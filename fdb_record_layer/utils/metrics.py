"""Metrics and observability for FDB Record Layer.

Provides comprehensive metrics collection, logging, and monitoring
for database operations.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
)

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class MetricValue:
    """A metric value with timestamp."""

    value: float
    timestamp: float = field(default_factory=time.time)
    labels: dict[str, str] = field(default_factory=dict)


class Counter:
    """A monotonically increasing counter.

    Example:
        >>> counter = Counter("requests_total")
        >>> counter.inc()
        >>> counter.inc(5)
    """

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._value = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        """Increment the counter."""
        if amount < 0:
            raise ValueError("Counter can only be incremented")
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        """Get the current value."""
        return self._value

    def reset(self) -> None:
        """Reset the counter to zero."""
        with self._lock:
            self._value = 0.0


class LabeledCounter:
    """A counter with labels.

    Example:
        >>> counter = LabeledCounter("http_requests", ["method", "status"])
        >>> counter.labels(method="GET", status="200").inc()
    """

    def __init__(self, name: str, label_names: list[str], description: str = "") -> None:
        self.name = name
        self.label_names = label_names
        self.description = description
        self._counters: dict[tuple[str, ...], Counter] = {}
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> Counter:
        """Get a counter for specific label values."""
        key = tuple(kwargs.get(name, "") for name in self.label_names)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = Counter(self.name)
            return self._counters[key]

    def collect(self) -> list[tuple[dict[str, str], float]]:
        """Collect all counter values with labels."""
        result = []
        with self._lock:
            for key, counter in self._counters.items():
                labels = dict(zip(self.label_names, key))
                result.append((labels, counter.value))
        return result


class Gauge:
    """A metric that can go up and down.

    Example:
        >>> gauge = Gauge("temperature")
        >>> gauge.set(25.5)
        >>> gauge.inc(0.5)
        >>> gauge.dec(1.0)
    """

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        """Set the gauge value."""
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        """Increment the gauge."""
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        """Decrement the gauge."""
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        """Get the current value."""
        return self._value


class Histogram:
    """A histogram for measuring value distributions.

    Example:
        >>> hist = Histogram("request_size", buckets=[100, 500, 1000, 5000])
        >>> hist.observe(250)
    """

    DEFAULT_BUCKETS = (
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
        float("inf"),
    )

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: tuple[float, ...] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._bucket_counts: dict[float, int] = {b: 0 for b in self.buckets}
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """Record an observation."""
        with self._lock:
            self._sum += value
            self._count += 1
            for bucket in self.buckets:
                if value <= bucket:
                    self._bucket_counts[bucket] += 1

    @property
    def sum(self) -> float:
        """Get the sum of all observations."""
        return self._sum

    @property
    def count(self) -> int:
        """Get the count of observations."""
        return self._count

    @property
    def mean(self) -> float:
        """Get the mean of observations."""
        if self._count == 0:
            return 0.0
        return self._sum / self._count

    def get_buckets(self) -> dict[float, int]:
        """Get bucket counts."""
        with self._lock:
            return dict(self._bucket_counts)


class Timer:
    """A timer for measuring durations.

    Example:
        >>> timer = Timer("request_duration")
        >>> with timer.time():
        ...     process_request()
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: tuple[float, ...] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self._histogram = Histogram(name, description, buckets)

    @contextmanager
    def time(self) -> Iterator[None]:
        """Context manager for timing operations."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self._histogram.observe(duration)

    def observe(self, duration: float) -> None:
        """Record a duration directly."""
        self._histogram.observe(duration)

    @property
    def count(self) -> int:
        """Get the number of recorded durations."""
        return self._histogram.count

    @property
    def sum(self) -> float:
        """Get the total duration."""
        return self._histogram.sum

    @property
    def mean(self) -> float:
        """Get the mean duration."""
        return self._histogram.mean


@dataclass
class OperationMetrics:
    """Metrics for a specific operation type.

    Attributes:
        operation: The operation name.
        count: Number of operations.
        total_time: Total time spent.
        min_time: Minimum operation time.
        max_time: Maximum operation time.
        errors: Number of errors.
    """

    operation: str
    count: int = 0
    total_time: float = 0.0
    min_time: float = float("inf")
    max_time: float = 0.0
    errors: int = 0

    @property
    def avg_time(self) -> float:
        """Get the average operation time."""
        if self.count == 0:
            return 0.0
        return self.total_time / self.count

    def record(self, duration: float, error: bool = False) -> None:
        """Record an operation."""
        self.count += 1
        self.total_time += duration
        self.min_time = min(self.min_time, duration)
        self.max_time = max(self.max_time, duration)
        if error:
            self.errors += 1


class MetricsCollector:
    """Central collector for all metrics.

    Example:
        >>> collector = MetricsCollector()
        >>> collector.record_read("users", 0.001)
        >>> collector.record_write("users", 0.002)
        >>> print(collector.get_summary())
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Core metrics
        self._reads = Counter("fdb_reads_total", "Total read operations")
        self._writes = Counter("fdb_writes_total", "Total write operations")
        self._deletes = Counter("fdb_deletes_total", "Total delete operations")
        self._queries = Counter("fdb_queries_total", "Total query executions")
        self._errors = LabeledCounter(
            "fdb_errors_total", ["operation", "error_type"], "Total errors by type"
        )

        # Latency histograms
        self._read_latency = Histogram(
            "fdb_read_latency_seconds",
            "Read operation latency",
        )
        self._write_latency = Histogram(
            "fdb_write_latency_seconds",
            "Write operation latency",
        )
        self._query_latency = Histogram(
            "fdb_query_latency_seconds",
            "Query execution latency",
        )

        # Gauges
        self._active_transactions = Gauge(
            "fdb_active_transactions", "Number of active transactions"
        )
        self._cache_size = Gauge("fdb_cache_size", "Number of items in cache")

        # Per-operation metrics
        self._operations: dict[str, OperationMetrics] = {}

        # Query metrics by table
        self._table_reads: dict[str, int] = defaultdict(int)
        self._table_writes: dict[str, int] = defaultdict(int)

    def record_read(
        self,
        record_type: str,
        duration: float,
        bytes_read: int = 0,
    ) -> None:
        """Record a read operation."""
        self._reads.inc()
        self._read_latency.observe(duration)
        self._table_reads[record_type] += 1

        with self._lock:
            if "read" not in self._operations:
                self._operations["read"] = OperationMetrics("read")
            self._operations["read"].record(duration)

    def record_write(
        self,
        record_type: str,
        duration: float,
        bytes_written: int = 0,
    ) -> None:
        """Record a write operation."""
        self._writes.inc()
        self._write_latency.observe(duration)
        self._table_writes[record_type] += 1

        with self._lock:
            if "write" not in self._operations:
                self._operations["write"] = OperationMetrics("write")
            self._operations["write"].record(duration)

    def record_delete(
        self,
        record_type: str,
        duration: float,
    ) -> None:
        """Record a delete operation."""
        self._deletes.inc()

        with self._lock:
            if "delete" not in self._operations:
                self._operations["delete"] = OperationMetrics("delete")
            self._operations["delete"].record(duration)

    def record_query(
        self,
        query_type: str,
        duration: float,
        rows_returned: int = 0,
    ) -> None:
        """Record a query execution."""
        self._queries.inc()
        self._query_latency.observe(duration)

        with self._lock:
            key = f"query_{query_type}"
            if key not in self._operations:
                self._operations[key] = OperationMetrics(key)
            self._operations[key].record(duration)

    def record_error(
        self,
        operation: str,
        error_type: str,
    ) -> None:
        """Record an error."""
        self._errors.labels(operation=operation, error_type=error_type).inc()

        with self._lock:
            if operation in self._operations:
                self._operations[operation].errors += 1

    def set_active_transactions(self, count: int) -> None:
        """Set the number of active transactions."""
        self._active_transactions.set(count)

    def set_cache_size(self, size: int) -> None:
        """Set the cache size metric."""
        self._cache_size.set(size)

    @contextmanager
    def timed_operation(
        self,
        operation: str,
        record_type: str | None = None,
    ) -> Iterator[None]:
        """Context manager for timing operations.

        Example:
            >>> with collector.timed_operation("read", "users"):
            ...     load_record()
        """
        start = time.perf_counter()
        error = False
        try:
            yield
        except Exception as e:
            error = True
            self.record_error(operation, type(e).__name__)
            raise
        finally:
            duration = time.perf_counter() - start
            if operation == "read":
                self.record_read(record_type or "unknown", duration)
            elif operation == "write":
                self.record_write(record_type or "unknown", duration)
            elif operation == "delete":
                self.record_delete(record_type or "unknown", duration)
            elif operation == "query":
                self.record_query("select", duration)
            else:
                with self._lock:
                    if operation not in self._operations:
                        self._operations[operation] = OperationMetrics(operation)
                    self._operations[operation].record(duration, error)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all metrics."""
        return {
            "counters": {
                "reads": self._reads.value,
                "writes": self._writes.value,
                "deletes": self._deletes.value,
                "queries": self._queries.value,
            },
            "latency": {
                "read_mean": self._read_latency.mean,
                "write_mean": self._write_latency.mean,
                "query_mean": self._query_latency.mean,
            },
            "gauges": {
                "active_transactions": self._active_transactions.value,
                "cache_size": self._cache_size.value,
            },
            "operations": {
                name: {
                    "count": op.count,
                    "avg_time": op.avg_time,
                    "min_time": op.min_time if op.min_time != float("inf") else 0,
                    "max_time": op.max_time,
                    "errors": op.errors,
                }
                for name, op in self._operations.items()
            },
            "tables": {
                "reads": dict(self._table_reads),
                "writes": dict(self._table_writes),
            },
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._reads.reset()
        self._writes.reset()
        self._deletes.reset()
        self._queries.reset()
        self._operations.clear()
        self._table_reads.clear()
        self._table_writes.clear()


# Global metrics collector
_global_collector: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Get the global metrics collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def reset_metrics() -> None:
    """Reset the global metrics collector."""
    global _global_collector
    if _global_collector is not None:
        _global_collector.reset()


class QueryLogger:
    """Logs query execution details.

    Example:
        >>> logger = QueryLogger()
        >>> with logger.log_query("SELECT * FROM users"):
        ...     execute_query()
    """

    def __init__(
        self,
        log_level: int = logging.DEBUG,
        slow_query_threshold: float = 1.0,
    ) -> None:
        """Initialize the query logger.

        Args:
            log_level: Default logging level.
            slow_query_threshold: Threshold for slow query warnings (seconds).
        """
        self._log_level = log_level
        self._slow_threshold = slow_query_threshold
        self._logger = logging.getLogger("fdb.query")

    @contextmanager
    def log_query(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> Iterator[QueryLogContext]:
        """Log a query execution.

        Args:
            query: The query string.
            params: Query parameters.

        Yields:
            A context for adding result information.
        """
        context = QueryLogContext(query, params)
        self._logger.log(self._log_level, f"Executing: {query[:200]}")

        start = time.perf_counter()
        try:
            yield context
        except Exception as e:
            context.error = str(e)
            self._logger.error(f"Query failed: {e}")
            raise
        finally:
            duration = time.perf_counter() - start
            context.duration = duration

            if duration > self._slow_threshold:
                self._logger.warning(f"Slow query ({duration:.3f}s): {query[:100]}")
            else:
                self._logger.log(
                    self._log_level,
                    f"Query completed in {duration:.3f}s, rows={context.rows_affected}",
                )


@dataclass
class QueryLogContext:
    """Context for logging query results."""

    query: str
    params: list[Any] | None = None
    duration: float = 0.0
    rows_affected: int = 0
    error: str | None = None


class IndexUsageTracker:
    """Tracks index usage statistics.

    Example:
        >>> tracker = IndexUsageTracker()
        >>> tracker.record_scan("users_email_idx", 100)
        >>> print(tracker.get_usage("users_email_idx"))
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()  # Use RLock to allow reentrant locking
        self._scans: dict[str, int] = defaultdict(int)
        self._rows_scanned: dict[str, int] = defaultdict(int)
        self._full_scans: dict[str, int] = defaultdict(int)

    def record_scan(
        self,
        index_name: str,
        rows_scanned: int,
        is_full_scan: bool = False,
    ) -> None:
        """Record an index scan."""
        with self._lock:
            self._scans[index_name] += 1
            self._rows_scanned[index_name] += rows_scanned
            if is_full_scan:
                self._full_scans[index_name] += 1

    def get_usage(self, index_name: str) -> dict[str, Any]:
        """Get usage statistics for an index."""
        with self._lock:
            return {
                "scans": self._scans.get(index_name, 0),
                "rows_scanned": self._rows_scanned.get(index_name, 0),
                "full_scans": self._full_scans.get(index_name, 0),
            }

    def get_all_usage(self) -> dict[str, dict[str, Any]]:
        """Get usage statistics for all indexes."""
        with self._lock:
            all_indexes = set(self._scans.keys())
            return {idx: self.get_usage(idx) for idx in all_indexes}

    def get_unused_indexes(self) -> list[str]:
        """Get indexes that have never been scanned."""
        # This would need to be integrated with schema information
        return []

    def reset(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self._scans.clear()
            self._rows_scanned.clear()
            self._full_scans.clear()


class PlanExplainer:
    """Explains query execution plans.

    Example:
        >>> explainer = PlanExplainer()
        >>> explanation = explainer.explain(plan)
        >>> print(explanation.to_string())
    """

    def explain(self, plan: Any) -> PlanExplanation:
        """Generate an explanation for a query plan.

        Args:
            plan: The query plan to explain.

        Returns:
            An explanation object.
        """
        steps: list[str] = []
        costs: list[float] = []

        self._traverse_plan(plan, steps, costs, depth=0)

        return PlanExplanation(
            plan_type=type(plan).__name__,
            steps=steps,
            estimated_cost=sum(costs) if costs else 0.0,
        )

    def _traverse_plan(
        self,
        plan: Any,
        steps: list[str],
        costs: list[float],
        depth: int,
    ) -> None:
        """Recursively traverse a plan."""
        indent = "  " * depth
        plan_type = type(plan).__name__

        # Get plan-specific info
        if hasattr(plan, "index_name"):
            steps.append(f"{indent}Index Scan: {plan.index_name}")
        elif hasattr(plan, "record_types"):
            steps.append(f"{indent}Table Scan: {plan.record_types}")
        else:
            steps.append(f"{indent}{plan_type}")

        # Get cost if available
        if hasattr(plan, "estimated_cost"):
            costs.append(plan.estimated_cost)

        # Traverse children
        if hasattr(plan, "children"):
            for child in plan.children:
                self._traverse_plan(child, steps, costs, depth + 1)
        elif hasattr(plan, "inner_plan"):
            self._traverse_plan(plan.inner_plan, steps, costs, depth + 1)


@dataclass
class PlanExplanation:
    """An explanation of a query plan."""

    plan_type: str
    steps: list[str]
    estimated_cost: float

    def to_string(self) -> str:
        """Convert to a readable string."""
        lines = [f"Plan: {self.plan_type}"]
        lines.append(f"Estimated Cost: {self.estimated_cost:.2f}")
        lines.append("Steps:")
        lines.extend(self.steps)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary."""
        return {
            "plan_type": self.plan_type,
            "steps": self.steps,
            "estimated_cost": self.estimated_cost,
        }
