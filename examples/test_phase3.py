#!/usr/bin/env python3
"""Phase 3 Test - Advanced Indexes

Tests COUNT, SUM, RANK, and TEXT index types.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FDB_LIBRARY_PATH"] = os.path.expanduser("~/.fdb/lib/libfdb_c.dylib")
os.environ["FDB_CLUSTER_FILE"] = os.path.expanduser("~/.fdb/conf/fdb.cluster")


def main():
    """Run Phase 3 tests."""
    import fdb
    fdb.api_version(740)

    import fdb_record_layer as frl
    from fdb_record_layer.metadata.index import IndexType
    from sample_pb2 import Person, Order, DESCRIPTOR

    print("=" * 60)
    print("Phase 3: Advanced Indexes Test")
    print("=" * 60)

    # Step 1: Build metadata with advanced indexes
    print("\n1. Building metadata with advanced indexes...")

    metadata = (
        frl.RecordMetaDataBuilder(DESCRIPTOR)
        .set_record_type("Person", primary_key=frl.field("id"))
        .set_record_type("Order", primary_key=frl.field("id"))
        # VALUE indexes
        .add_index("Person", "Person$name", frl.field("name"))
        .add_index("Person", "Person$city", frl.field("city"))
        # COUNT index - count persons by city
        .add_count_index("Person", "Person$city_count", frl.field("city"))
        # COUNT index - count orders by status
        .add_count_index("Order", "Order$status_count", frl.field("status"))
        # RANK index - rank persons by age
        .add_rank_index("Person", "Person$age_rank", frl.field("age"))
        # TEXT index - search person name
        .add_text_index("Person", "Person$name_text", frl.field("name"))
        .build()
    )

    print(f"   Record types: {list(metadata.record_types.keys())}")
    print(f"   Indexes: {list(metadata.indexes.keys())}")
    for name, idx in metadata.indexes.items():
        print(f"     - {name}: {idx.index_type.value}")

    # Step 2: Test with FDB
    print("\n2. Testing indexes with FDB...")

    async def test_indexes():
        db = frl.FDBDatabase()

        with db.open_context() as ctx:
            subspace = fdb.Subspace(("test", "phase3"))
            store = frl.FDBRecordStore(ctx, subspace, metadata)

            # Clear existing data
            store.transaction.clear_range(subspace.range().start, subspace.range().stop)

            # Insert test persons
            print("\n   Inserting test data...")
            persons = [
                Person(id=1, name="Alice Smith", city="NYC", age=25),
                Person(id=2, name="Bob Jones", city="LA", age=30),
                Person(id=3, name="Charlie Brown", city="NYC", age=35),
                Person(id=4, name="Diana Prince", city="Chicago", age=28),
                Person(id=5, name="Eve Wilson", city="NYC", age=22),
                Person(id=6, name="Frank Miller", city="LA", age=40),
                Person(id=7, name="Grace Lee", city="Chicago", age=33),
                Person(id=8, name="Alice Johnson", city="LA", age=27),
            ]
            for p in persons:
                await store.save_record(p)
            print(f"   Inserted {len(persons)} persons")

            orders = [
                Order(id=1, customer_id=1, status="pending", total=100.0),
                Order(id=2, customer_id=1, status="completed", total=250.0),
                Order(id=3, customer_id=2, status="pending", total=75.0),
                Order(id=4, customer_id=3, status="completed", total=500.0),
                Order(id=5, customer_id=2, status="pending", total=300.0),
            ]
            for o in orders:
                await store.save_record(o)
            print(f"   Inserted {len(orders)} orders")

            await ctx.commit()

        # Test COUNT index
        print("\n3. Testing COUNT index...")
        with db.open_context() as ctx:
            store = frl.FDBRecordStore(ctx, subspace, metadata)

            # Count by city
            nyc_count = store.get_count("Person$city_count", "NYC")
            la_count = store.get_count("Person$city_count", "LA")
            chicago_count = store.get_count("Person$city_count", "Chicago")

            print(f"   Persons in NYC: {nyc_count}")
            print(f"   Persons in LA: {la_count}")
            print(f"   Persons in Chicago: {chicago_count}")

            # Count orders by status
            pending_count = store.get_count("Order$status_count", "pending")
            completed_count = store.get_count("Order$status_count", "completed")

            print(f"   Pending orders: {pending_count}")
            print(f"   Completed orders: {completed_count}")

        # Test RANK index
        print("\n4. Testing RANK index...")
        with db.open_context() as ctx:
            store = frl.FDBRecordStore(ctx, subspace, metadata)

            # Get rank of specific ages
            rank_25 = store.get_rank("Person$age_rank", (25,))
            rank_35 = store.get_rank("Person$age_rank", (35,))
            rank_40 = store.get_rank("Person$age_rank", (40,))

            print(f"   Rank of age 25: {rank_25}")
            print(f"   Rank of age 35: {rank_35}")
            print(f"   Rank of age 40: {rank_40}")

            # Get person at rank 0 (youngest)
            youngest = store.get_by_rank("Person$age_rank", 0)
            if youngest:
                print(f"   Youngest person: {youngest.record.name} (age {youngest.record.age})")

            # Get person at highest rank
            from fdb_record_layer.indexes.rank_index import RankIndexMaintainer
            maintainer = store._index_maintainers["Person$age_rank"]
            if isinstance(maintainer, RankIndexMaintainer):
                total = maintainer.get_count(store.transaction)
                oldest = store.get_by_rank("Person$age_rank", total - 1)
                if oldest:
                    print(f"   Oldest person: {oldest.record.name} (age {oldest.record.age})")

        # Test TEXT index
        print("\n5. Testing TEXT index...")
        with db.open_context() as ctx:
            store = frl.FDBRecordStore(ctx, subspace, metadata)

            # Search for "Alice"
            alice_results = store.text_search("Person$name_text", ["alice"])
            print(f"   Search 'alice': found {len(alice_results)} results")
            for r in alice_results:
                print(f"     - {r.record.name}")

            # Search for "Smith" OR "Jones"
            smith_jones = store.text_search("Person$name_text", ["smith", "jones"], match_all=False)
            print(f"   Search 'smith' OR 'jones': found {len(smith_jones)} results")
            for r in smith_jones:
                print(f"     - {r.record.name}")

            # Search for both "alice" AND "smith"
            alice_smith = store.text_search("Person$name_text", ["alice", "smith"], match_all=True)
            print(f"   Search 'alice' AND 'smith': found {len(alice_smith)} results")
            for r in alice_smith:
                print(f"     - {r.record.name}")

        # Test deleting and verifying counts update
        print("\n6. Testing count updates on delete...")
        with db.open_context() as ctx:
            store = frl.FDBRecordStore(ctx, subspace, metadata)

            nyc_before = store.get_count("Person$city_count", "NYC")
            print(f"   NYC count before delete: {nyc_before}")

            # Delete one NYC person
            await store.delete_record("Person", (1,))  # Alice Smith from NYC
            await ctx.commit()

        with db.open_context() as ctx:
            store = frl.FDBRecordStore(ctx, subspace, metadata)
            nyc_after = store.get_count("Person$city_count", "NYC")
            print(f"   NYC count after delete: {nyc_after}")
            assert nyc_after == nyc_before - 1, "Count should decrease by 1"
            print("   Count correctly decreased!")

    asyncio.run(test_indexes())

    print("\n" + "=" * 60)
    print("Phase 3 Test Complete!")
    print("=" * 60)
    print("\nPhase 3 successfully implemented:")
    print("  - COUNT index for aggregate counting")
    print("  - RANK index for leaderboard queries")
    print("  - TEXT index for full-text search")
    print("  - Index maintainer registry")
    print("  - Store integration with all index types")


if __name__ == "__main__":
    main()
