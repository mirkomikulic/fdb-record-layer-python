"""Lifecycle management for FDB Record Layer.

Provides graceful shutdown handling, signal management, and cleanup hooks.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import signal
import threading
import time
import weakref
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb_record_layer.utils.pool import ConnectionPool

logger = logging.getLogger(__name__)


def _safe_log(level: int, msg: str) -> None:
    """Log a message, suppressing errors if the stream is closed.

    During process shutdown, logging streams may be closed before
    the shutdown thread finishes. This function suppresses the
    "--- Logging error ---" messages that would otherwise be printed.
    """
    # Temporarily disable logging error reporting
    old_raise = logging.raiseExceptions
    logging.raiseExceptions = False
    try:
        logger.log(level, msg)
    finally:
        logging.raiseExceptions = old_raise


class LifecycleState(str, Enum):
    """Application lifecycle state."""

    STARTING = "starting"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


@dataclass
class ShutdownConfig:
    """Configuration for graceful shutdown."""

    # Maximum time to wait for graceful shutdown (seconds)
    timeout_seconds: float = 30.0

    # Time to wait for in-flight requests to complete
    drain_timeout_seconds: float = 10.0

    # Whether to force shutdown after timeout
    force_on_timeout: bool = True

    # Signals to handle
    signals: list[signal.Signals] = field(default_factory=lambda: [signal.SIGTERM, signal.SIGINT])


class LifecycleManager:
    """Manages application lifecycle with graceful shutdown.

    Provides:
    - Signal handling (SIGTERM, SIGINT)
    - Graceful shutdown with timeout
    - Cleanup hook registration
    - Connection draining
    - State tracking

    Example:
        >>> lifecycle = LifecycleManager()
        >>> lifecycle.register_pool(pool)
        >>> lifecycle.register_shutdown_hook(cleanup_fn)
        >>> lifecycle.start()
        >>> # ... application runs ...
        >>> # On SIGTERM, graceful shutdown begins automatically
    """

    def __init__(self, config: ShutdownConfig | None = None) -> None:
        """Initialize the lifecycle manager.

        Args:
            config: Shutdown configuration.
        """
        self._config = config or ShutdownConfig()
        self._state = LifecycleState.STARTING
        self._state_lock = threading.Lock()

        # Registered resources
        self._pools: list[weakref.ref[ConnectionPool]] = []
        self._shutdown_hooks: list[Callable[[], Any]] = []
        self._async_shutdown_hooks: list[Callable[[], Coroutine[Any, Any, Any]]] = []

        # Signal handling
        self._original_handlers: dict[signal.Signals, Any] = {}
        self._shutdown_event = threading.Event()
        self._async_shutdown_event: asyncio.Event | None = None

        # Tracking
        self._start_time: float | None = None
        self._shutdown_start_time: float | None = None
        self._in_flight_count = 0
        self._in_flight_lock = threading.Lock()
        self._atexit_registered = False

    @property
    def state(self) -> LifecycleState:
        """Get the current lifecycle state."""
        with self._state_lock:
            return self._state

    @property
    def is_running(self) -> bool:
        """Check if the application is running."""
        return self.state == LifecycleState.RUNNING

    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self.state == LifecycleState.SHUTTING_DOWN

    @property
    def uptime_seconds(self) -> float:
        """Get the application uptime in seconds."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def register_pool(self, pool: ConnectionPool) -> None:
        """Register a connection pool for shutdown draining.

        Args:
            pool: The connection pool to drain on shutdown.
        """
        self._pools.append(weakref.ref(pool))
        logger.debug("Registered pool for lifecycle management")

    def register_shutdown_hook(self, hook: Callable[[], Any]) -> None:
        """Register a synchronous shutdown hook.

        Hooks are called in reverse order of registration.

        Args:
            hook: Function to call during shutdown.
        """
        self._shutdown_hooks.append(hook)
        hook_name = hook.__name__ if hasattr(hook, "__name__") else "anonymous"
        logger.debug(f"Registered shutdown hook: {hook_name}")

    def register_async_shutdown_hook(self, hook: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        """Register an async shutdown hook.

        Args:
            hook: Async function to call during shutdown.
        """
        self._async_shutdown_hooks.append(hook)
        hook_name = hook.__name__ if hasattr(hook, "__name__") else "anonymous"
        logger.debug(f"Registered async shutdown hook: {hook_name}")

    def start(self) -> None:
        """Start the lifecycle manager and install signal handlers.

        This should be called once when the application starts.
        """
        with self._state_lock:
            if self._state != LifecycleState.STARTING:
                raise RuntimeError(f"Cannot start from state {self._state}")
            self._state = LifecycleState.RUNNING

        self._start_time = time.time()

        # Install signal handlers
        self._install_signal_handlers()

        # Register atexit handler
        atexit.register(self._atexit_handler)
        self._atexit_registered = True

        logger.info("Lifecycle manager started")

    def request_shutdown(self) -> None:
        """Request graceful shutdown.

        Can be called programmatically to trigger shutdown.
        """
        self._initiate_shutdown("programmatic request")

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for shutdown to complete.

        Args:
            timeout: Maximum time to wait (None = wait forever).

        Returns:
            True if shutdown completed, False if timeout.
        """
        return self._shutdown_event.wait(timeout=timeout)

    async def wait_for_shutdown_async(self) -> None:
        """Async wait for shutdown to complete."""
        if self._async_shutdown_event is None:
            self._async_shutdown_event = asyncio.Event()

        await self._async_shutdown_event.wait()

    def track_in_flight(self) -> InFlightContext:
        """Track an in-flight request.

        Use as a context manager to track active requests for draining.

        Returns:
            Context manager for tracking.
        """
        return InFlightContext(self)

    def _increment_in_flight(self) -> None:
        """Increment in-flight counter."""
        with self._in_flight_lock:
            self._in_flight_count += 1

    def _decrement_in_flight(self) -> None:
        """Decrement in-flight counter."""
        with self._in_flight_lock:
            self._in_flight_count -= 1

    def _get_in_flight_count(self) -> int:
        """Get current in-flight count."""
        with self._in_flight_lock:
            return self._in_flight_count

    def _install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        for sig in self._config.signals:
            try:
                self._original_handlers[sig] = signal.signal(sig, self._signal_handler)
                logger.debug(f"Installed signal handler for {sig.name}")
            except (ValueError, OSError) as e:
                # Signal handling may not work in all environments (e.g., threads)
                logger.warning(f"Could not install signal handler for {sig.name}: {e}")

    def _restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        sig_name = signal.Signals(signum).name
        _safe_log(logging.INFO, f"Received signal {sig_name}")
        self._initiate_shutdown(f"signal {sig_name}")

    def _initiate_shutdown(self, reason: str) -> None:
        """Initiate graceful shutdown."""
        with self._state_lock:
            if self._state != LifecycleState.RUNNING:
                _safe_log(logging.WARNING, f"Shutdown requested but state is {self._state}")
                return
            self._state = LifecycleState.SHUTTING_DOWN

        self._shutdown_start_time = time.time()
        _safe_log(logging.INFO, f"Initiating graceful shutdown: {reason}")

        # Run shutdown in a thread to not block the signal handler
        shutdown_thread = threading.Thread(
            target=self._run_shutdown,
            daemon=False,
            name="shutdown-thread",
        )
        shutdown_thread.start()

    def _run_shutdown(self) -> None:
        """Execute the shutdown sequence."""
        try:
            # 1. Stop accepting new requests (handled by application)
            _safe_log(logging.INFO, "Phase 1: Stopping new requests")

            # 2. Wait for in-flight requests to drain
            _safe_log(logging.INFO, "Phase 2: Draining in-flight requests")
            self._drain_in_flight()

            # 3. Close connection pools
            _safe_log(logging.INFO, "Phase 3: Closing connection pools")
            self._close_pools()

            # 4. Run shutdown hooks (reverse order)
            _safe_log(logging.INFO, "Phase 4: Running shutdown hooks")
            self._run_shutdown_hooks()

            # 5. Mark as stopped
            with self._state_lock:
                self._state = LifecycleState.STOPPED

            _safe_log(logging.INFO, "Graceful shutdown completed")

        except Exception as e:
            _safe_log(logging.ERROR, f"Error during shutdown: {e}")
            with self._state_lock:
                self._state = LifecycleState.STOPPED

        finally:
            # Signal shutdown complete
            self._shutdown_event.set()
            if self._async_shutdown_event:
                # Schedule the event set in the event loop if running
                try:
                    loop = asyncio.get_running_loop()
                    loop.call_soon_threadsafe(self._async_shutdown_event.set)
                except RuntimeError:
                    pass

            # Restore signal handlers
            self._restore_signal_handlers()

    def _drain_in_flight(self) -> None:
        """Wait for in-flight requests to complete."""
        deadline = time.time() + self._config.drain_timeout_seconds
        check_interval = 0.1

        while time.time() < deadline:
            count = self._get_in_flight_count()
            if count == 0:
                _safe_log(logging.INFO, "All in-flight requests completed")
                return

            _safe_log(logging.DEBUG, f"Waiting for {count} in-flight requests")
            time.sleep(check_interval)

        remaining = self._get_in_flight_count()
        if remaining > 0:
            _safe_log(logging.WARNING, f"Drain timeout: {remaining} requests still in flight")

    def _close_pools(self) -> None:
        """Close all registered connection pools."""
        for pool_ref in self._pools:
            pool = pool_ref()
            if pool is not None:
                try:
                    # Check if there's a running event loop
                    try:
                        loop = asyncio.get_running_loop()
                        # Schedule async close
                        asyncio.run_coroutine_threadsafe(pool.close(), loop).result(timeout=5.0)
                    except RuntimeError:
                        # No event loop, try sync close if available
                        if hasattr(pool, "close_sync"):
                            pool.close_sync()
                        else:
                            # Create a new event loop for cleanup
                            asyncio.run(pool.close())

                    _safe_log(logging.DEBUG, "Closed connection pool")
                except Exception as e:
                    _safe_log(logging.WARNING, f"Error closing pool: {e}")

    def _run_shutdown_hooks(self) -> None:
        """Run all registered shutdown hooks."""
        # Run sync hooks in reverse order
        for hook in reversed(self._shutdown_hooks):
            try:
                hook_name = hook.__name__ if hasattr(hook, "__name__") else "anonymous"
                _safe_log(logging.DEBUG, f"Running shutdown hook: {hook_name}")
                hook()
            except Exception as e:
                _safe_log(logging.ERROR, f"Error in shutdown hook: {e}")

        # Run async hooks
        if self._async_shutdown_hooks:
            try:
                loop = asyncio.get_running_loop()
                for hook in reversed(self._async_shutdown_hooks):
                    try:
                        asyncio.run_coroutine_threadsafe(hook(), loop).result(timeout=5.0)
                    except Exception as e:
                        _safe_log(logging.ERROR, f"Error in async shutdown hook: {e}")
            except RuntimeError:
                # No running event loop, create one
                async def run_async_hooks() -> None:
                    for hook in reversed(self._async_shutdown_hooks):
                        try:
                            await hook()
                        except Exception as e:
                            _safe_log(logging.ERROR, f"Error in async shutdown hook: {e}")

                asyncio.run(run_async_hooks())

    def _atexit_handler(self) -> None:
        """Handle atexit for cleanup."""
        if self.state == LifecycleState.RUNNING:
            _safe_log(logging.INFO, "Atexit triggered - initiating shutdown")
            self._initiate_shutdown("atexit")
            self._shutdown_event.wait(timeout=self._config.timeout_seconds)

    def cleanup(self) -> None:
        """Clean up this lifecycle manager.

        Unregisters the atexit handler and restores signal handlers.
        Call this before discarding a lifecycle manager to prevent
        zombie atexit handlers.
        """
        if self._atexit_registered:
            try:
                atexit.unregister(self._atexit_handler)
            except Exception:
                pass  # Ignore errors during cleanup
            self._atexit_registered = False

        # Restore signal handlers if they were installed
        self._restore_signal_handlers()


class InFlightContext:
    """Context manager for tracking in-flight requests."""

    def __init__(self, manager: LifecycleManager) -> None:
        self._manager = manager

    def __enter__(self) -> InFlightContext:
        self._manager._increment_in_flight()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._manager._decrement_in_flight()

    async def __aenter__(self) -> InFlightContext:
        self._manager._increment_in_flight()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._manager._decrement_in_flight()


# Global lifecycle manager instance
_global_lifecycle: LifecycleManager | None = None
_lifecycle_lock = threading.Lock()


def get_lifecycle() -> LifecycleManager:
    """Get or create the global lifecycle manager."""
    global _global_lifecycle
    with _lifecycle_lock:
        if _global_lifecycle is None:
            _global_lifecycle = LifecycleManager()
        return _global_lifecycle


def init_lifecycle(config: ShutdownConfig | None = None) -> LifecycleManager:
    """Initialize and start the global lifecycle manager.

    Args:
        config: Optional shutdown configuration.

    Returns:
        The initialized lifecycle manager.
    """
    global _global_lifecycle
    with _lifecycle_lock:
        if _global_lifecycle is not None and _global_lifecycle.is_running:
            raise RuntimeError("Lifecycle manager already initialized and running")
        _global_lifecycle = LifecycleManager(config)
        _global_lifecycle.start()
        return _global_lifecycle


def shutdown() -> None:
    """Request graceful shutdown of the global lifecycle manager."""
    manager = get_lifecycle()
    manager.request_shutdown()


def reset_lifecycle() -> None:
    """Reset the global lifecycle manager (for testing).

    Properly cleans up the existing manager before creating a new one,
    including unregistering atexit handlers to prevent zombie handlers.
    """
    global _global_lifecycle
    with _lifecycle_lock:
        if _global_lifecycle is not None:
            _global_lifecycle.cleanup()
        _global_lifecycle = None
