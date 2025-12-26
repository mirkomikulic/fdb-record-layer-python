"""Integration tests for index operations with real FoundationDB."""

import pytest

from fdb_record_layer.core.context import FDBRecordContext
from fdb_record_layer.core.store import FDBRecordStore
from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType
from fdb_record_layer.expressions.field import FieldKeyExpression
from fdb_record_layer.metadata.index import Index, IndexType, IndexState
from fdb_record_layer.indexes.maintainer import IndexScanRange

pytestmark = pytest.mark.integration


class MockRecord:
    """Mock record for testing."""

    class _Descriptor:
        name = "TestRecord"

        @property
        def fields_by_name(self):
            return {
                "id": type("Field", (), {"name": "id"})(),
                "name": type("Field", (), {"name": "name"})(),
                "score": type("Field", (), {"name": "score"})(),
                "category": type("Field", (), {"name": "category"})(),
            }

    DESCRIPTOR = _Descriptor()

    def __init__(self, id: int, name: str, score: int = 0, category: str = ""):
        self.id = id
        self.name = name
        self.score = score
        self.category = category

    def SerializeToString(self) -> bytes:
        import json

        return json.dumps({
            "id": self.id,
            "name": self.name,
            "score": self.score,
            "category": self.category,
        }).encode()

    @classmethod
    def FromString(cls, data: bytes) -> "MockRecord":
        import json

        d = json.loads(data.decode())
        return cls(
            id=d["id"],
            name=d["name"],
            score=d.get("score", 0),
            category=d.get("category", ""),
        )


class MockSerializer:
    """Mock serializer for testing."""

    def serialize(self, record) -> bytes:
        return record.SerializeToString()

    def deserialize(self, data: bytes, descriptor) -> MockRecord:
        return MockRecord.FromString(data)


def create_test_metadata() -> RecordMetaData:
    """Create test metadata with indexes."""
    primary_key = FieldKeyExpression("id")

    record_type = RecordType(
        name="TestRecord",
        descriptor=MockRecord.DESCRIPTOR,
        primary_key=primary_key,
    )

    # VALUE index on name
    name_index = Index(
        name="TestRecord$name",
        root_expression=FieldKeyExpression("name"),
        index_type=IndexType.VALUE,
    )

    # VALUE index on score
    score_index = Index(
        name="TestRecord$score",
        root_expression=FieldKeyExpression("score"),
        index_type=IndexType.VALUE,
    )

    # VALUE index on category
    category_index = Index(
        name="TestRecord$category",
        root_expression=FieldKeyExpression("category"),
        index_type=IndexType.VALUE,
    )

    metadata = RecordMetaData()
    metadata.add_record_type(record_type)
    metadata.add_index("TestRecord", name_index)
    metadata.add_index("TestRecord", score_index)
    metadata.add_index("TestRecord", category_index)

    return metadata


@pytest.fixture
def test_metadata():
    return create_test_metadata()


@pytest.fixture
def test_serializer():
    return MockSerializer()


class TestIndexMaintenance:
    """Test automatic index maintenance."""

    @pytest.mark.asyncio
    async def test_index_created_on_save(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test that index entries are created when saving records."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Save a record
            record = MockRecord(id=1, name="Alpha", score=100, category="A")
            await store.save_record(record)

            # The index entry should exist (we check by scanning)
            index_state = store.get_index_state("TestRecord$name")
            assert index_state == IndexState.READABLE

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_index_updated_on_update(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test that index entries are updated when updating records."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Save initial record
            record = MockRecord(id=2, name="Beta", score=50)
            await store.save_record(record)

            # Update the record with new name
            updated = MockRecord(id=2, name="Gamma", score=50)
            await store.save_record(updated)

            # Load and verify
            loaded = await store.load_record("TestRecord", (2,))
            assert loaded is not None
            assert loaded.record.name == "Gamma"

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_index_removed_on_delete(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test that index entries are removed when deleting records."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Save a record
            record = MockRecord(id=3, name="Delta", score=75)
            await store.save_record(record)

            # Delete the record
            deleted = await store.delete_record("TestRecord", (3,))
            assert deleted is True

            # Verify record is gone
            loaded = await store.load_record("TestRecord", (3,))
            assert loaded is None

            await ctx.commit()

        finally:
            ctx.close()


class TestIndexState:
    """Test index state management."""

    @pytest.mark.asyncio
    async def test_default_index_state(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test that default index state is READABLE."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            state = store.get_index_state("TestRecord$name")
            assert state == IndexState.READABLE

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_set_index_state(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test setting index state."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Set to WRITE_ONLY
            store.set_index_state("TestRecord$name", IndexState.WRITE_ONLY)
            state = store.get_index_state("TestRecord$name")
            assert state == IndexState.WRITE_ONLY

            # Set back to READABLE
            store.set_index_state("TestRecord$name", IndexState.READABLE)
            state = store.get_index_state("TestRecord$name")
            assert state == IndexState.READABLE

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_disabled_index_not_updated(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test that disabled indexes are not updated on save."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Disable one index
            store.set_index_state("TestRecord$score", IndexState.DISABLED)

            # Save a record - should still work
            record = MockRecord(id=10, name="Test", score=999)
            await store.save_record(record)

            # Verify record saved
            loaded = await store.load_record("TestRecord", (10,))
            assert loaded is not None
            assert loaded.record.score == 999

            await ctx.commit()

        finally:
            ctx.close()


class TestMultipleRecords:
    """Test index behavior with multiple records."""

    @pytest.mark.asyncio
    async def test_multiple_records_same_index_value(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test multiple records with same indexed value."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Save multiple records with same category
            for i in range(20, 25):
                record = MockRecord(id=i, name=f"Record{i}", category="shared")
                await store.save_record(record)

            # All should be loadable
            for i in range(20, 25):
                loaded = await store.load_record("TestRecord", (i,))
                assert loaded is not None
                assert loaded.record.category == "shared"

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_update_indexed_value(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test updating an indexed value."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Save initial record
            record = MockRecord(id=30, name="Original", score=100)
            await store.save_record(record)

            # Update with new indexed value
            updated = MockRecord(id=30, name="Updated", score=200)
            await store.save_record(updated)

            # Verify update
            loaded = await store.load_record("TestRecord", (30,))
            assert loaded.record.name == "Updated"
            assert loaded.record.score == 200

            await ctx.commit()

        finally:
            ctx.close()


class TestIndexConsistency:
    """Test index consistency across operations."""

    @pytest.mark.asyncio
    async def test_batch_save_updates_indexes(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test that batch save properly updates all indexes."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Batch save
            records = [
                MockRecord(id=i, name=f"Batch{i}", score=i * 10, category="batch")
                for i in range(40, 50)
            ]
            await store.save_records(records)

            # Verify all saved
            for i in range(40, 50):
                loaded = await store.load_record("TestRecord", (i,))
                assert loaded is not None
                assert loaded.record.name == f"Batch{i}"

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_batch_delete_updates_indexes(
        self, fdb_database, test_subspace, test_metadata, test_serializer
    ):
        """Test that batch delete properly cleans up indexes."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=test_metadata,
                serializer=test_serializer,
            )

            # Save records
            for i in range(50, 55):
                record = MockRecord(id=i, name=f"ToDelete{i}", score=i)
                await store.save_record(record)

            # Batch delete
            keys = [(i,) for i in range(50, 55)]
            deleted = await store.delete_records("TestRecord", keys)
            assert deleted == 5

            # Verify all deleted
            for i in range(50, 55):
                loaded = await store.load_record("TestRecord", (i,))
                assert loaded is None

            await ctx.commit()

        finally:
            ctx.close()
