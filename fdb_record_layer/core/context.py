"""Transaction context and database connection management."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

import fdb

from fdb_record_layer.core.exceptions import (
    TransactionConflictError,
    TransactionRetryLimitExceeded,
    TransactionTimeoutError,
)

# Module logger
_logger = logging.getLogger("fdb_record_layer.core.context")

if TYPE_CHECKING:
    from fdb import Database, Transaction

T = TypeVar("T")

# Initialize FDB API version
fdb.api_version(730)


@dataclass
class RetryConfig:
    """Configuration for transaction retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts (0 = unlimited).
        initial_delay_ms: Initial delay between retries in milliseconds.
        max_delay_ms: Maximum delay between retries in milliseconds.
        backoff_multiplier: Multiplier for exponential backoff.
        timeout_seconds: Total timeout for all retries (0 = no timeout).
    """

    max_retries: int = 10
    initial_delay_ms: float = 10.0
    max_delay_ms: float = 1000.0
    backoff_multiplier: float = 2.0
    timeout_seconds: float = 0.0

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay in seconds for a given attempt number."""
        delay_ms = self.initial_delay_ms * (self.backoff_multiplier**attempt)
        delay_ms = min(delay_ms, self.max_delay_ms)
        return delay_ms / 1000.0


# Default retry configuration
DEFAULT_RETRY_CONFIG = RetryConfig()


@dataclass
class FDBRecordContext:
    """Wraps an FDB transaction with record layer state and lifecycle management.

    The context provides:
    - Transaction access
    - Commit hooks for post-commit actions
    - Read version caching
    - Timer tracking for transaction duration
    """

    database: Database
    _transaction: Transaction | None = field(default=None, repr=False)
    _read_version: int | None = None
    _committed_version: int | None = None
    _commit_hooks: list[Callable[[], None]] = field(default_factory=list)
    _closed: bool = False

    @property
    def transaction(self) -> Transaction:
        """Get or create the underlying FDB transaction."""
        if self._closed:
            raise RuntimeError("Context has been closed")
        if self._transaction is None:
            self._transaction = self.database.create_transaction()
        return self._transaction

    @property
    def is_closed(self) -> bool:
        """Check if the context has been closed."""
        return self._closed

    def ensure_active(self) -> None:
        """Ensure the context is still active."""
        if self._closed:
            raise RuntimeError("Context has been closed")

    async def get_read_version(self) -> int:
        """Get the read version of the transaction, caching the result."""
        if self._read_version is None:
            # FDB Python client is synchronous, wrap in executor
            loop = asyncio.get_event_loop()
            version = await loop.run_in_executor(None, self.transaction.get_read_version().wait)
            self._read_version = int(version)
        return self._read_version

    def add_commit_hook(self, hook: Callable[[], None]) -> None:
        """Add a hook to be called after successful commit.

        Hooks are called in order of registration after the transaction commits.
        """
        self._commit_hooks.append(hook)

    async def commit(self) -> int:
        """Commit the transaction and return the committed version.

        Runs all registered commit hooks after successful commit.
        """
        self.ensure_active()

        start_time = time.perf_counter()
        _logger.debug("Committing transaction")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.transaction.commit().wait)
        self._committed_version = self.transaction.get_committed_version()

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Transaction committed",
            extra={
                "committed_version": self._committed_version,
                "duration_ms": round(duration_ms, 2),
            },
        )

        # Run commit hooks
        for hook in self._commit_hooks:
            try:
                hook()
            except Exception as e:
                _logger.warning(
                    "Commit hook failed",
                    extra={"hook": hook.__name__, "error": str(e)},
                )

        return self._committed_version

    def reset(self) -> None:
        """Reset the context with a fresh transaction.

        This is used after a retryable error to start a new transaction
        while keeping the same context. Clears all cached state.
        """
        if self._closed:
            raise RuntimeError("Cannot reset a closed context")

        # Cancel any existing transaction
        if self._transaction is not None:
            try:
                self._transaction.cancel()
            except Exception:
                pass  # Ignore errors during cancel
            self._transaction = None

        # Clear cached state
        self._read_version = None
        self._committed_version = None
        self._commit_hooks = []

        _logger.debug("Context reset with fresh transaction")

    def close(self) -> None:
        """Close the context, releasing the transaction."""
        if not self._closed:
            self._closed = True
            if self._transaction is not None:
                try:
                    self._transaction.cancel()
                except Exception:
                    pass  # Ignore errors during cancel
                self._transaction = None

    def __enter__(self) -> FDBRecordContext:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class FDBDatabase:
    """Manages database connections and provides context creation.

    This is the main entry point for working with the Record Layer.

    Example:
        >>> db = FDBDatabase()
        >>> async def save_person(ctx):
        ...     store = FDBRecordStore(ctx, subspace, metadata)
        ...     return await store.save_record(person)
        >>> result = await db.run(save_person)
    """

    def __init__(
        self,
        cluster_file: str | None = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize the database connection.

        Args:
            cluster_file: Path to the FDB cluster file. If None, uses default.
            retry_config: Configuration for transaction retries.
        """
        self._db: Database = fdb.open(cluster_file)
        self._cluster_file = cluster_file
        self._retry_config = retry_config or DEFAULT_RETRY_CONFIG

    @property
    def database(self) -> Database:
        """Get the underlying FDB database."""
        return self._db

    @property
    def retry_config(self) -> RetryConfig:
        """Get the retry configuration."""
        return self._retry_config

    def open_context(self) -> FDBRecordContext:
        """Create a new record context with a fresh transaction."""
        return FDBRecordContext(database=self._db)

    async def run(
        self,
        func: Callable[[FDBRecordContext], T],
        retry_config: RetryConfig | None = None,
    ) -> T:
        """Run a transactional function with automatic retry.

        The function will be retried on retryable FDB errors (conflicts,
        network errors, etc.) up to the configured retry limit.

        Args:
            func: An async or sync function that takes an FDBRecordContext.
                  Should be idempotent as it may be retried.
            retry_config: Override retry configuration for this call.

        Returns:
            The result of the function.

        Raises:
            TransactionRetryLimitExceeded: If retry limit is exceeded.
            TransactionTimeoutError: If timeout is exceeded.
            TransactionConflictError: If a conflict cannot be resolved.

        Example:
            >>> async def update_balance(ctx):
            ...     store = FDBRecordStore(ctx, subspace, metadata)
            ...     account = await store.load_record("Account", (account_id,))
            ...     account.balance += amount
            ...     return await store.save_record(account)
            >>> await db.run(update_balance)
        """
        config = retry_config or self._retry_config
        func_name = getattr(func, "__name__", repr(func))
        retry_count = 0
        start_time = time.perf_counter()
        last_error: Exception | None = None

        while True:
            # Check timeout
            if config.timeout_seconds > 0:
                elapsed = time.perf_counter() - start_time
                if elapsed >= config.timeout_seconds:
                    raise TransactionTimeoutError(config.timeout_seconds)

            # Check retry limit
            if config.max_retries > 0 and retry_count > config.max_retries:
                raise TransactionRetryLimitExceeded(retry_count, last_error)

            ctx = self.open_context()
            try:
                # Execute the function
                if asyncio.iscoroutinefunction(func):
                    result = await func(ctx)
                else:
                    result = func(ctx)

                # Commit the transaction
                await ctx.commit()

                # Log success
                duration_ms = (time.perf_counter() - start_time) * 1000
                if retry_count > 0:
                    _logger.info(
                        "Transaction succeeded after retries",
                        extra={
                            "function": func_name,
                            "retries": retry_count,
                            "duration_ms": round(duration_ms, 2),
                        },
                    )
                else:
                    _logger.debug(
                        "Transaction succeeded",
                        extra={
                            "function": func_name,
                            "duration_ms": round(duration_ms, 2),
                        },
                    )
                return result

            except fdb.FDBError as e:
                last_error = e
                retry_count += 1

                _logger.debug(
                    "Transaction error, checking if retryable",
                    extra={
                        "function": func_name,
                        "error_code": e.code,
                        "retry_count": retry_count,
                    },
                )

                # Use FDB's built-in retry logic to determine if retryable
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, ctx.transaction.on_error(e.code).wait)
                except fdb.FDBError:
                    # Not retryable
                    raise TransactionConflictError(f"FDB error {e.code}: {e}") from e

                # Apply backoff delay
                delay = config.calculate_delay(retry_count - 1)
                if delay > 0:
                    await asyncio.sleep(delay)

            finally:
                ctx.close()

    async def run_async(
        self,
        func: Callable[[FDBRecordContext], T],
        retry_config: RetryConfig | None = None,
    ) -> T:
        """Alias for run() for clarity when using async functions."""
        return await self.run(func, retry_config)

    def run_sync(
        self,
        func: Callable[[FDBRecordContext], T],
        retry_config: RetryConfig | None = None,
    ) -> T:
        """Run a transactional function synchronously.

        This is a convenience method for synchronous code. It runs the
        async run() method in a new event loop.

        Args:
            func: A sync function that takes an FDBRecordContext.
            retry_config: Override retry configuration for this call.

        Returns:
            The result of the function.
        """
        return asyncio.get_event_loop().run_until_complete(self.run(func, retry_config))
