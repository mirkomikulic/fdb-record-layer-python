"""Health check utilities for FDB Record Layer.

Provides health check endpoints for monitoring system health,
liveness, and readiness probes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb_record_layer.core.context import FDBDatabase
    from fdb_record_layer.utils.pool import ConnectionPool

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    name: str
    status: HealthStatus
    message: str | None = None
    latency_ms: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    last_check: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "last_check": self.last_check,
        }


@dataclass
class HealthReport:
    """Overall health report."""

    status: HealthStatus
    components: list[ComponentHealth] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    version: str | None = None

    @property
    def is_healthy(self) -> bool:
        """Check if overall status is healthy."""
        return self.status == HealthStatus.HEALTHY

    @property
    def is_alive(self) -> bool:
        """Check if system is alive (not completely unhealthy)."""
        return self.status != HealthStatus.UNHEALTHY

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "is_healthy": self.is_healthy,
            "is_alive": self.is_alive,
            "timestamp": self.timestamp,
            "version": self.version,
            "components": [c.to_dict() for c in self.components],
        }


class HealthChecker:
    """Health checker for FDB Record Layer components.

    Provides health check functionality for:
    - FDB database connectivity
    - Connection pool status
    - Metadata store accessibility
    - Custom health checks

    Example:
        >>> checker = HealthChecker()
        >>> checker.register_database(db)
        >>> checker.register_pool(pool)
        >>> report = await checker.check_health()
        >>> if report.is_healthy:
        ...     print("All systems operational")
    """

    def __init__(
        self,
        timeout_seconds: float = 5.0,
        version: str | None = None,
    ) -> None:
        """Initialize the health checker.

        Args:
            timeout_seconds: Timeout for health checks.
            version: Application version to include in reports.
        """
        self._timeout = timeout_seconds
        self._version = version
        self._databases: list[tuple[str, FDBDatabase]] = []
        self._pools: list[tuple[str, ConnectionPool]] = []
        self._custom_checks: list[tuple[str, Callable[[], bool]]] = []
        self._async_checks: list[tuple[str, Callable[[], Any]]] = []

    def register_database(self, database: FDBDatabase, name: str = "fdb") -> None:
        """Register a database for health checking.

        Args:
            database: The FDB database to check.
            name: Name for this component in health reports.
        """
        self._databases.append((name, database))

    def register_pool(self, pool: ConnectionPool, name: str = "connection_pool") -> None:
        """Register a connection pool for health checking.

        Args:
            pool: The connection pool to check.
            name: Name for this component in health reports.
        """
        self._pools.append((name, pool))

    def register_check(self, name: str, check_fn: Callable[[], bool]) -> None:
        """Register a custom synchronous health check.

        Args:
            name: Name for this component.
            check_fn: Function that returns True if healthy.
        """
        self._custom_checks.append((name, check_fn))

    def register_async_check(self, name: str, check_fn: Callable[[], Any]) -> None:
        """Register a custom async health check.

        Args:
            name: Name for this component.
            check_fn: Async function that returns True if healthy.
        """
        self._async_checks.append((name, check_fn))

    async def check_health(self) -> HealthReport:
        """Perform all health checks and return a report.

        Returns:
            HealthReport with overall and component status.
        """
        components: list[ComponentHealth] = []

        # Check databases
        for name, db in self._databases:
            component = await self._check_database(name, db)
            components.append(component)

        # Check pools
        for name, pool in self._pools:
            component = self._check_pool(name, pool)
            components.append(component)

        # Run custom sync checks
        for name, check_fn in self._custom_checks:
            component = self._run_sync_check(name, check_fn)
            components.append(component)

        # Run custom async checks
        for name, check_fn in self._async_checks:
            component = await self._run_async_check(name, check_fn)
            components.append(component)

        # Determine overall status
        overall_status = self._compute_overall_status(components)

        return HealthReport(
            status=overall_status,
            components=components,
            version=self._version,
        )

    async def check_liveness(self) -> bool:
        """Quick liveness check - is the system running?

        Returns:
            True if the system is alive.
        """
        # For liveness, we just check if we can respond
        return True

    async def check_readiness(self) -> bool:
        """Readiness check - is the system ready to accept traffic?

        Returns:
            True if the system is ready.
        """
        report = await self.check_health()
        return report.is_alive

    async def _check_database(self, name: str, database: FDBDatabase) -> ComponentHealth:
        """Check FDB database connectivity."""
        start_time = time.time()

        try:
            # Try to perform a simple read operation
            async def test_connection(ctx: Any) -> bool:
                # Just accessing transaction verifies connection
                _ = ctx.transaction
                return True

            # Run with timeout
            _ = await asyncio.wait_for(
                database.run(test_connection),
                timeout=self._timeout,
            )

            latency_ms = (time.time() - start_time) * 1000

            return ComponentHealth(
                name=name,
                status=HealthStatus.HEALTHY,
                message="Connected to FoundationDB",
                latency_ms=latency_ms,
                last_check=time.time(),
            )

        except asyncio.TimeoutError:
            logger.warning(f"Health check timeout for {name}")
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Connection timeout after {self._timeout}s",
                last_check=time.time(),
            )

        except Exception as e:
            logger.error(f"Health check failed for {name}: {e}")
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Connection error: {str(e)}",
                last_check=time.time(),
            )

    def _check_pool(self, name: str, pool: ConnectionPool) -> ComponentHealth:
        """Check connection pool status."""
        try:
            stats = pool.stats()

            # Determine status based on pool state
            if stats.get("closed", False):
                status = HealthStatus.UNHEALTHY
                message = "Pool is closed"
            elif stats.get("available", 0) == 0 and stats.get("in_use", 0) >= stats.get("size", 0):
                status = HealthStatus.DEGRADED
                message = "Pool exhausted - no available connections"
            else:
                status = HealthStatus.HEALTHY
                avail = stats.get("available", 0)
                in_use = stats.get("in_use", 0)
                message = f"Pool healthy: {avail} available, {in_use} in use"

            return ComponentHealth(
                name=name,
                status=status,
                message=message,
                details=stats,
                last_check=time.time(),
            )

        except Exception as e:
            logger.error(f"Pool health check failed for {name}: {e}")
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNKNOWN,
                message=f"Failed to check pool: {str(e)}",
                last_check=time.time(),
            )

    def _run_sync_check(self, name: str, check_fn: Callable[[], bool]) -> ComponentHealth:
        """Run a synchronous health check."""
        start_time = time.time()

        try:
            result = check_fn()
            latency_ms = (time.time() - start_time) * 1000

            return ComponentHealth(
                name=name,
                status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                message="Check passed" if result else "Check failed",
                latency_ms=latency_ms,
                last_check=time.time(),
            )

        except Exception as e:
            logger.error(f"Health check failed for {name}: {e}")
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check error: {str(e)}",
                last_check=time.time(),
            )

    async def _run_async_check(self, name: str, check_fn: Callable[[], Any]) -> ComponentHealth:
        """Run an async health check."""
        start_time = time.time()

        try:
            result = await asyncio.wait_for(
                check_fn(),
                timeout=self._timeout,
            )
            latency_ms = (time.time() - start_time) * 1000

            return ComponentHealth(
                name=name,
                status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                message="Check passed" if result else "Check failed",
                latency_ms=latency_ms,
                last_check=time.time(),
            )

        except asyncio.TimeoutError:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check timeout after {self._timeout}s",
                last_check=time.time(),
            )

        except Exception as e:
            logger.error(f"Health check failed for {name}: {e}")
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check error: {str(e)}",
                last_check=time.time(),
            )

    def _compute_overall_status(self, components: list[ComponentHealth]) -> HealthStatus:
        """Compute overall health status from component statuses."""
        if not components:
            return HealthStatus.UNKNOWN

        statuses = [c.status for c in components]

        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNKNOWN


# Global health checker instance
_global_health_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """Get or create the global health checker."""
    global _global_health_checker
    if _global_health_checker is None:
        from fdb_record_layer import __version__

        _global_health_checker = HealthChecker(version=__version__)
    return _global_health_checker


def reset_health_checker() -> None:
    """Reset the global health checker."""
    global _global_health_checker
    _global_health_checker = None
