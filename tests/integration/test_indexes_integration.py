"""Integration tests for index operations with real FoundationDB."""

import pytest

from fdb_record_layer.core.context import FDBRecordContext
from fdb_record_layer.core.store import FDBRecordStore
from fdb_record_layer.metadata.index import IndexState

pytestmark = pytest.mark.integration


class TestIndexMaintenance:
    """Test automatic index maintenance."""

    @pytest.mark.asyncio
    async def test_index_created_on_save(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test that index entries are created when saving records."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save a record
            person = person_class(id=1, name="Alpha", age=30, city="NYC")
            await store.save_record(person)

            # The index entry should exist (we check by state)
            index_state = store.get_index_state("Person$name")
            assert index_state == IndexState.READABLE

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_index_updated_on_update(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test that index entries are updated when updating records."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save initial record
            person = person_class(id=2, name="Beta", age=25)
            await store.save_record(person)

            # Update the record with new name
            updated = person_class(id=2, name="Gamma", age=25)
            await store.save_record(updated)

            # Load and verify
            loaded = await store.load_record("Person", (2,))
            assert loaded is not None
            assert loaded.record.name == "Gamma"

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_index_removed_on_delete(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test that index entries are removed when deleting records."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save a record
            person = person_class(id=3, name="Delta", age=35)
            await store.save_record(person)

            # Delete the record
            deleted = await store.delete_record("Person", (3,))
            assert deleted is True

            # Verify record is gone
            loaded = await store.load_record("Person", (3,))
            assert loaded is None

            await ctx.commit()

        finally:
            ctx.close()


class TestIndexState:
    """Test index state management."""

    @pytest.mark.asyncio
    async def test_default_index_state(self, fdb_database, test_subspace, record_metadata):
        """Test that default index state is READABLE."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            state = store.get_index_state("Person$name")
            assert state == IndexState.READABLE

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_set_index_state(self, fdb_database, test_subspace, record_metadata):
        """Test setting index state."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Set to WRITE_ONLY
            store.set_index_state("Person$name", IndexState.WRITE_ONLY)
            state = store.get_index_state("Person$name")
            assert state == IndexState.WRITE_ONLY

            # Set back to READABLE
            store.set_index_state("Person$name", IndexState.READABLE)
            state = store.get_index_state("Person$name")
            assert state == IndexState.READABLE

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_disabled_index_not_updated(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test that disabled indexes are not updated on save."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Disable one index
            store.set_index_state("Person$age", IndexState.DISABLED)

            # Save a record - should still work
            person = person_class(id=10, name="Test", age=99)
            await store.save_record(person)

            # Verify record saved
            loaded = await store.load_record("Person", (10,))
            assert loaded is not None
            assert loaded.record.age == 99

            await ctx.commit()

        finally:
            ctx.close()


class TestMultipleRecords:
    """Test index behavior with multiple records."""

    @pytest.mark.asyncio
    async def test_multiple_records_same_index_value(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test multiple records with same indexed value."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save multiple records with same city
            for i in range(20, 25):
                person = person_class(id=i, name=f"Person{i}", city="SharedCity")
                await store.save_record(person)

            # All should be loadable
            for i in range(20, 25):
                loaded = await store.load_record("Person", (i,))
                assert loaded is not None
                assert loaded.record.city == "SharedCity"

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_update_indexed_value(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test updating an indexed value."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save initial record
            person = person_class(id=30, name="Original", age=25)
            await store.save_record(person)

            # Update with new indexed value
            updated = person_class(id=30, name="Updated", age=35)
            await store.save_record(updated)

            # Verify update
            loaded = await store.load_record("Person", (30,))
            assert loaded.record.name == "Updated"
            assert loaded.record.age == 35

            await ctx.commit()

        finally:
            ctx.close()


class TestMultipleIndexes:
    """Test behavior with multiple indexes."""

    @pytest.mark.asyncio
    async def test_all_indexes_updated(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test that all indexes are updated on save."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save a record with all indexed fields
            person = person_class(id=40, name="MultiIndex", age=40, city="Boston")
            await store.save_record(person)

            # All indexes should be in READABLE state
            assert store.get_index_state("Person$name") == IndexState.READABLE
            assert store.get_index_state("Person$age") == IndexState.READABLE
            assert store.get_index_state("Person$city") == IndexState.READABLE

            # Load and verify
            loaded = await store.load_record("Person", (40,))
            assert loaded is not None
            assert loaded.record.name == "MultiIndex"
            assert loaded.record.age == 40
            assert loaded.record.city == "Boston"

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_product_indexes(
        self, fdb_database, test_subspace, record_metadata, product_class
    ):
        """Test indexes on Product record type."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Save a product
            product = product_class(id=1, name="Widget", price=19.99, category="Electronics")
            await store.save_record(product)

            # Check index states
            assert store.get_index_state("Product$name") == IndexState.READABLE
            assert store.get_index_state("Product$category") == IndexState.READABLE

            # Load and verify
            loaded = await store.load_record("Product", (1,))
            assert loaded is not None
            assert loaded.record.name == "Widget"
            assert loaded.record.price == 19.99
            assert loaded.record.category == "Electronics"

            await ctx.commit()

        finally:
            ctx.close()


class TestIndexConsistency:
    """Test index consistency across operations."""

    @pytest.mark.asyncio
    async def test_batch_operations_update_indexes(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test that batch operations properly update indexes."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Batch save
            for i in range(50, 60):
                person = person_class(id=i, name=f"Batch{i}", age=20 + i)
                await store.save_record(person)

            # Verify all saved
            for i in range(50, 60):
                loaded = await store.load_record("Person", (i,))
                assert loaded is not None
                assert loaded.record.name == f"Batch{i}"

            # Batch delete
            for i in range(50, 55):
                deleted = await store.delete_record("Person", (i,))
                assert deleted is True

            # Verify half deleted, half remain
            for i in range(50, 55):
                loaded = await store.load_record("Person", (i,))
                assert loaded is None

            for i in range(55, 60):
                loaded = await store.load_record("Person", (i,))
                assert loaded is not None

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_rapid_update_same_record(
        self, fdb_database, test_subspace, record_metadata, person_class
    ):
        """Test rapid updates to the same record."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            store = FDBRecordStore(
                context=ctx,
                subspace=test_subspace,
                meta_data=record_metadata,
            )

            # Rapid updates
            for i in range(10):
                person = person_class(id=99, name=f"Version{i}", age=i)
                await store.save_record(person)

            # Should have final version
            loaded = await store.load_record("Person", (99,))
            assert loaded is not None
            assert loaded.record.name == "Version9"
            assert loaded.record.age == 9

            await ctx.commit()

        finally:
            ctx.close()
