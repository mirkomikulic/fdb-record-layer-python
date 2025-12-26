"""Connection pooling for FDB Record Layer.

Provides connection pooling for efficient database access across
multiple concurrent operations.
"""

from __future__ import annotations

import asyncio
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import (
    Any,
    Generic,
    TypeVar,
)

T = TypeVar("T")


@dataclass
class PoolConfig:
    """Configuration for connection pools.

    Attributes:
        min_connections: Minimum connections to maintain.
        max_connections: Maximum connections allowed.
        max_idle_time: Maximum time a connection can be idle (seconds).
        connection_timeout: Timeout for acquiring a connection (seconds).
        validation_interval: How often to validate connections (seconds).
    """

    min_connections: int = 2
    max_connections: int = 10
    max_idle_time: float = 300.0  # 5 minutes
    connection_timeout: float = 30.0
    validation_interval: float = 60.0


@dataclass
class PooledConnection(Generic[T]):
    """A connection managed by a pool.

    Attributes:
        connection: The underlying connection.
        created_at: When the connection was created.
        last_used_at: When the connection was last used.
        use_count: Number of times this connection has been used.
    """

    connection: T
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    use_count: int = 0

    def mark_used(self) -> None:
        """Mark the connection as used."""
        self.last_used_at = time.time()
        self.use_count += 1

    @property
    def idle_time(self) -> float:
        """Get the time since last use."""
        return time.time() - self.last_used_at

    @property
    def age(self) -> float:
        """Get the connection age."""
        return time.time() - self.created_at


class ConnectionPool(Generic[T]):
    """A generic connection pool.

    Manages a pool of connections, handling creation, validation,
    and cleanup.

    Example:
        >>> async def create_connection():
        ...     return await connect_to_db()
        >>>
        >>> pool = ConnectionPool(create_connection, PoolConfig(max_connections=5))
        >>> async with pool.acquire() as conn:
        ...     await conn.execute("SELECT 1")
    """

    def __init__(
        self,
        factory: Callable[[], Any],
        config: PoolConfig | None = None,
        validator: Callable[[T], bool] | None = None,
        closer: Callable[[T], Any] | None = None,
    ) -> None:
        """Initialize the connection pool.

        Args:
            factory: Function to create new connections.
            config: Pool configuration.
            validator: Optional function to validate connections.
            closer: Optional function to close connections.
        """
        self._factory = factory
        self._config = config or PoolConfig()
        self._validator = validator
        self._closer = closer

        self._available: list[PooledConnection[T]] = []
        self._in_use: dict[int, PooledConnection[T]] = {}
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition(self._lock)

        self._closed = False
        self._total_created = 0
        self._total_acquired = 0
        self._total_released = 0

    @property
    def size(self) -> int:
        """Get the total pool size."""
        return len(self._available) + len(self._in_use)

    @property
    def available_count(self) -> int:
        """Get the number of available connections."""
        return len(self._available)

    @property
    def in_use_count(self) -> int:
        """Get the number of connections in use."""
        return len(self._in_use)

    def acquire(self) -> PooledConnectionContext[T]:
        """Acquire a connection from the pool.

        Returns:
            A context manager that yields the connection.

        Raises:
            RuntimeError: If the pool is closed.
            TimeoutError: If acquisition times out.
        """
        if self._closed:
            raise RuntimeError("Pool is closed")

        return PooledConnectionContext(self)

    async def _acquire(self) -> PooledConnection[T]:
        """Internal acquire implementation."""
        deadline = time.time() + self._config.connection_timeout

        async with self._lock:
            while True:
                # Try to get an available connection
                while self._available:
                    conn = self._available.pop()

                    # Validate if needed
                    if self._validator is not None:
                        try:
                            if not self._validator(conn.connection):
                                await self._close_connection(conn)
                                continue
                        except Exception:
                            await self._close_connection(conn)
                            continue

                    # Check idle time
                    if conn.idle_time > self._config.max_idle_time:
                        await self._close_connection(conn)
                        continue

                    conn.mark_used()
                    self._in_use[id(conn)] = conn
                    self._total_acquired += 1
                    return conn

                # Create new connection if under limit
                if self.size < self._config.max_connections:
                    conn = await self._create_connection()
                    conn.mark_used()
                    self._in_use[id(conn)] = conn
                    self._total_acquired += 1
                    return conn

                # Wait for a connection to be released
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError("Connection acquisition timed out")

                try:
                    await asyncio.wait_for(
                        self._not_empty.wait(),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError("Connection acquisition timed out")

    async def _release(self, conn: PooledConnection[T]) -> None:
        """Release a connection back to the pool."""
        async with self._lock:
            conn_id = id(conn)
            if conn_id in self._in_use:
                del self._in_use[conn_id]
                self._total_released += 1

                # Return to available pool
                self._available.append(conn)
                self._not_empty.notify()

    async def _create_connection(self) -> PooledConnection[T]:
        """Create a new connection."""
        result = self._factory()
        if asyncio.iscoroutine(result):
            connection = await result
        else:
            connection = result

        self._total_created += 1
        return PooledConnection(connection=connection)

    async def _close_connection(self, conn: PooledConnection[T]) -> None:
        """Close a connection."""
        if self._closer is not None:
            try:
                result = self._closer(conn.connection)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass  # Ignore close errors

    async def close(self) -> None:
        """Close the pool and all connections."""
        async with self._lock:
            self._closed = True

            # Close all available connections
            for conn in self._available:
                await self._close_connection(conn)
            self._available.clear()

            # Close all in-use connections
            for conn in self._in_use.values():
                await self._close_connection(conn)
            self._in_use.clear()

    async def __aenter__(self) -> ConnectionPool[T]:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        return {
            "size": self.size,
            "available": self.available_count,
            "in_use": self.in_use_count,
            "total_created": self._total_created,
            "total_acquired": self._total_acquired,
            "total_released": self._total_released,
            "closed": self._closed,
        }


class PooledConnectionContext(Generic[T]):
    """Context manager for pooled connections."""

    def __init__(self, pool: ConnectionPool[T]) -> None:
        self._pool = pool
        self._conn: PooledConnection[T] | None = None

    async def __aenter__(self) -> T:
        self._conn = await self._pool._acquire()
        return self._conn.connection

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._conn is not None:
            await self._pool._release(self._conn)


class DatabasePool:
    """A pool specifically for FDB database connections.

    Wraps ConnectionPool with FDB-specific functionality.

    Example:
        >>> pool = DatabasePool(cluster_file="/path/to/fdb.cluster")
        >>> async with pool.transaction() as tr:
        ...     tr[b"key"] = b"value"
    """

    def __init__(
        self,
        cluster_file: str | None = None,
        config: PoolConfig | None = None,
    ) -> None:
        """Initialize the database pool.

        Args:
            cluster_file: Path to FDB cluster file.
            config: Pool configuration.
        """
        self._cluster_file = cluster_file
        self._config = config or PoolConfig()
        self._pool: ConnectionPool | None = None
        self._db: Any | None = None

    async def open(self) -> None:
        """Open the database pool."""
        try:
            import fdb

            fdb.api_version(710)
            self._db = fdb.open(self._cluster_file)
            db = self._db  # Capture for lambda

            # For FDB, we don't pool connections since FDB handles this
            # Instead, we pool transaction contexts
            self._pool = ConnectionPool(
                factory=lambda: db.create_transaction(),
                config=self._config,
            )
        except ImportError:
            # FDB not available, use mock
            self._db = MockDatabase()
            self._pool = ConnectionPool(
                factory=lambda: MockTransaction(),
                config=self._config,
            )

    async def close(self) -> None:
        """Close the database pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def transaction(self) -> PooledConnectionContext[Any]:
        """Get a transaction from the pool."""
        if self._pool is None:
            await self.open()
        assert self._pool is not None
        return self._pool.acquire()

    @property
    def database(self) -> Any:
        """Get the underlying database."""
        return self._db

    async def __aenter__(self) -> DatabasePool:
        await self.open()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


class MockDatabase:
    """Mock database for testing without FDB."""

    def __init__(self) -> None:
        self._data: dict[bytes, bytes] = {}

    def create_transaction(self) -> MockTransaction:
        return MockTransaction(self._data)


class MockTransaction:
    """Mock transaction for testing without FDB."""

    def __init__(self, data: dict[bytes, bytes] | None = None) -> None:
        self._data = data if data is not None else {}
        self._pending: dict[bytes, bytes | None] = {}

    def __getitem__(self, key: bytes) -> bytes | None:
        if key in self._pending:
            return self._pending[key]
        return self._data.get(key)

    def __setitem__(self, key: bytes, value: bytes) -> None:
        self._pending[key] = value

    def __delitem__(self, key: bytes) -> None:
        self._pending[key] = None

    def commit(self) -> None:
        for key, value in self._pending.items():
            if value is None:
                self._data.pop(key, None)
            else:
                self._data[key] = value
        self._pending.clear()

    def cancel(self) -> None:
        self._pending.clear()


class ContextPool(Generic[T]):
    """A pool for FDBRecordContext instances.

    Pools context instances for efficient reuse across operations.
    """

    def __init__(
        self,
        context_factory: Callable[[], T],
        config: PoolConfig | None = None,
    ) -> None:
        """Initialize the context pool.

        Args:
            context_factory: Function to create new contexts.
            config: Pool configuration.
        """
        self._factory = context_factory
        self._config = config or PoolConfig()
        self._pool: list[T] = []
        self._in_use: weakref.WeakSet[T] = weakref.WeakSet()
        self._lock = asyncio.Lock()

    async def acquire(self) -> T:
        """Acquire a context from the pool."""
        async with self._lock:
            if self._pool:
                ctx = self._pool.pop()
            else:
                ctx = self._factory()

            self._in_use.add(ctx)
            return ctx

    async def release(self, ctx: T) -> None:
        """Release a context back to the pool."""
        async with self._lock:
            if len(self._pool) < self._config.max_connections:
                self._pool.append(ctx)

    async def close(self) -> None:
        """Close the pool."""
        async with self._lock:
            self._pool.clear()
