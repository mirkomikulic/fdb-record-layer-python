"""Integration tests for FDBRecordStore with real FoundationDB and protobuf."""

import pytest

from fdb_record_layer.core.context import FDBDatabase, FDBRecordContext
from fdb_record_layer.core.store import FDBRecordStore

pytestmark = pytest.mark.integration


class TestBasicCRUD:
    """Test basic CRUD operations with real FDB."""

    @pytest.mark.asyncio
    async def test_save_and_load_record(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test saving and loading a record."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Create and save a person
            person = person_class(id=1, name="Alice", email="alice@test.com", age=30)
            stored = await store.save_record(person)

            assert stored is not None
            assert stored.primary_key == (1,)

            # Load the record back
            loaded = await store.load_record("Person", (1,))
            assert loaded is not None
            assert loaded.record.id == 1
            assert loaded.record.name == "Alice"
            assert loaded.record.email == "alice@test.com"
            assert loaded.record.age == 30

            await ctx.commit()
        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_update_record(self, fdb_database, test_subspace, record_metadata, person_class):
        """Test updating an existing record."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save initial record
            person = person_class(id=2, name="Bob", age=25)
            await store.save_record(person)

            # Update the record
            person_updated = person_class(id=2, name="Bob", age=26)
            await store.save_record(person_updated)

            # Load and verify
            loaded = await store.load_record("Person", (2,))
            assert loaded is not None
            assert loaded.record.age == 26

            await ctx.commit()
        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_delete_record(self, fdb_database, test_subspace, record_metadata, person_class):
        """Test deleting a record."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save a record
            person = person_class(id=3, name="Charlie", age=35)
            await store.save_record(person)

            # Verify it exists
            assert await store.record_exists("Person", (3,))

            # Delete it
            deleted = await store.delete_record("Person", (3,))
            assert deleted is True

            # Verify it's gone
            assert not await store.record_exists("Person", (3,))

            # Delete again returns False
            deleted_again = await store.delete_record("Person", (3,))
            assert deleted_again is False

            await ctx.commit()
        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_load_nonexistent_record(self, fdb_database, test_subspace, record_metadata):
        """Test loading a record that doesn't exist."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Try to load non-existent record
            loaded = await store.load_record("Person", (99999,))
            assert loaded is None
        finally:
            ctx.close()


class TestMultipleRecordTypes:
    """Test operations with multiple record types."""

    @pytest.mark.asyncio
    async def test_save_different_record_types(
        self,
        fdb_database,
        test_subspace,
        record_metadata,
        person_class,
        product_class,
    ):
        """Test saving different record types."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save a person
            person = person_class(id=1, name="Alice", age=30)
            await store.save_record(person)

            # Save a product
            product = product_class(id=1, name="Widget", price=9.99, category="Electronics")
            await store.save_record(product)

            # Load both back
            loaded_person = await store.load_record("Person", (1,))
            loaded_product = await store.load_record("Product", (1,))

            assert loaded_person is not None
            assert loaded_person.record.name == "Alice"

            assert loaded_product is not None
            assert loaded_product.record.name == "Widget"
            assert loaded_product.record.price == 9.99

            await ctx.commit()
        finally:
            ctx.close()


class TestBatchOperations:
    """Test batch CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_multiple_records(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test saving multiple records."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Create multiple records
            for i in range(10):
                person = person_class(id=100 + i, name=f"Person{i}", age=20 + i)
                await store.save_record(person)

            # Verify all saved
            for i in range(10):
                loaded = await store.load_record("Person", (100 + i,))
                assert loaded is not None
                assert loaded.record.name == f"Person{i}"

            await ctx.commit()
        finally:
            ctx.close()


class TestDatabaseRun:
    """Test FDBDatabase.run() with RecordStore."""

    @pytest.mark.asyncio
    async def test_run_with_store(
        self, fdb_cluster_file, test_subspace, record_metadata, person_class
    ):
        """Test running store operations with db.run()."""
        db = FDBDatabase(fdb_cluster_file)

        async def save_person(ctx: FDBRecordContext):
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )
            person = person_class(id=200, name="TestPerson", age=50)
            return await store.save_record(person)

        result = await db.run(save_person)
        assert result is not None
        assert result.record.name == "TestPerson"

        # Verify data persisted in a new transaction
        async def load_person(ctx: FDBRecordContext):
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )
            return await store.load_record("Person", (200,))

        loaded = await db.run(load_person)
        assert loaded is not None
        assert loaded.record.id == 200
