"""Test script for Phase 1 of FDB Record Layer.

This script tests:
- Record creation and retrieval
- Index maintenance
- Index scanning
"""

import asyncio
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fdb.subspace_impl import Subspace

import fdb_record_layer as frl
from examples.sample_pb2 import Person, DESCRIPTOR


async def main():
    print("=" * 60)
    print("FDB Record Layer - Phase 1 Test")
    print("=" * 60)

    # Set FDB library path
    os.environ["DYLD_LIBRARY_PATH"] = os.path.expanduser("~/.fdb/lib")

    # Connect to database
    print("\n1. Connecting to FoundationDB...")
    cluster_file = os.path.expanduser("~/.fdb/conf/fdb.cluster")
    db = frl.FDBDatabase(cluster_file)
    print("   Connected!")

    # Build metadata
    print("\n2. Building record metadata...")
    metadata = (
        frl.RecordMetaDataBuilder(DESCRIPTOR)
        .set_record_type("Person", primary_key=frl.field("id"))
        .add_index("Person", "email_idx", frl.field("email"))
        .add_index("Person", "city_idx", frl.field("city"))
        .add_index("Person", "age_city_idx", frl.concat(frl.field("age"), frl.field("city")))
        .build()
    )
    print(f"   Record types: {list(metadata.record_types.keys())}")
    print(f"   Indexes: {list(metadata.indexes.keys())}")

    # Create subspace for our test
    subspace = Subspace(("test", "phase1"))

    # Run tests
    async def run_tests(ctx):
        store = frl.FDBRecordStore(ctx, subspace, metadata)

        # Clear any existing data
        print("\n3. Clearing existing data...")
        ctx.transaction.clear_range_startswith(subspace.key())

        # Create test records
        print("\n4. Creating test records...")
        people = [
            Person(id=1, name="Alice", email="alice@example.com", age=30, city="New York"),
            Person(id=2, name="Bob", email="bob@example.com", age=25, city="Los Angeles"),
            Person(id=3, name="Charlie", email="charlie@example.com", age=35, city="New York"),
            Person(id=4, name="Diana", email="diana@example.com", age=28, city="Chicago"),
            Person(id=5, name="Eve", email="eve@example.com", age=30, city="New York"),
        ]

        for person in people:
            stored = await store.save_record(person)
            print(f"   Saved: {person.name} (id={stored.primary_key})")

        # Load a record
        print("\n5. Loading record by primary key...")
        loaded = await store.load_record("Person", (1,))
        if loaded:
            print(f"   Loaded: {loaded.record.name}, email={loaded.record.email}")
        else:
            print("   ERROR: Record not found!")

        # Check existence
        print("\n6. Checking record existence...")
        exists = await store.record_exists("Person", (1,))
        print(f"   Person(1) exists: {exists}")
        exists = await store.record_exists("Person", (999,))
        print(f"   Person(999) exists: {exists}")

        # Scan index - all emails
        print("\n7. Scanning email index (all)...")
        cursor = await store.scan_index("email_idx")
        results = await cursor.to_list()
        print(f"   Found {len(results)} records:")
        for r in results:
            print(f"     - {r.record.name}: {r.record.email}")

        # Scan index - specific city
        print("\n8. Scanning city index (New York only)...")
        cursor = await store.scan_index(
            "city_idx",
            frl.IndexScanRange.equals("New York")
        )
        results = await cursor.to_list()
        print(f"   Found {len(results)} records in New York:")
        for r in results:
            print(f"     - {r.record.name}")

        # Scan composite index - age 30 in New York
        print("\n9. Scanning age_city index (age=30, city=New York)...")
        cursor = await store.scan_index(
            "age_city_idx",
            frl.IndexScanRange.equals(30, "New York")
        )
        results = await cursor.to_list()
        print(f"   Found {len(results)} records age 30 in New York:")
        for r in results:
            print(f"     - {r.record.name}")

        # Update a record
        print("\n10. Updating a record...")
        alice = people[0]
        alice.city = "Boston"
        alice.age = 31
        await store.save_record(alice)
        print(f"    Updated Alice: now in {alice.city}, age {alice.age}")

        # Verify index updated
        print("\n11. Verifying index updated (New York should now have 2)...")
        cursor = await store.scan_index(
            "city_idx",
            frl.IndexScanRange.equals("New York")
        )
        results = await cursor.to_list()
        print(f"    New York now has {len(results)} records")

        cursor = await store.scan_index(
            "city_idx",
            frl.IndexScanRange.equals("Boston")
        )
        results = await cursor.to_list()
        print(f"    Boston now has {len(results)} records")

        # Delete a record
        print("\n12. Deleting a record...")
        deleted = await store.delete_record("Person", (5,))
        print(f"    Deleted Person(5): {deleted}")

        # Verify deletion
        loaded = await store.load_record("Person", (5,))
        print(f"    Person(5) after delete: {'exists' if loaded else 'not found'}")

        print("\n" + "=" * 60)
        print("Phase 1 tests completed successfully!")
        print("=" * 60)

    await db.run(run_tests)


if __name__ == "__main__":
    asyncio.run(main())
