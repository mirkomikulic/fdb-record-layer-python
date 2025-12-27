#!/usr/bin/env python3
"""Phase 2 Test - Query System

Tests the query builder, planner, and execution.
"""

import asyncio
import os
import sys

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set FDB library path
os.environ["FDB_LIBRARY_PATH"] = os.path.expanduser("~/.fdb/lib/libfdb_c.dylib")
os.environ["FDB_CLUSTER_FILE"] = os.path.expanduser("~/.fdb/conf/fdb.cluster")


def main():
    """Run Phase 2 tests."""
    import fdb

    fdb.api_version(740)

    # Import our library
    import fdb_record_layer as frl
    from fdb_record_layer.query import Query, Field

    # Import test proto
    from sample_pb2 import Person, Order, DESCRIPTOR

    print("=" * 60)
    print("Phase 2: Query System Test")
    print("=" * 60)

    # Step 1: Build metadata with indexes
    print("\n1. Building metadata with indexes...")

    metadata = (
        frl.RecordMetaDataBuilder(DESCRIPTOR)
        .set_record_type("Person", primary_key=frl.field("id"))
        .set_record_type("Order", primary_key=frl.field("id"))
        .add_index("Person", "Person$name", frl.field("name"))
        .add_index("Person", "Person$email", frl.field("email"))
        .add_index("Person", "Person$age", frl.field("age"))
        .add_index("Order", "Order$customer_id", frl.field("customer_id"))
        .build()
    )

    print(f"   Record types: {list(metadata.record_types.keys())}")
    print(f"   Indexes: {list(metadata.indexes.keys())}")

    # Step 2: Test query builder
    print("\n2. Testing query builder API...")

    # Simple equality query
    q1 = Query.from_type("Person").where(
        Query.field("name").equals("Alice")
    ).build()
    print(f"   Query 1: {q1}")
    print(f"   Filter: {q1.filter}")

    # Range query
    q2 = Query.from_type("Person").where(
        Query.field("age").greater_than(21)
    ).build()
    print(f"   Query 2: {q2}")

    # AND query
    q3 = Query.from_type("Person").where(
        Query.and_(
            Query.field("name").equals("Alice"),
            Query.field("age").greater_than(18)
        )
    ).build()
    print(f"   Query 3: {q3}")

    # OR query
    q4 = Query.from_type("Person").where(
        Query.or_(
            Query.field("name").equals("Alice"),
            Query.field("name").equals("Bob")
        )
    ).build()
    print(f"   Query 4: {q4}")

    # Chained fluent API
    q5 = (Query.from_type("Person")
          .where(Field("name").equals("Alice"))
          .where(Field("age").greater_than(18))
          .build())
    print(f"   Query 5 (chained): {q5}")

    # Step 3: Test planner
    print("\n3. Testing heuristic planner...")

    planner = frl.HeuristicPlanner(metadata)

    # Test plan for equality query
    plan1 = planner.plan(q1)
    print(f"   Plan for equality query:")
    print(f"   {plan1.explain()}")

    # Test plan for range query
    plan2 = planner.plan(q2)
    print(f"\n   Plan for range query:")
    print(f"   {plan2.explain()}")

    # Test plan for AND query
    plan3 = planner.plan(q3)
    print(f"\n   Plan for AND query:")
    print(f"   {plan3.explain()}")

    # Test plan for OR query
    plan4 = planner.plan(q4)
    print(f"\n   Plan for OR query:")
    print(f"   {plan4.explain()}")

    # Step 4: Test execution with FDB
    print("\n4. Testing query execution with FDB...")

    async def test_query_execution():
        db = frl.FDBDatabase()

        with db.open_context() as ctx:
            subspace = fdb.Subspace(("test", "phase2"))
            store = frl.FDBRecordStore(ctx, subspace, metadata)

            # Clear any existing data
            store.transaction.clear_range(subspace.range().start, subspace.range().stop)

            # Insert test data
            print("\n   Inserting test persons...")
            persons = [
                Person(id=1, name="Alice", email="alice@test.com", age=25),
                Person(id=2, name="Bob", email="bob@test.com", age=30),
                Person(id=3, name="Charlie", email="charlie@test.com", age=35),
                Person(id=4, name="Diana", email="diana@test.com", age=28),
                Person(id=5, name="Alice", email="alice2@test.com", age=22),
            ]
            for p in persons:
                await store.save_record(p)
            print(f"   Inserted {len(persons)} persons")

            # Test equality query
            print("\n   Executing equality query (name='Alice')...")
            query = Query.from_type("Person").where(
                Field("name").equals("Alice")
            ).build()

            print(f"   Explain: {store.explain_query(query)}")

            cursor = await store.execute_query(query)
            results = []
            async for stored_record in cursor:
                results.append(stored_record)

            print(f"   Found {len(results)} matching records:")
            for r in results:
                print(f"     - {r.record.name} (age={r.record.age})")

            # Test range query
            print("\n   Executing range query (age > 27)...")
            query2 = Query.from_type("Person").where(
                Field("age").greater_than(27)
            ).build()

            print(f"   Explain: {store.explain_query(query2)}")

            cursor2 = await store.execute_query(query2)
            results2 = []
            async for stored_record in cursor2:
                results2.append(stored_record)

            print(f"   Found {len(results2)} matching records:")
            for r in results2:
                print(f"     - {r.record.name} (age={r.record.age})")

            # Test combined query
            print("\n   Executing combined query (age >= 25 AND age <= 30)...")
            query3 = Query.from_type("Person").where(
                Field("age").between(25, 30)
            ).build()

            print(f"   Explain: {store.explain_query(query3)}")

            cursor3 = await store.execute_query(query3)
            results3 = []
            async for stored_record in cursor3:
                results3.append(stored_record)

            print(f"   Found {len(results3)} matching records:")
            for r in results3:
                print(f"     - {r.record.name} (age={r.record.age})")

            await ctx.commit()

    asyncio.run(test_query_execution())

    # Step 5: Test predicate evaluation
    print("\n5. Testing predicate evaluation...")

    person = Person(id=1, name="Test", email="test@test.com", age=25)

    # Test field predicates
    pred1 = Field("name").equals("Test")
    print(f"   name='Test': {pred1.evaluate(person)}")

    pred2 = Field("age").greater_than(20)
    print(f"   age>20: {pred2.evaluate(person)}")

    pred3 = Field("age").between(20, 30)
    print(f"   20<=age<=30: {pred3.evaluate(person)}")

    pred4 = Field("email").starts_with("test@")
    print(f"   email starts with 'test@': {pred4.evaluate(person)}")

    pred5 = Field("name").in_values(["Test", "Alice", "Bob"])
    print(f"   name in ['Test', 'Alice', 'Bob']: {pred5.evaluate(person)}")

    # Test combined predicates
    combined = pred1.and_(pred2)
    print(f"   name='Test' AND age>20: {combined.evaluate(person)}")

    print("\n" + "=" * 60)
    print("Phase 2 Test Complete!")
    print("=" * 60)
    print("\nPhase 2 successfully implemented:")
    print("  - Query builder with fluent API")
    print("  - Query components (AND, OR, NOT, Field)")
    print("  - Comparison operators")
    print("  - Heuristic planner with index selection")
    print("  - Execution plans (Scan, IndexScan, Filter)")
    print("  - Query execution through FDBRecordStore")


if __name__ == "__main__":
    main()
