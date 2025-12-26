#!/usr/bin/env python3
"""Phase 7 Tests: Production Hardening.

Tests for batch operations, connection pooling, caching, and metrics.
"""

import asyncio
import os
import sys
import time
from typing import Any, List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_batch_operations() -> None:
    """Test batch processing utilities."""
    print("=" * 60)
    print(" Test 1: Batch Operations")
    print("=" * 60)

    from fdb_record_layer.utils.batch import (
        BatchConfig,
        BatchProcessor,
        BatchResult,
        Pipeline,
        WriteBuffer,
    )

    # Test BatchConfig
    config = BatchConfig(batch_size=10, max_concurrent_batches=3, retry_limit=2)
    assert config.batch_size == 10
    assert config.max_concurrent_batches == 3
    print("  [PASS] BatchConfig created successfully")

    # Test BatchResult
    result: BatchResult[int] = BatchResult()
    result.successful.extend([1, 2, 3])
    result.failed.append((4, "Test error"))
    assert result.total_processed == 4
    assert result.total_succeeded == 3
    assert result.total_failed == 1
    assert result.success_rate == 0.75
    print("  [PASS] BatchResult tracking works correctly")

    # Test BatchResult merge
    result2: BatchResult[int] = BatchResult()
    result2.successful.extend([5, 6])
    merged = result.merge(result2)
    assert merged.total_succeeded == 5
    print("  [PASS] BatchResult merge works")

    # Test BatchProcessor
    async def process_batch(items: List[int]) -> List[int]:
        return [i * 2 for i in items]

    async def run_processor() -> None:
        processor = BatchProcessor(process_batch, BatchConfig(batch_size=3))
        result = await processor.process([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        assert result.total_succeeded == 10
        assert 20 in result.successful

    asyncio.run(run_processor())
    print("  [PASS] BatchProcessor processes all items")

    # Test Pipeline
    async def double(x: Any) -> int:
        return x * 2

    async def add_one(x: Any) -> int:
        return x + 1

    async def run_pipeline() -> None:
        pipeline = Pipeline(max_in_flight=5)
        pipeline.add_stage("double", double)
        pipeline.add_stage("add_one", add_one)
        results = await pipeline.execute([1, 2, 3, 4, 5])
        assert results == [3, 5, 7, 9, 11]

    asyncio.run(run_pipeline())
    print("  [PASS] Pipeline executes stages in order")

    # Test WriteBuffer
    buffer = WriteBuffer()
    buffer.insert({"id": 1, "name": "test"})
    buffer.update({"id": 2}, {"name": "updated"})
    buffer.delete("users", (3,))
    assert buffer.insert_count == 1
    assert buffer.update_count == 1
    assert buffer.delete_count == 1
    assert buffer.total_count == 3
    assert not buffer.is_empty
    print("  [PASS] WriteBuffer accumulates operations")

    buffer.clear()
    assert buffer.is_empty
    print("  [PASS] WriteBuffer clear works")


def test_connection_pooling() -> None:
    """Test connection pool utilities."""
    print("\n" + "=" * 60)
    print(" Test 2: Connection Pooling")
    print("=" * 60)

    from fdb_record_layer.utils.pool import (
        ConnectionPool,
        PoolConfig,
        PooledConnection,
        MockDatabase,
        MockTransaction,
    )

    # Test PoolConfig
    config = PoolConfig(min_connections=2, max_connections=10, max_idle_time=300.0)
    assert config.min_connections == 2
    assert config.max_connections == 10
    print("  [PASS] PoolConfig created successfully")

    # Test PooledConnection
    conn = PooledConnection(connection="test_conn")
    assert conn.use_count == 0
    conn.mark_used()
    assert conn.use_count == 1
    assert conn.age >= 0
    assert conn.idle_time >= 0
    print("  [PASS] PooledConnection tracking works")

    # Test ConnectionPool
    async def run_pool_test() -> None:
        connection_counter = {"count": 0}

        def create_connection() -> str:
            connection_counter["count"] += 1
            return f"conn_{connection_counter['count']}"

        pool = ConnectionPool(
            factory=create_connection,
            config=PoolConfig(max_connections=3),
        )

        async with pool.acquire() as conn1:
            assert conn1.startswith("conn_")

            async with pool.acquire() as conn2:
                assert conn2.startswith("conn_")

        stats = pool.stats()
        assert stats["total_created"] >= 1
        assert stats["total_acquired"] >= 2
        print(f"  [PASS] Pool stats: created={stats['total_created']}, acquired={stats['total_acquired']}")

        await pool.close()
        assert pool.stats()["closed"]
        print("  [PASS] Pool closed successfully")

    asyncio.run(run_pool_test())

    # Test MockDatabase and MockTransaction
    db = MockDatabase()
    tr = db.create_transaction()
    tr[b"key1"] = b"value1"
    assert tr[b"key1"] == b"value1"
    tr.commit()

    tr2 = db.create_transaction()
    assert tr2[b"key1"] == b"value1"
    print("  [PASS] MockDatabase and MockTransaction work correctly")


def test_caching() -> None:
    """Test caching utilities."""
    print("\n" + "=" * 60)
    print(" Test 3: Caching")
    print("=" * 60)

    from fdb_record_layer.utils.cache import (
        CacheConfig,
        CacheEntry,
        LRUCache,
        QueryPlanCache,
        SQLPlanCache,
        PreparedStatementCache,
        MetadataCache,
    )

    # Test CacheConfig
    config = CacheConfig(max_size=100, ttl_seconds=60.0)
    assert config.max_size == 100
    assert config.ttl_seconds == 60.0
    print("  [PASS] CacheConfig created successfully")

    # Test CacheEntry
    entry: CacheEntry[str] = CacheEntry(value="test_value")
    assert entry.access_count == 0
    entry.touch()
    assert entry.access_count == 1
    assert entry.age >= 0
    assert not entry.is_expired(10.0)
    print("  [PASS] CacheEntry tracking works")

    # Test LRUCache
    cache: LRUCache[str, int] = LRUCache(CacheConfig(max_size=3))
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.size == 3
    print("  [PASS] LRUCache basic operations work")

    # Test LRU eviction
    cache.put("d", 4)
    assert cache.size == 3
    print("  [PASS] LRUCache eviction works")

    # Test cache stats
    stats = cache.stats
    assert stats.hits > 0
    print(f"  [INFO] Cache stats: hits={stats.hits}, misses={stats.misses}, hit_rate={stats.hit_rate:.2%}")

    # Test get_or_compute
    compute_calls = {"count": 0}

    def compute_value() -> int:
        compute_calls["count"] += 1
        return 42

    cache2: LRUCache[str, int] = LRUCache()
    val = cache2.get_or_compute("key", compute_value)
    assert val == 42
    assert compute_calls["count"] == 1

    val2 = cache2.get_or_compute("key", compute_value)
    assert val2 == 42
    assert compute_calls["count"] == 1
    print("  [PASS] LRUCache get_or_compute works")

    # Test QueryPlanCache
    plan_cache = QueryPlanCache()

    class MockQuery:
        def __init__(self, table: str):
            self.table = table

        def to_cache_key(self) -> str:
            return f"SELECT * FROM {self.table}"

    query = MockQuery("users")
    plan_cache.put(query, {"type": "scan", "table": "users"})

    cached_plan = plan_cache.get(query)
    assert cached_plan is not None
    assert cached_plan["table"] == "users"
    print("  [PASS] QueryPlanCache stores and retrieves plans")

    # Test SQLPlanCache
    sql_cache = SQLPlanCache()
    sql = "SELECT * FROM users WHERE id = ?"

    compile_calls = {"count": 0}

    def compile_sql(s: str) -> dict:
        compile_calls["count"] += 1
        return {"sql": s, "compiled": True}

    plan1 = sql_cache.get_or_compile(sql, compile_sql)
    assert plan1["compiled"]
    assert compile_calls["count"] == 1

    plan2 = sql_cache.get_or_compile(sql, compile_sql)
    assert compile_calls["count"] == 1
    print("  [PASS] SQLPlanCache caching works")

    # Test PreparedStatementCache
    stmt_cache = PreparedStatementCache()
    stmt = stmt_cache.prepare("SELECT * FROM users WHERE id = ?", ["BIGINT"])
    bound = stmt.bind([123])
    assert "123" in bound
    assert "?" not in bound
    print("  [PASS] PreparedStatementCache creates and binds statements")

    # Test MetadataCache
    meta_cache = MetadataCache()
    meta_cache.put_schema("mydb", {"name": "mydb", "version": 1})
    meta_cache.put_table("users", {"name": "users", "columns": ["id", "name"]})
    assert meta_cache.get_schema("mydb") is not None
    assert meta_cache.get_table("users") is not None
    print("  [PASS] MetadataCache stores and retrieves metadata")


def test_metrics() -> None:
    """Test metrics and observability utilities."""
    print("\n" + "=" * 60)
    print(" Test 4: Metrics and Observability")
    print("=" * 60)

    from fdb_record_layer.utils.metrics import (
        Counter,
        Gauge,
        Histogram,
        Timer,
        LabeledCounter,
        MetricsCollector,
        IndexUsageTracker,
        PlanExplainer,
        get_metrics,
        reset_metrics,
    )

    # Test Counter
    counter = Counter("test_counter")
    counter.inc()
    counter.inc(5)
    assert counter.value == 6
    print("  [PASS] Counter increments correctly")

    # Test LabeledCounter
    labeled = LabeledCounter("requests", ["method", "status"])
    labeled.labels(method="GET", status="200").inc()
    labeled.labels(method="POST", status="201").inc(3)
    values = labeled.collect()
    assert len(values) == 2
    print("  [PASS] LabeledCounter tracks by labels")

    # Test Gauge
    gauge = Gauge("temperature")
    gauge.set(25.0)
    assert gauge.value == 25.0
    gauge.inc(5.0)
    assert gauge.value == 30.0
    gauge.dec(10.0)
    assert gauge.value == 20.0
    print("  [PASS] Gauge set/inc/dec work correctly")

    # Test Histogram
    hist = Histogram("request_size", buckets=(10, 50, 100, 500, 1000))
    for size in [5, 25, 75, 200, 800]:
        hist.observe(size)
    assert hist.count == 5
    assert hist.sum == 1105
    assert hist.mean == 221.0
    print(f"  [PASS] Histogram: count={hist.count}, mean={hist.mean:.1f}")

    # Test Timer
    timer = Timer("operation_duration")
    with timer.time():
        time.sleep(0.01)
    assert timer.count == 1
    assert timer.sum > 0
    print(f"  [PASS] Timer recorded duration: {timer.sum:.4f}s")

    # Test MetricsCollector
    collector = MetricsCollector()
    collector.record_read("users", 0.001, 1024)
    collector.record_write("users", 0.002, 512)
    collector.record_query("select", 0.005, 10)

    summary = collector.get_summary()
    assert summary["counters"]["reads"] == 1
    assert summary["counters"]["writes"] == 1
    assert summary["counters"]["queries"] == 1
    print("  [PASS] MetricsCollector records operations")

    # Test timed_operation
    with collector.timed_operation("read", "products"):
        time.sleep(0.001)

    summary2 = collector.get_summary()
    assert summary2["counters"]["reads"] == 2
    print("  [PASS] MetricsCollector timed_operation works")

    # Test global metrics
    reset_metrics()
    metrics = get_metrics()
    metrics.record_read("test", 0.001)
    assert get_metrics().get_summary()["counters"]["reads"] == 1
    print("  [PASS] Global metrics collector works")

    # Test IndexUsageTracker
    tracker = IndexUsageTracker()
    tracker.record_scan("users_email_idx", 100)
    tracker.record_scan("users_email_idx", 50)
    tracker.record_scan("products_name_idx", 200, is_full_scan=True)

    usage = tracker.get_usage("users_email_idx")
    assert usage["scans"] == 2
    assert usage["rows_scanned"] == 150
    print(f"  [PASS] IndexUsageTracker: scans={usage['scans']}, rows={usage['rows_scanned']}")

    all_usage = tracker.get_all_usage()
    assert len(all_usage) == 2
    print("  [PASS] IndexUsageTracker tracks all indexes")

    # Test PlanExplainer
    class MockPlan:
        def __init__(self, index_name: str):
            self.index_name = index_name
            self.estimated_cost = 10.5

    explainer = PlanExplainer()
    plan = MockPlan("users_pk")
    explanation = explainer.explain(plan)
    assert explanation.plan_type == "MockPlan"
    assert explanation.estimated_cost == 10.5
    assert len(explanation.steps) > 0
    print(f"  [PASS] PlanExplainer: {explanation.plan_type}, cost={explanation.estimated_cost}")


def test_integration() -> None:
    """Integration test combining multiple utilities."""
    print("\n" + "=" * 60)
    print(" Test 5: Integration Test")
    print("=" * 60)

    from fdb_record_layer.utils.batch import BatchProcessor, BatchConfig
    from fdb_record_layer.utils.cache import LRUCache, CacheConfig
    from fdb_record_layer.utils.metrics import MetricsCollector

    collector = MetricsCollector()
    cache: LRUCache[str, dict] = LRUCache(CacheConfig(max_size=100))

    async def fetch_user(user_id: int) -> dict:
        cache_key = f"user_{user_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        with collector.timed_operation("read", "users"):
            await asyncio.sleep(0.001)
            user = {"id": user_id, "name": f"User {user_id}"}

        cache.put(cache_key, user)
        return user

    async def process_users(user_ids: List[int]) -> List[dict]:
        return [await fetch_user(uid) for uid in user_ids]

    async def run_integration() -> None:
        processor = BatchProcessor(process_users, BatchConfig(batch_size=10))

        # First batch - all cache misses
        result1 = await processor.process(list(range(1, 21)))
        assert result1.total_succeeded == 20
        print(f"  [PASS] Processed {result1.total_succeeded} users (first batch)")

        summary = collector.get_summary()
        print(f"  [INFO] Reads: {summary['counters']['reads']}")

        # Second batch with same IDs - should hit cache
        cache_stats_before = cache.stats.hits
        result2 = await processor.process(list(range(1, 11)))
        cache_stats_after = cache.stats.hits

        assert cache_stats_after > cache_stats_before
        print(f"  [PASS] Cache hits increased: {cache_stats_before} -> {cache_stats_after}")

        hit_rate = cache.stats.hit_rate
        print(f"  [INFO] Cache hit rate: {hit_rate:.2%}")

    asyncio.run(run_integration())
    print("  [PASS] Integration test completed successfully")


def main() -> None:
    """Run all Phase 7 tests."""
    print("\n" + "=" * 60)
    print(" Phase 7: Production Hardening - Test Suite")
    print("=" * 60)

    tests = [
        ("Batch Operations", test_batch_operations),
        ("Connection Pooling", test_connection_pooling),
        ("Caching", test_caching),
        ("Metrics and Observability", test_metrics),
        ("Integration", test_integration),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"\n  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f" Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
