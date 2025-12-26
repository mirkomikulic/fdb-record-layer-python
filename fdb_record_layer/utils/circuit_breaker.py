"""Circuit breaker pattern for fault tolerance.

Implements the circuit breaker pattern to prevent cascading failures
when the database is unavailable or under stress.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, TypeVar

_logger = logging.getLogger("fdb_record_layer.circuit_breaker")

T = TypeVar("T")


class CircuitState(Enum):
    """State of the circuit breaker."""

    CLOSED = auto()  # Normal operation, requests pass through
    OPEN = auto()  # Failing, requests are rejected
    HALF_OPEN = auto()  # Testing if service recovered


class CircuitOpenError(Exception):
    """Raised when the circuit is open and requests are rejected."""

    def __init__(self, message: str = "Circuit breaker is open") -> None:
        super().__init__(message)
        self.message = message


@dataclass
class CircuitBreakerConfig:
    """Configuration for the circuit breaker.

    Attributes:
        failure_threshold: Number of failures before opening circuit.
        success_threshold: Successes in half-open to close circuit.
        timeout_seconds: Time before trying again after opening.
        excluded_exceptions: Exceptions that don't count as failures.
    """

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 30.0
    excluded_exceptions: tuple = ()


@dataclass
class CircuitBreakerStats:
    """Statistics for the circuit breaker."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0
    state_changes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None


class CircuitBreaker:
    """Circuit breaker implementation.

    The circuit breaker prevents cascading failures by:
    1. CLOSED: Normal operation, requests pass through
    2. OPEN: After threshold failures, requests are immediately rejected
    3. HALF_OPEN: After timeout, allows test requests to check recovery

    Example:
        >>> breaker = CircuitBreaker("database", config)
        >>> async def query():
        ...     async with breaker:
        ...         return await database.query(...)
        >>> try:
        ...     result = await query()
        ... except CircuitOpenError:
        ...     # Handle circuit open (e.g., return cached data)
        ...     pass
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            name: Name for logging and identification.
            config: Configuration options.
        """
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """Get the circuit breaker name."""
        return self._name

    @property
    def state(self) -> CircuitState:
        """Get the current circuit state."""
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        return self._stats

    @property
    def is_closed(self) -> bool:
        """Check if the circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if the circuit is open (rejecting requests)."""
        return self._state == CircuitState.OPEN

    async def _should_allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # Check if timeout has expired
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self._config.timeout_seconds:
                    await self._transition_to(CircuitState.HALF_OPEN)
                    return True
            return False

        # HALF_OPEN: allow limited requests
        return True

    async def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self._stats.state_changes += 1

            if new_state == CircuitState.CLOSED:
                self._failure_count = 0
                self._success_count = 0
            elif new_state == CircuitState.HALF_OPEN:
                self._success_count = 0

            _logger.info(
                f"Circuit breaker '{self._name}' state changed",
                extra={
                    "circuit": self._name,
                    "old_state": old_state.name,
                    "new_state": new_state.name,
                },
            )

    async def _record_success(self) -> None:
        """Record a successful request."""
        self._stats.total_requests += 1
        self._stats.successful_requests += 1
        self._stats.last_success_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                await self._transition_to(CircuitState.CLOSED)

    async def _record_failure(self, exc: Exception) -> None:
        """Record a failed request."""
        self._stats.total_requests += 1
        self._stats.failed_requests += 1
        self._stats.last_failure_time = time.time()
        self._last_failure_time = time.time()

        # Check if this exception should be counted
        if isinstance(exc, self._config.excluded_exceptions):
            return

        if self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self._config.failure_threshold:
                await self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.HALF_OPEN:
            await self._transition_to(CircuitState.OPEN)

    async def _record_rejection(self) -> None:
        """Record a rejected request."""
        self._stats.total_requests += 1
        self._stats.rejected_requests += 1

    async def __aenter__(self) -> CircuitBreaker:
        """Enter the circuit breaker context."""
        async with self._lock:
            if not await self._should_allow_request():
                await self._record_rejection()
                raise CircuitOpenError(f"Circuit breaker '{self._name}' is open")
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> bool:
        """Exit the circuit breaker context."""
        async with self._lock:
            if exc_type is None:
                await self._record_success()
            elif exc_val is not None:
                await self._record_failure(exc_val)
        return False  # Don't suppress exceptions

    async def execute(  # type: ignore[return]
        self, func: Callable[..., T], *args: Any, **kwargs: Any
    ) -> T:
        """Execute a function with circuit breaker protection.

        Args:
            func: The function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the function.

        Raises:
            CircuitOpenError: If the circuit is open.
        """
        async with self:
            if asyncio.iscoroutinefunction(func):
                result: T = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            return result

    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        _logger.info(
            f"Circuit breaker '{self._name}' reset",
            extra={"circuit": self._name},
        )


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker by name."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def remove(self, name: str) -> None:
        """Remove a circuit breaker."""
        self._breakers.pop(name, None)

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()

    def get_all_stats(self) -> dict[str, CircuitBreakerStats]:
        """Get statistics for all circuit breakers."""
        return {name: cb.stats for name, cb in self._breakers.items()}


# Global registry
_registry: CircuitBreakerRegistry | None = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get the global circuit breaker registry."""
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry


def get_circuit_breaker(
    name: str,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    return get_circuit_breaker_registry().get(name, config)


def reset_circuit_breakers() -> None:
    """Reset the global circuit breaker registry."""
    global _registry
    _registry = None
