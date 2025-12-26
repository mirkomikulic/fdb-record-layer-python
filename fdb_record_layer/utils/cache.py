"""Query plan caching for FDB Record Layer.

Provides caching mechanisms for query plans and other
frequently accessed data to improve performance.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import (
    Any,
    Generic,
    TypeVar,
)

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass
class CacheConfig:
    """Configuration for caches.

    Attributes:
        max_size: Maximum number of entries.
        ttl_seconds: Time-to-live in seconds (0 = no expiry).
        stats_enabled: Whether to collect statistics.
    """

    max_size: int = 1000
    ttl_seconds: float = 0.0
    stats_enabled: bool = True


@dataclass
class CacheEntry(Generic[V]):
    """An entry in the cache.

    Attributes:
        value: The cached value.
        created_at: When the entry was created.
        accessed_at: When the entry was last accessed.
        access_count: Number of times accessed.
    """

    value: V
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0

    def touch(self) -> None:
        """Mark the entry as accessed."""
        self.accessed_at = time.time()
        self.access_count += 1

    @property
    def age(self) -> float:
        """Get the entry age in seconds."""
        return time.time() - self.created_at

    def is_expired(self, ttl: float) -> bool:
        """Check if the entry has expired."""
        if ttl <= 0:
            return False
        return self.age > ttl


@dataclass
class CacheStats:
    """Statistics for cache operations.

    Attributes:
        hits: Number of cache hits.
        misses: Number of cache misses.
        evictions: Number of evictions.
        expirations: Number of expirations.
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    def reset(self) -> None:
        """Reset all statistics."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0


class LRUCache(Generic[K, V]):
    """A thread-safe LRU cache.

    Uses an ordered dictionary to maintain LRU order efficiently.

    Example:
        >>> cache = LRUCache(max_size=100)
        >>> cache.put("key", "value")
        >>> value = cache.get("key")
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        """Initialize the cache.

        Args:
            config: Cache configuration.
        """
        self._config = config or CacheConfig()
        self._cache: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats()

    def get(self, key: K, default: V | None = None) -> V | None:
        """Get a value from the cache.

        Args:
            key: The cache key.
            default: Default value if not found.

        Returns:
            The cached value or default.
        """
        with self._lock:
            if key not in self._cache:
                if self._config.stats_enabled:
                    self._stats.misses += 1
                return default

            entry = self._cache[key]

            # Check expiration
            if entry.is_expired(self._config.ttl_seconds):
                del self._cache[key]
                if self._config.stats_enabled:
                    self._stats.expirations += 1
                    self._stats.misses += 1
                return default

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.touch()

            if self._config.stats_enabled:
                self._stats.hits += 1

            return entry.value

    def put(self, key: K, value: V) -> None:
        """Put a value in the cache.

        Args:
            key: The cache key.
            value: The value to cache.
        """
        with self._lock:
            if key in self._cache:
                # Update existing
                self._cache[key].value = value
                self._cache[key].touch()
                self._cache.move_to_end(key)
            else:
                # Add new
                self._cache[key] = CacheEntry(value=value)

                # Evict if over capacity
                while len(self._cache) > self._config.max_size:
                    self._cache.popitem(last=False)
                    if self._config.stats_enabled:
                        self._stats.evictions += 1

    def remove(self, key: K) -> bool:
        """Remove a value from the cache.

        Args:
            key: The cache key.

        Returns:
            True if the key was removed.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()

    def contains(self, key: K) -> bool:
        """Check if a key is in the cache."""
        with self._lock:
            if key not in self._cache:
                return False
            entry = self._cache[key]
            if entry.is_expired(self._config.ttl_seconds):
                del self._cache[key]
                return False
            return True

    @property
    def size(self) -> int:
        """Get the current cache size."""
        return len(self._cache)

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    def get_or_compute(
        self,
        key: K,
        compute: Callable[[], V],
    ) -> V:
        """Get from cache or compute and cache.

        Args:
            key: The cache key.
            compute: Function to compute the value if not cached.

        Returns:
            The cached or computed value.
        """
        value = self.get(key)
        if value is not None:
            return value

        value = compute()
        self.put(key, value)
        return value


class QueryPlanCache:
    """Cache for query plans.

    Caches compiled query plans to avoid re-planning identical queries.

    Example:
        >>> cache = QueryPlanCache()
        >>> plan = cache.get_or_compile(query, lambda q: planner.plan(q))
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        """Initialize the plan cache.

        Args:
            config: Cache configuration.
        """
        self._config = config or CacheConfig(max_size=500)
        self._cache: LRUCache[str, Any] = LRUCache(self._config)

    def get(self, query: Any) -> Any | None:
        """Get a cached plan for a query.

        Args:
            query: The query object.

        Returns:
            The cached plan or None.
        """
        key = self._compute_key(query)
        return self._cache.get(key)

    def put(self, query: Any, plan: Any) -> None:
        """Cache a plan for a query.

        Args:
            query: The query object.
            plan: The compiled plan.
        """
        key = self._compute_key(query)
        self._cache.put(key, plan)

    def get_or_compile(
        self,
        query: Any,
        compiler: Callable[[Any], Any],
    ) -> Any:
        """Get cached plan or compile and cache.

        Args:
            query: The query object.
            compiler: Function to compile the query.

        Returns:
            The cached or compiled plan.
        """
        key = self._compute_key(query)
        plan = self._cache.get(key)
        if plan is not None:
            return plan

        plan = compiler(query)
        self._cache.put(key, plan)
        return plan

    def invalidate(self, query: Any) -> bool:
        """Invalidate a cached plan.

        Args:
            query: The query object.

        Returns:
            True if a plan was invalidated.
        """
        key = self._compute_key(query)
        return self._cache.remove(key)

    def invalidate_for_table(self, table_name: str) -> int:
        """Invalidate all plans involving a table.

        Args:
            table_name: The table name.

        Returns:
            Number of plans invalidated.
        """
        # This is a simple implementation that requires
        # iterating through the cache
        count = 0
        with self._cache._lock:
            keys_to_remove = [key for key in self._cache._cache.keys() if table_name in key]
            for key in keys_to_remove:
                del self._cache._cache[key]
                count += 1
        return count

    def clear(self) -> None:
        """Clear the plan cache."""
        self._cache.clear()

    def _compute_key(self, query: Any) -> str:
        """Compute a cache key for a query.

        Args:
            query: The query object.

        Returns:
            A string cache key.
        """
        # Get a string representation of the query
        if hasattr(query, "to_cache_key"):
            query_str = query.to_cache_key()
        elif hasattr(query, "__dict__"):
            query_str = str(sorted(query.__dict__.items()))
        else:
            query_str = str(query)

        # Hash for fixed-size keys
        return hashlib.sha256(query_str.encode()).hexdigest()

    @property
    def size(self) -> int:
        """Get the number of cached plans."""
        return self._cache.size

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._cache.stats


class SQLPlanCache:
    """Cache for SQL query plans.

    Caches parsed SQL and their execution plans.

    Example:
        >>> cache = SQLPlanCache()
        >>> plan = cache.get_or_compile(
        ...     "SELECT * FROM users WHERE id = ?",
        ...     lambda sql: compile_sql(sql)
        ... )
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        """Initialize the SQL plan cache.

        Args:
            config: Cache configuration.
        """
        self._config = config or CacheConfig(max_size=500)
        self._cache: LRUCache[str, Any] = LRUCache(self._config)

    def get(self, sql: str) -> Any | None:
        """Get a cached plan for SQL.

        Args:
            sql: The SQL statement.

        Returns:
            The cached plan or None.
        """
        key = self._normalize_sql(sql)
        return self._cache.get(key)

    def put(self, sql: str, plan: Any) -> None:
        """Cache a plan for SQL.

        Args:
            sql: The SQL statement.
            plan: The compiled plan.
        """
        key = self._normalize_sql(sql)
        self._cache.put(key, plan)

    def get_or_compile(
        self,
        sql: str,
        compiler: Callable[[str], Any],
    ) -> Any:
        """Get cached plan or compile and cache.

        Args:
            sql: The SQL statement.
            compiler: Function to compile the SQL.

        Returns:
            The cached or compiled plan.
        """
        key = self._normalize_sql(sql)
        plan = self._cache.get(key)
        if plan is not None:
            return plan

        plan = compiler(sql)
        self._cache.put(key, plan)
        return plan

    def invalidate(self, sql: str) -> bool:
        """Invalidate a cached plan.

        Args:
            sql: The SQL statement.

        Returns:
            True if a plan was invalidated.
        """
        key = self._normalize_sql(sql)
        return self._cache.remove(key)

    def clear(self) -> None:
        """Clear the SQL plan cache."""
        self._cache.clear()

    def _normalize_sql(self, sql: str) -> str:
        """Normalize SQL for caching.

        Removes extra whitespace and normalizes case for keywords.

        Args:
            sql: The SQL statement.

        Returns:
            Normalized SQL string.
        """
        # Simple normalization - collapse whitespace
        normalized = " ".join(sql.split())
        return normalized

    @property
    def size(self) -> int:
        """Get the number of cached plans."""
        return self._cache.size

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._cache.stats


class PreparedStatementCache:
    """Cache for prepared statements.

    Stores prepared statements with their parameter types
    for efficient re-execution.

    Example:
        >>> cache = PreparedStatementCache()
        >>> stmt = cache.prepare("SELECT * FROM users WHERE id = ?", ["BIGINT"])
        >>> result = stmt.execute([123])
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        """Initialize the prepared statement cache.

        Args:
            config: Cache configuration.
        """
        self._config = config or CacheConfig(max_size=200)
        self._cache: LRUCache[str, PreparedStatement] = LRUCache(self._config)

    def prepare(
        self,
        sql: str,
        param_types: list[str] | None = None,
    ) -> PreparedStatement:
        """Prepare a SQL statement.

        Args:
            sql: The SQL statement with ? placeholders.
            param_types: Optional parameter type hints.

        Returns:
            A prepared statement.
        """
        cached = self._cache.get(sql)
        if cached is not None:
            return cached

        stmt = PreparedStatement(sql, param_types or [])
        self._cache.put(sql, stmt)
        return stmt

    def clear(self) -> None:
        """Clear all prepared statements."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Get the number of cached statements."""
        return self._cache.size


@dataclass
class PreparedStatement:
    """A prepared SQL statement.

    Attributes:
        sql: The SQL template with ? placeholders.
        param_types: The parameter types.
    """

    sql: str
    param_types: list[str] = field(default_factory=list)
    _compiled: Any | None = field(default=None, repr=False)

    def bind(self, params: list[Any]) -> str:
        """Bind parameters to create executable SQL.

        Args:
            params: Parameter values.

        Returns:
            SQL with bound parameters.
        """
        result = self.sql
        for param in params:
            if isinstance(param, str):
                value = f"'{param}'"
            elif param is None:
                value = "NULL"
            else:
                value = str(param)
            result = result.replace("?", value, 1)
        return result


class MetadataCache:
    """Cache for metadata (schemas, tables, indexes).

    Caches schema information to avoid repeated lookups.

    Example:
        >>> cache = MetadataCache()
        >>> table = cache.get_table("users")
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        """Initialize the metadata cache.

        Args:
            config: Cache configuration.
        """
        self._config = config or CacheConfig(max_size=100, ttl_seconds=300)
        self._schemas: LRUCache[str, Any] = LRUCache(self._config)
        self._tables: LRUCache[str, Any] = LRUCache(self._config)
        self._indexes: LRUCache[str, Any] = LRUCache(self._config)

    def get_schema(self, name: str) -> Any | None:
        """Get a cached schema."""
        return self._schemas.get(name)

    def put_schema(self, name: str, schema: Any) -> None:
        """Cache a schema."""
        self._schemas.put(name, schema)

    def get_table(self, name: str) -> Any | None:
        """Get a cached table definition."""
        return self._tables.get(name)

    def put_table(self, name: str, table: Any) -> None:
        """Cache a table definition."""
        self._tables.put(name, table)

    def get_index(self, name: str) -> Any | None:
        """Get a cached index definition."""
        return self._indexes.get(name)

    def put_index(self, name: str, index: Any) -> None:
        """Cache an index definition."""
        self._indexes.put(name, index)

    def invalidate_table(self, name: str) -> None:
        """Invalidate a table and its indexes."""
        self._tables.remove(name)
        # Also invalidate any indexes for this table
        with self._indexes._lock:
            keys_to_remove = [
                key for key in self._indexes._cache.keys() if key.startswith(f"{name}.")
            ]
            for key in keys_to_remove:
                del self._indexes._cache[key]

    def clear(self) -> None:
        """Clear all cached metadata."""
        self._schemas.clear()
        self._tables.clear()
        self._indexes.clear()

    @property
    def stats(self) -> dict[str, CacheStats]:
        """Get statistics for all caches."""
        return {
            "schemas": self._schemas.stats,
            "tables": self._tables.stats,
            "indexes": self._indexes.stats,
        }
