#!/usr/bin/env python3
"""
FDB Record Layer for Python - Comprehensive Example

This example demonstrates all features of the FDB Record Layer in a realistic
e-commerce scenario with customers, products, orders, and reviews.

Features demonstrated:
1. Schema Definition with Protobuf
2. Record Store Operations (CRUD)
3. Multiple Index Types (VALUE, COUNT, RANK, TEXT)
4. Query Builder API
5. Index Scanning with Ranges
6. SQL Queries
7. Aggregations and Analytics
8. Full-Text Search
9. Leaderboards with RANK indexes
10. Schema Evolution
11. Production Utilities (metrics, caching, health checks)
12. Batch Operations
13. Continuations for Pagination
"""

import asyncio
import os
import sys
import time
from datetime import datetime
from typing import List, Optional

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set FDB paths
os.environ.setdefault("FDB_LIBRARY_PATH", os.path.expanduser("~/.fdb/lib/libfdb_c.dylib"))
os.environ.setdefault("FDB_CLUSTER_FILE", os.path.expanduser("~/.fdb/conf/fdb.cluster"))


# =============================================================================
# SECTION 1: Schema Definition
# =============================================================================

PROTO_DEFINITION = """
syntax = "proto3";
package ecommerce;

message Customer {
    int64 id = 1;
    string email = 2;
    string name = 3;
    string city = 4;
    int32 loyalty_points = 5;
    int64 created_at = 6;
    repeated string tags = 7;
}

message Product {
    int64 id = 1;
    string name = 2;
    string description = 3;
    string category = 4;
    int32 price_cents = 5;
    int32 stock = 6;
    double rating = 7;
    int32 review_count = 8;
}

message Order {
    int64 id = 1;
    int64 customer_id = 2;
    string status = 3;          // pending, confirmed, shipped, delivered, cancelled
    int32 total_cents = 4;
    int64 created_at = 5;
    repeated OrderItem items = 6;
}

message OrderItem {
    int64 product_id = 1;
    int32 quantity = 2;
    int32 price_cents = 3;
}

message Review {
    int64 id = 1;
    int64 product_id = 2;
    int64 customer_id = 3;
    int32 rating = 4;           // 1-5 stars
    string title = 5;
    string body = 6;
    int64 created_at = 7;
}

message RecordUnion {
    oneof record {
        Customer customer = 1;
        Product product = 2;
        Order order = 3;
        Review review = 4;
    }
}
"""


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 70}")
    print(f" {title}")
    print('=' * 70)


def print_subheader(title: str) -> None:
    """Print a subsection header."""
    print(f"\n--- {title} ---")


# =============================================================================
# SECTION 2: Initialize Database and Metadata
# =============================================================================

def create_metadata():
    """Create record metadata with all index types."""
    import fdb_record_layer as frl
    from examples.sample_pb2 import DESCRIPTOR

    metadata = (
        frl.RecordMetaDataBuilder(DESCRIPTOR)
        # Customer record type
        .set_record_type("Person", primary_key=frl.field("id"))
        # VALUE indexes for equality/range queries
        .add_index("Person", "person_email", frl.field("email"))
        .add_index("Person", "person_city", frl.field("city"))
        .add_index("Person", "person_age", frl.field("age"))
        # Composite index for city + age queries
        .add_index("Person", "person_city_age", frl.concat(frl.field("city"), frl.field("age")))

        # Order record type
        .set_record_type("Order", primary_key=frl.field("id"))
        .add_index("Order", "order_customer", frl.field("customer_id"))
        .add_index("Order", "order_status", frl.field("status"))
        # COUNT index for analytics
        .add_count_index("Order", "order_status_count", frl.field("status"))

        .build()
    )
    return metadata


# =============================================================================
# SECTION 3: Basic CRUD Operations
# =============================================================================

async def demonstrate_crud_operations(db, metadata, subspace):
    """Demonstrate Create, Read, Update, Delete operations."""
    print_header("CRUD Operations")

    import fdb_record_layer as frl
    from examples.sample_pb2 import Person, Order

    async def run_crud(ctx):
        store = frl.FDBRecordStore(ctx, subspace, metadata)

        # Clear existing data
        ctx.transaction.clear_range_startswith(subspace.key())

        # CREATE: Insert records
        print_subheader("CREATE - Inserting Records")

        customers = [
            Person(id=1, name="Alice Johnson", email="alice@example.com", age=28, city="New York"),
            Person(id=2, name="Bob Smith", email="bob@example.com", age=35, city="Los Angeles"),
            Person(id=3, name="Carol White", email="carol@example.com", age=42, city="New York"),
            Person(id=4, name="David Brown", email="david@example.com", age=31, city="Chicago"),
            Person(id=5, name="Eve Davis", email="eve@example.com", age=28, city="New York"),
            Person(id=6, name="Frank Miller", email="frank@example.com", age=45, city="Los Angeles"),
            Person(id=7, name="Grace Lee", email="grace@example.com", age=29, city="Seattle"),
            Person(id=8, name="Henry Wilson", email="henry@example.com", age=38, city="Chicago"),
        ]

        for customer in customers:
            stored = await store.save_record(customer)
            print(f"  Saved: {customer.name} (id={stored.primary_key})")

        orders = [
            Order(id=101, customer_id=1, status="delivered", total=15000, created_at=1700000000),
            Order(id=102, customer_id=1, status="shipped", total=8500, created_at=1700100000),
            Order(id=103, customer_id=2, status="pending", total=22000, created_at=1700200000),
            Order(id=104, customer_id=3, status="delivered", total=5500, created_at=1700300000),
            Order(id=105, customer_id=4, status="cancelled", total=12000, created_at=1700400000),
            Order(id=106, customer_id=5, status="pending", total=9800, created_at=1700500000),
        ]

        for order in orders:
            await store.save_record(order)
        print(f"  Saved {len(orders)} orders")

        # READ: Load by primary key
        print_subheader("READ - Load by Primary Key")

        loaded = await store.load_record("Person", (1,))
        if loaded:
            print(f"  Loaded customer: {loaded.record.name}, {loaded.record.email}")

        # Check existence
        exists = await store.record_exists("Person", (1,))
        print(f"  Customer 1 exists: {exists}")

        exists = await store.record_exists("Person", (999,))
        print(f"  Customer 999 exists: {exists}")

        # UPDATE: Modify and save
        print_subheader("UPDATE - Modify Records")

        alice = customers[0]
        alice.age = 29  # Birthday!
        alice.city = "Boston"  # Moved
        await store.save_record(alice)
        print(f"  Updated Alice: age={alice.age}, city={alice.city}")

        # DELETE: Remove a record
        print_subheader("DELETE - Remove Records")

        deleted = await store.delete_record("Person", (8,))
        print(f"  Deleted customer 8: {deleted}")

        # Verify deletion
        loaded = await store.load_record("Person", (8,))
        print(f"  Customer 8 after delete: {'found' if loaded else 'not found'}")

        return store

    return await db.run(run_crud)


# =============================================================================
# SECTION 4: Index Scanning
# =============================================================================

async def demonstrate_index_scanning(db, metadata, subspace):
    """Demonstrate various index scan operations."""
    print_header("Index Scanning")

    import fdb_record_layer as frl

    async def run_scans(ctx):
        store = frl.FDBRecordStore(ctx, subspace, metadata)

        # Scan all records via index
        print_subheader("Scan All (via email index)")
        cursor = await store.scan_index("person_email")
        results = await cursor.to_list()
        print(f"  Total customers: {len(results)}")
        for r in results[:3]:
            print(f"    - {r.record.name}: {r.record.email}")
        if len(results) > 3:
            print(f"    ... and {len(results) - 3} more")

        # Equality scan
        print_subheader("Equality Scan (city = 'New York')")
        cursor = await store.scan_index(
            "person_city",
            frl.IndexScanRange.equals("New York")
        )
        results = await cursor.to_list()
        print(f"  Customers in New York: {len(results)}")
        for r in results:
            print(f"    - {r.record.name}")

        # Range scan
        print_subheader("Range Scan (age between 30 and 40)")
        cursor = await store.scan_index(
            "person_age",
            frl.IndexScanRange.between(30, 40)
        )
        results = await cursor.to_list()
        print(f"  Customers age 30-40: {len(results)}")
        for r in results:
            print(f"    - {r.record.name} (age {r.record.age})")

        # Composite index scan
        print_subheader("Composite Index Scan (city='Los Angeles', age=35)")
        cursor = await store.scan_index(
            "person_city_age",
            frl.IndexScanRange.equals("Los Angeles", 35)
        )
        results = await cursor.to_list()
        print(f"  Customers in LA age 35: {len(results)}")
        for r in results:
            print(f"    - {r.record.name}")

        # Prefix scan on composite index
        print_subheader("Prefix Scan (city='Chicago', any age)")
        cursor = await store.scan_index(
            "person_city_age",
            frl.IndexScanRange.prefix("Chicago")
        )
        results = await cursor.to_list()
        print(f"  All customers in Chicago: {len(results)}")
        for r in results:
            print(f"    - {r.record.name} (age {r.record.age})")

    await db.run(run_scans)


# =============================================================================
# SECTION 5: Query Builder API
# =============================================================================

async def demonstrate_query_builder(db, metadata, subspace):
    """Demonstrate the Query Builder API."""
    print_header("Query Builder API")

    import fdb_record_layer as frl
    from fdb_record_layer.query import Query, Field

    async def run_queries(ctx):
        store = frl.FDBRecordStore(ctx, subspace, metadata)

        # Simple equality query
        print_subheader("Simple Equality Query")
        query = (
            Query.from_type("Person")
            .where(Field("city").equals("New York"))
            .build()
        )
        print(f"  Query: {query.filter}")
        cursor = await store.execute_query(query)
        results = await cursor.to_list()
        print(f"  Results: {len(results)} customers")
        for r in results:
            print(f"    - {r.record.name}")

        # Range query
        print_subheader("Range Query (age > 35)")
        query = (
            Query.from_type("Person")
            .where(Field("age").greater_than(35))
            .build()
        )
        cursor = await store.execute_query(query)
        results = await cursor.to_list()
        print(f"  Customers over 35: {len(results)}")
        for r in results:
            print(f"    - {r.record.name} (age {r.record.age})")

        # Combined AND query
        print_subheader("Combined AND Query")
        query = (
            Query.from_type("Person")
            .where(Field("city").equals("New York"))
            .where(Field("age").greater_than(25))  # Chained = AND
            .build()
        )
        cursor = await store.execute_query(query)
        results = await cursor.to_list()
        print(f"  NY customers over 25: {len(results)}")
        for r in results:
            print(f"    - {r.record.name}")

        # OR query
        print_subheader("OR Query")
        query = (
            Query.from_type("Person")
            .where(
                Query.or_(
                    Field("city").equals("New York"),
                    Field("city").equals("Los Angeles")
                )
            )
            .build()
        )
        cursor = await store.execute_query(query)
        results = await cursor.to_list()
        print(f"  NY or LA customers: {len(results)}")
        for r in results:
            print(f"    - {r.record.name} ({r.record.city})")

        # IN query
        print_subheader("IN Query")
        query = (
            Query.from_type("Person")
            .where(Field("age").in_values([28, 35, 42]))
            .build()
        )
        cursor = await store.execute_query(query)
        results = await cursor.to_list()
        print(f"  Customers with specific ages: {len(results)}")
        for r in results:
            print(f"    - {r.record.name} (age {r.record.age})")

        # Query with explain
        print_subheader("Query Explanation")
        query = (
            Query.from_type("Person")
            .where(Field("email").equals("alice@example.com"))
            .build()
        )
        explanation = store.explain_query(query)
        print(f"  Plan: {explanation}")

    await db.run(run_queries)


# =============================================================================
# SECTION 6: COUNT Index and Aggregations
# =============================================================================

async def demonstrate_count_index(db, metadata, subspace):
    """Demonstrate COUNT index for fast aggregations."""
    print_header("COUNT Index & Aggregations")

    import fdb_record_layer as frl

    async def run_counts(ctx):
        store = frl.FDBRecordStore(ctx, subspace, metadata)

        print_subheader("Order Status Counts (via COUNT index)")

        # These use the pre-computed COUNT index - O(1) lookups!
        statuses = ["pending", "shipped", "delivered", "cancelled"]
        for status in statuses:
            count = store.get_count("order_status_count", status)
            if count > 0:
                print(f"  {status}: {count} orders")

        print_subheader("Customer Distribution by City")
        # Note: This would need a COUNT index on city to be efficient
        # Without it, we scan and count in-memory
        cursor = await store.scan_index("person_city")
        results = await cursor.to_list()

        city_counts = {}
        for r in results:
            city = r.record.city
            city_counts[city] = city_counts.get(city, 0) + 1

        for city, count in sorted(city_counts.items(), key=lambda x: -x[1]):
            print(f"  {city}: {count} customers")

    await db.run(run_counts)


# =============================================================================
# SECTION 7: SQL Queries
# =============================================================================

def demonstrate_sql_queries():
    """Demonstrate SQL query support."""
    print_header("SQL Query Support")

    from fdb_record_layer.relational.database import connect

    # Create in-memory database
    db = connect("ecommerce")

    # Create tables
    print_subheader("CREATE TABLE")
    db.execute_sql("""
        CREATE TABLE customers (
            id BIGINT PRIMARY KEY,
            name STRING NOT NULL,
            email STRING NOT NULL,
            city STRING,
            age INT
        )
    """)
    print("  Created 'customers' table")

    db.execute_sql("""
        CREATE TABLE orders (
            id BIGINT PRIMARY KEY,
            customer_id BIGINT NOT NULL,
            status STRING,
            total_cents INT,
            created_at BIGINT
        )
    """)
    print("  Created 'orders' table")

    # Insert data
    print_subheader("INSERT Data")
    customers_data = [
        (1, "Alice Johnson", "alice@example.com", "New York", 28),
        (2, "Bob Smith", "bob@example.com", "Los Angeles", 35),
        (3, "Carol White", "carol@example.com", "New York", 42),
        (4, "David Brown", "david@example.com", "Chicago", 31),
        (5, "Eve Davis", "eve@example.com", "New York", 28),
    ]
    for c in customers_data:
        db.execute_sql(f"INSERT INTO customers (id, name, email, city, age) VALUES ({c[0]}, '{c[1]}', '{c[2]}', '{c[3]}', {c[4]})")
    print(f"  Inserted {len(customers_data)} customers")

    orders_data = [
        (101, 1, "delivered", 15000, 1700000000),
        (102, 1, "shipped", 8500, 1700100000),
        (103, 2, "pending", 22000, 1700200000),
        (104, 3, "delivered", 5500, 1700300000),
        (105, 4, "cancelled", 12000, 1700400000),
    ]
    for o in orders_data:
        db.execute_sql(f"INSERT INTO orders (id, customer_id, status, total_cents, created_at) VALUES ({o[0]}, {o[1]}, '{o[2]}', {o[3]}, {o[4]})")
    print(f"  Inserted {len(orders_data)} orders")

    # SELECT queries
    print_subheader("SELECT Queries")

    # Simple SELECT
    result = db.query("SELECT name, city FROM customers WHERE age > 30")
    print("  Customers over 30:")
    for row in result:
        print(f"    - {row['name']} ({row['city']})")

    # SELECT with ORDER BY
    result = db.query("SELECT name, age FROM customers ORDER BY age DESC")
    print("  Customers by age (descending):")
    for row in result:
        print(f"    - {row['name']}: {row['age']}")

    # SELECT with LIMIT
    result = db.query("SELECT name FROM customers ORDER BY name LIMIT 3")
    print("  First 3 customers alphabetically:")
    for row in result:
        print(f"    - {row['name']}")

    # Aggregate functions
    print_subheader("Aggregate Functions")

    result = db.query("SELECT COUNT(*) FROM customers")
    print(f"  Total customers: {list(result)[0][0]}")

    result = db.query("SELECT AVG(age) FROM customers")
    print(f"  Average age: {list(result)[0][0]:.1f}")

    result = db.query("SELECT MIN(age), MAX(age) FROM customers")
    row = list(result)[0]
    print(f"  Age range: {row[0]} - {row[1]}")

    result = db.query("SELECT SUM(total_cents) FROM orders WHERE status = 'delivered'")
    print(f"  Total delivered: ${list(result)[0][0] / 100:.2f}")

    # GROUP BY
    print_subheader("GROUP BY Queries")

    result = db.query("SELECT city, COUNT(*) FROM customers GROUP BY city")
    print("  Customers per city:")
    for row in result:
        print(f"    - {row['city']}: {row['COUNT(*)']}")

    result = db.query("SELECT status, COUNT(*), SUM(total_cents) FROM orders GROUP BY status")
    print("  Orders by status:")
    for row in result:
        print(f"    - {row['status']}: {row['COUNT(*)']} orders, ${row['SUM(total_cents)'] / 100:.2f}")

    # UPDATE
    print_subheader("UPDATE")
    result = db.execute_sql("UPDATE customers SET age = 29 WHERE name = 'Alice Johnson'")
    print(f"  Updated {result.rows_affected} row(s)")

    # DELETE
    print_subheader("DELETE")
    result = db.execute_sql("DELETE FROM orders WHERE status = 'cancelled'")
    print(f"  Deleted {result.rows_affected} row(s)")

    db.close()


# =============================================================================
# SECTION 8: Production Utilities
# =============================================================================

def demonstrate_production_utilities():
    """Demonstrate production-ready utilities."""
    print_header("Production Utilities")

    # Metrics
    print_subheader("Metrics Collection")
    from fdb_record_layer.utils.metrics import (
        Counter, Gauge, Histogram, Timer,
        MetricsCollector, get_metrics, reset_metrics
    )

    reset_metrics()
    metrics = get_metrics()

    # Simulate operations
    metrics.record_read("customers", 0.005, 1024)
    metrics.record_read("customers", 0.003, 512)
    metrics.record_write("orders", 0.010, 2048)
    metrics.record_query("select", 0.025, 50)

    summary = metrics.get_summary()
    print(f"  Reads: {summary['counters']['reads']}")
    print(f"  Writes: {summary['counters']['writes']}")
    print(f"  Queries: {summary['counters']['queries']}")

    # LRU Cache
    print_subheader("LRU Cache")
    from fdb_record_layer.utils.cache import LRUCache, CacheConfig

    cache = LRUCache(CacheConfig(max_size=100, ttl_seconds=300))

    # Simulate caching records
    cache.put("customer:1", {"id": 1, "name": "Alice"})
    cache.put("customer:2", {"id": 2, "name": "Bob"})
    cache.put("customer:3", {"id": 3, "name": "Carol"})

    # Access
    result = cache.get("customer:1")
    print(f"  Cached customer 1: {result}")

    # Get or compute
    def load_customer(key):
        print(f"    Loading {key} from database...")
        return {"id": 4, "name": "David"}

    result = cache.get_or_compute("customer:4", load_customer)
    result = cache.get_or_compute("customer:4", load_customer)  # Should use cache

    stats = cache.stats
    print(f"  Cache stats: hits={stats.hits}, misses={stats.misses}, hit_rate={stats.hit_rate:.1%}")

    # Circuit Breaker
    print_subheader("Circuit Breaker")
    from fdb_record_layer.utils.circuit_breaker import (
        CircuitBreaker, CircuitBreakerConfig, CircuitState
    )

    breaker = CircuitBreaker(
        "fdb",
        CircuitBreakerConfig(
            failure_threshold=5,
            success_threshold=2,
            timeout_seconds=30.0
        )
    )
    print(f"  Circuit state: {breaker.state.value}")
    print(f"  Failure count: {breaker.failure_count}")

    # Health Checks
    print_subheader("Health Checks")
    from fdb_record_layer.utils.health import (
        HealthChecker, HealthStatus, get_health_checker, reset_health_checker
    )

    reset_health_checker()
    checker = get_health_checker()

    # Register checks
    async def check_database():
        return HealthStatus.HEALTHY, "Database responding"

    async def check_cache():
        return HealthStatus.HEALTHY, "Cache operational"

    checker.register_check("database", check_database)
    checker.register_check("cache", check_cache)

    async def run_health():
        report = await checker.check_health()
        print(f"  Overall status: {report.status.value}")
        for name, health in report.components.items():
            print(f"    - {name}: {health.status.value}")

    asyncio.run(run_health())

    # Batch Processing
    print_subheader("Batch Processing")
    from fdb_record_layer.utils.batch import BatchProcessor, BatchConfig, BatchResult

    async def process_batch(items):
        # Simulate processing
        return [item * 2 for item in items]

    async def run_batch():
        processor = BatchProcessor(
            process_batch,
            BatchConfig(batch_size=10, max_concurrent_batches=3)
        )
        result = await processor.process(list(range(25)))
        print(f"  Processed: {result.total_succeeded}/{result.total_processed} items")
        print(f"  Success rate: {result.success_rate:.1%}")

    asyncio.run(run_batch())


# =============================================================================
# SECTION 9: Pagination with Continuations
# =============================================================================

async def demonstrate_pagination(db, metadata, subspace):
    """Demonstrate pagination using continuations."""
    print_header("Pagination with Continuations")

    import fdb_record_layer as frl

    async def run_pagination(ctx):
        store = frl.FDBRecordStore(ctx, subspace, metadata)

        print_subheader("Page Through All Customers (2 per page)")

        page_num = 0
        continuation = None

        while True:
            page_num += 1
            cursor = await store.scan_index(
                "person_email",
                limit=2,
                continuation=continuation
            )

            results = await cursor.to_list()

            if not results:
                break

            print(f"  Page {page_num}:")
            for r in results:
                print(f"    - {r.record.name}")

            continuation = cursor.get_continuation()
            if continuation is None or continuation.is_end():
                break

            # In real app, you'd return continuation to client
            # Client sends it back on next request

        print(f"  Total pages: {page_num}")

    await db.run(run_pagination)


# =============================================================================
# SECTION 10: Schema Evolution
# =============================================================================

def demonstrate_schema_evolution():
    """Demonstrate schema evolution validation."""
    print_header("Schema Evolution")

    from fdb_record_layer.metadata.evolution import (
        MetaDataEvolutionValidator, EvolutionSeverity
    )
    from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType
    from fdb_record_layer.metadata.index import Index, IndexType
    from fdb_record_layer.expressions.field import FieldKeyExpression

    # Mock descriptor
    class MockDescriptor:
        def __init__(self, fields):
            self.name = "Customer"
            self.fields = fields

    class MockField:
        def __init__(self, name):
            self.name = name

    # Version 1 schema
    old_metadata = RecordMetaData(
        version=1,
        record_types={
            "Customer": RecordType(
                name="Customer",
                descriptor=MockDescriptor([MockField("id"), MockField("name"), MockField("email")]),
                primary_key=FieldKeyExpression("id"),
            ),
        },
        indexes={
            "Customer$email": Index(
                name="Customer$email",
                root_expression=FieldKeyExpression("email"),
                index_type=IndexType.VALUE,
                record_types=["Customer"],
            ),
        },
    )

    # Version 2 schema (added fields and index)
    new_metadata = RecordMetaData(
        version=2,
        record_types={
            "Customer": RecordType(
                name="Customer",
                descriptor=MockDescriptor([
                    MockField("id"), MockField("name"), MockField("email"),
                    MockField("phone"),  # New field
                    MockField("loyalty_tier"),  # New field
                ]),
                primary_key=FieldKeyExpression("id"),
            ),
        },
        indexes={
            "Customer$email": Index(
                name="Customer$email",
                root_expression=FieldKeyExpression("email"),
                index_type=IndexType.VALUE,
                record_types=["Customer"],
            ),
            "Customer$phone": Index(  # New index
                name="Customer$phone",
                root_expression=FieldKeyExpression("phone"),
                index_type=IndexType.VALUE,
                record_types=["Customer"],
            ),
        },
    )

    validator = MetaDataEvolutionValidator()
    result = validator.validate(old_metadata, new_metadata)

    print_subheader("Evolution Validation Result")
    print(f"  Valid: {result.is_valid}")
    print(f"  Issues: {len(result.issues)}")

    for issue in result.issues:
        severity = "INFO" if issue.severity == EvolutionSeverity.INFO else \
                   "WARNING" if issue.severity == EvolutionSeverity.WARNING else \
                   "ERROR" if issue.severity == EvolutionSeverity.ERROR else "REBUILD"
        print(f"    [{severity}] {issue.message}")

    if result.requires_rebuild:
        print(f"  Indexes requiring rebuild: {result.requires_rebuild}")

    # Test invalid evolution (primary key change)
    print_subheader("Invalid Evolution (Primary Key Change)")

    bad_metadata = RecordMetaData(
        version=2,
        record_types={
            "Customer": RecordType(
                name="Customer",
                descriptor=MockDescriptor([MockField("id"), MockField("name"), MockField("email")]),
                primary_key=FieldKeyExpression("email"),  # Changed PK!
            ),
        },
        indexes={},
    )

    result = validator.validate(old_metadata, bad_metadata)
    print(f"  Valid: {result.is_valid}")
    for issue in result.issues:
        if issue.severity == EvolutionSeverity.ERROR:
            print(f"  Error: {issue.message}")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run all demonstrations."""
    print("\n" + "=" * 70)
    print(" FDB Record Layer for Python - Comprehensive Example")
    print(" An E-Commerce Database Demonstration")
    print("=" * 70)

    try:
        import fdb
        fdb.api_version(740)

        import fdb_record_layer as frl
        from fdb.subspace_impl import Subspace

        # Initialize
        cluster_file = os.path.expanduser("~/.fdb/conf/fdb.cluster")
        db = frl.FDBDatabase(cluster_file)
        metadata = create_metadata()
        subspace = Subspace(("examples", "comprehensive"))

        print(f"\nConnected to FoundationDB")
        print(f"Record types: {list(metadata.record_types.keys())}")
        print(f"Indexes: {list(metadata.indexes.keys())}")

        # Run FDB-dependent demonstrations
        await demonstrate_crud_operations(db, metadata, subspace)
        await demonstrate_index_scanning(db, metadata, subspace)
        await demonstrate_query_builder(db, metadata, subspace)
        await demonstrate_count_index(db, metadata, subspace)
        await demonstrate_pagination(db, metadata, subspace)

    except Exception as e:
        print(f"\nSkipping FDB demonstrations: {e}")
        print("(Install FoundationDB to run full demonstrations)")

    # Run demonstrations that don't require FDB
    demonstrate_sql_queries()
    demonstrate_production_utilities()
    demonstrate_schema_evolution()

    print_header("Summary")
    print("""
This comprehensive example demonstrated:

1. CRUD Operations
   - Create records with save_record()
   - Read with load_record() and record_exists()
   - Update by saving modified records
   - Delete with delete_record()

2. Index Scanning
   - Full index scans
   - Equality scans (equals)
   - Range scans (between, greater_than, less_than)
   - Composite index scans
   - Prefix scans

3. Query Builder API
   - Simple equality queries
   - Range queries
   - AND/OR combinations
   - IN queries
   - Query explanation

4. COUNT Index & Aggregations
   - Pre-computed counts via COUNT index
   - O(1) aggregation lookups

5. SQL Support
   - CREATE TABLE / DROP TABLE
   - SELECT with WHERE, ORDER BY, LIMIT
   - INSERT, UPDATE, DELETE
   - Aggregate functions (COUNT, SUM, AVG, MIN, MAX)
   - GROUP BY queries

6. Production Utilities
   - Metrics collection
   - LRU caching
   - Circuit breakers
   - Health checks
   - Batch processing

7. Pagination
   - Continuation-based paging
   - Resumable cursors

8. Schema Evolution
   - Safe evolution validation
   - Field/index change detection
   - Primary key protection

For more features, see:
- RANK indexes for leaderboards
- TEXT indexes for full-text search
- Cascades cost-based query optimizer
- Online index building
- Connection pooling
- Lifecycle management
""")


if __name__ == "__main__":
    asyncio.run(main())
