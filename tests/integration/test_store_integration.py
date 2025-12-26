"""Integration tests for FDBRecordStore with real FoundationDB."""

import pytest

from fdb_record_layer.core.context import FDBDatabase, FDBRecordContext
from fdb_record_layer.core.store import FDBRecordStore
from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType
from fdb_record_layer.expressions.field import FieldKeyExpression
from fdb_record_layer.metadata.index import Index, IndexType

pytestmark = pytest.mark.integration


class MockPersonRecord:
    """Mock record for testing - simulates protobuf Message."""

    class _Descriptor:
        name = "Person"

        @property
        def fields_by_name(self):
            return {
                "id": type("Field", (), {"name": "id"})(),
                "name": type("Field", (), {"name": "name"})(),
                "age": type("Field", (), {"name": "age"})(),
                "email": type("Field", (), {"name": "email"})(),
            }

    DESCRIPTOR = _Descriptor()

    def __init__(self, id: int, name: str, age: int, email: str = ""):
        self.id = id
        self.name = name
        self.age = age
        self.email = email

    def SerializeToString(self) -> bytes:
        """Serialize to bytes (mock protobuf)."""
        import json

        return json.dumps(
            {"id": self.id, "name": self.name, "age": self.age, "email": self.email}
        ).encode()

    @classmethod
    def FromString(cls, data: bytes) -> "MockPersonRecord":
        """Deserialize from bytes (mock protobuf)."""
        import json

        d = json.loads(data.decode())
        return cls(id=d["id"], name=d["name"], age=d["age"], email=d.get("email", ""))


class MockSerializer:
    """Mock serializer for testing."""

    def serialize(self, record) -> bytes:
        return record.SerializeToString()

    def deserialize(self, data: bytes, descriptor) -> MockPersonRecord:
        return MockPersonRecord.FromString(data)


def create_test_metadata() -> RecordMetaData:
    """Create test metadata for Person records."""
    # Create primary key expression
    primary_key = FieldKeyExpression("id")

    # Create record type
    person_type = RecordType(
        name="Person",
        descriptor=MockPersonRecord.DESCRIPTOR,
        primary_key=primary_key,
    )

    # Create VALUE index on name
    name_index = Index(
        name="Person$name",
        root_expression=FieldKeyExpression("name"),
        index_type=IndexType.VALUE,
    )

    # Create VALUE index on age
    age_index = Index(
        name="Person$age",
        root_expression=FieldKeyExpression("age"),
        index_type=IndexType.VALUE,
    )

    # Create metadata
    metadata = RecordMetaData()
    metadata.add_record_type(person_type)
    metadata.add_index("Person", name_index)
    metadata.add_index("Person", age_index)

    return metadata


@pytest.fixture
def mock_metadata():
    """Create test metadata fixture."""
    return create_test_metadata()


@pytest.fixture
def mock_serializer():
    """Create mock serializer fixture."""
    return MockSerializer()


class TestBasicCRUD:
    """Test basic CRUD operations with real FDB."""

    @pytest.mark.asyncio
    async def test_save_and_load_record(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test saving and loading a record."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            # Create store with FDB subspace wrapper
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Create and save a record
            person = MockPersonRecord(id=1, name="Alice", age=30, email="alice@test.com")
            stored = await store.save_record(person)

            assert stored is not None
            assert stored.primary_key == (1,)
            assert stored.record.name == "Alice"

            # Load the record back
            loaded = await store.load_record("Person", (1,))
            assert loaded is not None
            assert loaded.record.id == 1
            assert loaded.record.name == "Alice"
            assert loaded.record.age == 30

            # Commit
            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_update_record(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test updating an existing record."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Save initial record
            person = MockPersonRecord(id=2, name="Bob", age=25)
            await store.save_record(person)

            # Update the record
            person_updated = MockPersonRecord(id=2, name="Bob", age=26)
            await store.save_record(person_updated)

            # Load and verify
            loaded = await store.load_record("Person", (2,))
            assert loaded is not None
            assert loaded.record.age == 26

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_delete_record(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test deleting a record."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Save a record
            person = MockPersonRecord(id=3, name="Charlie", age=35)
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
    async def test_load_nonexistent_record(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test loading a record that doesn't exist."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Try to load non-existent record
            loaded = await store.load_record("Person", (99999,))
            assert loaded is None

        finally:
            ctx.close()


class TestBatchOperations:
    """Test batch CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_multiple_records(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test saving multiple records in batch."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Create multiple records
            records = [
                MockPersonRecord(id=i, name=f"Person{i}", age=20 + i)
                for i in range(10, 20)
            ]

            # Save all
            stored = await store.save_records(records)
            assert len(stored) == 10

            # Verify all saved
            for i in range(10, 20):
                loaded = await store.load_record("Person", (i,))
                assert loaded is not None
                assert loaded.record.name == f"Person{i}"

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_load_multiple_records(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test loading multiple records in batch."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Save some records
            for i in range(20, 25):
                person = MockPersonRecord(id=i, name=f"Person{i}", age=30 + i)
                await store.save_record(person)

            # Load multiple at once
            primary_keys = [(i,) for i in range(20, 25)]
            loaded = await store.load_records("Person", primary_keys)

            assert len(loaded) == 5
            for i, record in enumerate(loaded):
                assert record is not None
                assert record.record.id == 20 + i

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_delete_multiple_records(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test deleting multiple records in batch."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Save some records
            for i in range(30, 35):
                person = MockPersonRecord(id=i, name=f"Person{i}", age=40 + i)
                await store.save_record(person)

            # Delete multiple
            primary_keys = [(i,) for i in range(30, 35)]
            deleted_count = await store.delete_records("Person", primary_keys)

            assert deleted_count == 5

            # Verify all deleted
            for i in range(30, 35):
                assert not await store.record_exists("Person", (i,))

            await ctx.commit()

        finally:
            ctx.close()


class TestDatabaseRun:
    """Test FDBDatabase.run() with automatic retry."""

    @pytest.mark.asyncio
    async def test_run_with_commit(self, fdb_cluster_file, test_subspace, mock_metadata, mock_serializer):
        """Test running a transactional function with auto-commit."""
        db = FDBDatabase(fdb_cluster_file)

        from fdb.subspace_impl import Subspace

        subspace = Subspace((test_subspace._prefix,))

        async def save_person(ctx: FDBRecordContext):
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )
            person = MockPersonRecord(id=100, name="TestPerson", age=50)
            return await store.save_record(person)

        result = await db.run(save_person)
        assert result is not None
        assert result.record.name == "TestPerson"

        # Verify data persisted in a new transaction
        async def load_person(ctx: FDBRecordContext):
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )
            return await store.load_record("Person", (100,))

        loaded = await db.run(load_person)
        assert loaded is not None
        assert loaded.record.id == 100


class TestRecordScan:
    """Test record scanning operations."""

    @pytest.mark.asyncio
    async def test_scan_all_records(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test scanning all records of a type."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Save several records
            for i in range(50, 55):
                person = MockPersonRecord(id=i, name=f"ScanPerson{i}", age=60 + i)
                await store.save_record(person)

            # Scan all
            cursor = await store.scan_records("Person")
            records = []
            async for result in cursor:
                records.append(result.get())

            assert len(records) == 5
            names = {r.record.name for r in records}
            assert names == {f"ScanPerson{i}" for i in range(50, 55)}

            await ctx.commit()

        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_scan_with_limit(
        self, fdb_database, test_subspace, mock_metadata, mock_serializer
    ):
        """Test scanning with a limit."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            from fdb.subspace_impl import Subspace

            subspace = Subspace((test_subspace._prefix,))
            store = FDBRecordStore(
                context=ctx,
                subspace=subspace,
                meta_data=mock_metadata,
                serializer=mock_serializer,
            )

            # Save several records
            for i in range(60, 70):
                person = MockPersonRecord(id=i, name=f"LimitPerson{i}", age=70 + i)
                await store.save_record(person)

            # Scan with limit
            cursor = await store.scan_records("Person", limit=3)
            records = []
            async for result in cursor:
                records.append(result.get())

            assert len(records) == 3

            await ctx.commit()

        finally:
            ctx.close()
