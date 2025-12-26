"""Utilities for FDB Record Layer.

Provides helper classes and functions for batch operations,
connection pooling, caching, metrics collection, health checks,
and lifecycle management.
"""

from .batch import (
    BatchConfig,
    BatchProcessor,
    BatchReader,
    BatchResult,
    BatchWriter,
    Pipeline,
    WriteBuffer,
)
from .cache import (
    CacheConfig,
    CacheEntry,
    CacheStats,
    LRUCache,
    MetadataCache,
    PreparedStatement,
    PreparedStatementCache,
    QueryPlanCache,
    SQLPlanCache,
)
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitBreakerStats,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    get_circuit_breaker_registry,
    reset_circuit_breakers,
)
from .health import (
    ComponentHealth,
    HealthChecker,
    HealthReport,
    HealthStatus,
    get_health_checker,
    reset_health_checker,
)
from .lifecycle import (
    InFlightContext,
    LifecycleManager,
    LifecycleState,
    ShutdownConfig,
    get_lifecycle,
    init_lifecycle,
    reset_lifecycle,
    shutdown,
)
from .logging import (
    LogContext,
    StructuredFormatter,
    configure_logging,
    get_logger,
    log_operation,
    log_timing,
)
from .metrics import (
    Counter,
    Gauge,
    Histogram,
    IndexUsageTracker,
    LabeledCounter,
    MetricsCollector,
    OperationMetrics,
    PlanExplainer,
    PlanExplanation,
    QueryLogContext,
    QueryLogger,
    Timer,
    get_metrics,
    reset_metrics,
)
from .pool import (
    ConnectionPool,
    ContextPool,
    DatabasePool,
    PoolConfig,
    PooledConnection,
)

__all__ = [
    # Batch operations
    "BatchConfig",
    "BatchProcessor",
    "BatchReader",
    "BatchResult",
    "BatchWriter",
    "Pipeline",
    "WriteBuffer",
    # Caching
    "CacheConfig",
    "CacheEntry",
    "CacheStats",
    "LRUCache",
    "MetadataCache",
    "PreparedStatement",
    "PreparedStatementCache",
    "QueryPlanCache",
    "SQLPlanCache",
    # Health checks
    "ComponentHealth",
    "HealthChecker",
    "HealthReport",
    "HealthStatus",
    "get_health_checker",
    "reset_health_checker",
    # Lifecycle management
    "InFlightContext",
    "LifecycleManager",
    "LifecycleState",
    "ShutdownConfig",
    "get_lifecycle",
    "init_lifecycle",
    "reset_lifecycle",
    "shutdown",
    # Metrics
    "Counter",
    "Gauge",
    "Histogram",
    "IndexUsageTracker",
    "LabeledCounter",
    "MetricsCollector",
    "OperationMetrics",
    "PlanExplainer",
    "PlanExplanation",
    "QueryLogContext",
    "QueryLogger",
    "Timer",
    "get_metrics",
    "reset_metrics",
    # Pooling
    "ConnectionPool",
    "ContextPool",
    "DatabasePool",
    "PoolConfig",
    "PooledConnection",
    # Logging
    "LogContext",
    "StructuredFormatter",
    "configure_logging",
    "get_logger",
    "log_operation",
    "log_timing",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitBreakerStats",
    "CircuitOpenError",
    "CircuitState",
    "get_circuit_breaker",
    "get_circuit_breaker_registry",
    "reset_circuit_breakers",
]
