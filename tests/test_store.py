"""Tests for FDBRecordStore CRUD operations."""

from unittest.mock import MagicMock, patch

import pytest

# Ensure FDB is mocked before imports


class MockValue:
    """Mock FDB value object."""

    def __init__(self, data: bytes | None = None):
        self._data = data

    def present(self) -> bool:
        return self._data is not None

    def __bytes__(self) -> bytes:
        return self._data or b""


class MockTransaction:
    """Mock FDB transaction for testing."""

    def __init__(self):
        self._data: dict[bytes, bytes] = {}
        self._futures: dict[bytes, MockValue] = {}

    def __getitem__(self, key: bytes) -> MockValue:
        data = self._data.get(key)
        return MockValue(data)

    def set(self, key: bytes, value: bytes) -> None:
        self._data[key] = value

    def clear(self, key: bytes) -> None:
        self._data.pop(key, None)

    def get_range(self, start: bytes, end: bytes):
        """Return items in the range."""
        return [(k, v) for k, v in sorted(self._data.items()) if start <= k < end]

    def commit(self):
        """Mock commit returning a waitable."""
        mock_future = MagicMock()
        mock_future.wait = MagicMock()
        return mock_future

    def get_committed_version(self) -> int:
        return 12345

    def cancel(self) -> None:
        pass

    def on_error(self, code):
        """Mock on_error for retry logic."""
        mock_future = MagicMock()
        mock_future.wait = MagicMock()
        return mock_future


class MockSubspace:
    """Mock FDB subspace for testing."""

    def __init__(self, prefix: tuple = ()):
        self._prefix = prefix

    def __getitem__(self, key) -> "MockSubspace":
        if isinstance(key, tuple):
            return MockSubspace(self._prefix + key)
        return MockSubspace(self._prefix + (key,))

    def pack(self, key) -> bytes:
        if isinstance(key, tuple):
            return str(self._prefix + key).encode()
        return str(self._prefix + (key,)).encode()

    def unpack(self, key: bytes) -> tuple:
        # Simple unpacking for testing
        key_str = key.decode()
        # Extract last tuple element for primary key
        return eval(key_str[len(str(self._prefix)) :])

    def range(self):
        """Return range boundaries."""
        mock_range = MagicMock()
        mock_range.start = str(self._prefix).encode() + b"\x00"
        mock_range.stop = str(self._prefix).encode() + b"\xff"
        return mock_range


class MockDescriptor:
    """Mock protobuf descriptor."""

    def __init__(self, name: str = "TestRecord"):
        self.name = name


class MockRecord:
    """Mock protobuf message for testing."""

    def __init__(self, id: int = 1, name: str = "test", age: int = 25):
        self.id = id
        self.name = name
        self.age = age
        self.DESCRIPTOR = MockDescriptor()

    def SerializeToString(self) -> bytes:  # noqa: N802
        return f"{self.id}|{self.name}|{self.age}".encode()

    def ListFields(self):  # noqa: N802
        return [
            (MagicMock(name="id"), self.id),
            (MagicMock(name="name"), self.name),
            (MagicMock(name="age"), self.age),
        ]


class MockSerializer:
    """Mock serializer for testing."""

    def serialize(self, record) -> bytes:
        return f"{record.id}|{record.name}|{record.age}".encode()

    def deserialize(self, data: bytes, descriptor) -> MockRecord:
        parts = data.decode().split("|")
        return MockRecord(int(parts[0]), parts[1], int(parts[2]))


class MockKeyExpression:
    """Mock key expression for testing."""

    def __init__(self, field_name: str = "id"):
        self.field_name = field_name

    def evaluate(self, record) -> list[tuple]:
        value = getattr(record, self.field_name)
        return [(value,)]


class MockRecordType:
    """Mock record type for testing."""

    def __init__(self, name: str = "TestRecord"):
        self.name = name
        self.primary_key = MockKeyExpression("id")
        self.descriptor = MockDescriptor(name)


class MockMetaData:
    """Mock record metadata for testing."""

    def __init__(self):
        self._record_types = {"TestRecord": MockRecordType()}
        self.indexes: dict = {}

    def has_record_type(self, name: str) -> bool:
        return name in self._record_types

    def get_record_type(self, name: str) -> MockRecordType:
        return self._record_types[name]

    def get_indexes_for_record_type(self, name: str) -> list:
        return []

    record_types = property(lambda self: self._record_types)


class MockContext:
    """Mock FDBRecordContext for testing."""

    def __init__(self, transaction: MockTransaction | None = None):
        self._transaction = transaction or MockTransaction()
        self._closed = False
        self.database = MagicMock()

    @property
    def transaction(self):
        return self._transaction

    def ensure_active(self):
        if self._closed:
            raise RuntimeError("Context closed")

    def close(self):
        self._closed = True

    async def commit(self):
        return 12345


@pytest.fixture
def mock_context():
    """Create a mock context for testing."""
    return MockContext()


@pytest.fixture
def mock_metadata():
    """Create mock metadata for testing."""
    return MockMetaData()


@pytest.fixture
def mock_subspace():
    """Create mock subspace for testing."""
    return MockSubspace(("records",))


@pytest.fixture
def mock_serializer():
    """Create mock serializer for testing."""
    return MockSerializer()


class TestFDBRecordStore:
    """Tests for FDBRecordStore."""

    def _create_store(self, context, subspace, metadata, serializer):
        """Create a store with mocks."""
        # Need to patch the imports
        with patch("fdb_record_layer.core.store.ValueIndexMaintainer"):
            from fdb_record_layer.core.store import FDBRecordStore

            store = FDBRecordStore(
                context=context,
                subspace=subspace,
                meta_data=metadata,
                serializer=serializer,
            )
            return store

    @pytest.mark.asyncio
    async def test_save_record_creates_new(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test saving a new record."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        record = MockRecord(id=1, name="Alice", age=30)
        result = await store.save_record(record)

        assert result.primary_key == (1,)
        assert result.record.name == "Alice"
        assert result.record.age == 30

    @pytest.mark.asyncio
    async def test_save_record_with_explicit_type(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test saving with explicit record type name."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        record = MockRecord(id=2, name="Bob", age=25)
        result = await store.save_record(record, record_type_name="TestRecord")

        assert result.primary_key == (2,)
        assert result.record_type.name == "TestRecord"

    @pytest.mark.asyncio
    async def test_save_record_unknown_type_raises(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test that saving unknown type raises exception."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        from fdb_record_layer.core.exceptions import RecordTypeNotFoundException

        record = MockRecord()
        record.DESCRIPTOR = MockDescriptor("UnknownType")

        with pytest.raises(RecordTypeNotFoundException):
            await store.save_record(record)

    @pytest.mark.asyncio
    async def test_load_record_returns_none_when_not_found(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test loading non-existent record returns None."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        result = await store.load_record("TestRecord", (999,))
        assert result is None

    @pytest.mark.asyncio
    async def test_load_record_unknown_type_raises(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test loading unknown type raises exception."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        from fdb_record_layer.core.exceptions import RecordTypeNotFoundException

        with pytest.raises(RecordTypeNotFoundException):
            await store.load_record("UnknownType", (1,))

    @pytest.mark.asyncio
    async def test_delete_record_returns_false_when_not_found(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test deleting non-existent record returns False."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        result = await store.delete_record("TestRecord", (999,))
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_record_unknown_type_raises(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test deleting unknown type raises exception."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        from fdb_record_layer.core.exceptions import RecordTypeNotFoundException

        with pytest.raises(RecordTypeNotFoundException):
            await store.delete_record("UnknownType", (1,))

    @pytest.mark.asyncio
    async def test_record_exists_returns_false_when_not_found(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test record_exists returns False for non-existent records."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        result = await store.record_exists("TestRecord", (999,))
        assert result is False

    @pytest.mark.asyncio
    async def test_load_records_batch_empty_list(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test batch loading empty list returns empty list."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        result = await store.load_records("TestRecord", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_save_records_batch_empty_list(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test batch saving empty list returns empty list."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        result = await store.save_records([])
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_records_batch_empty_list(
        self, mock_context, mock_subspace, mock_metadata, mock_serializer
    ):
        """Test batch deleting empty list returns 0."""
        store = self._create_store(mock_context, mock_subspace, mock_metadata, mock_serializer)

        result = await store.delete_records("TestRecord", [])
        assert result == 0


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        from fdb_record_layer.core.context import RetryConfig

        config = RetryConfig()
        assert config.max_retries == 10
        assert config.initial_delay_ms == 10.0
        assert config.max_delay_ms == 1000.0
        assert config.backoff_multiplier == 2.0
        assert config.timeout_seconds == 0.0

    def test_custom_values(self):
        """Test custom configuration values."""
        from fdb_record_layer.core.context import RetryConfig

        config = RetryConfig(
            max_retries=5,
            initial_delay_ms=50.0,
            max_delay_ms=500.0,
            backoff_multiplier=1.5,
            timeout_seconds=30.0,
        )
        assert config.max_retries == 5
        assert config.initial_delay_ms == 50.0
        assert config.max_delay_ms == 500.0
        assert config.backoff_multiplier == 1.5
        assert config.timeout_seconds == 30.0

    def test_calculate_delay_exponential_backoff(self):
        """Test exponential backoff calculation."""
        from fdb_record_layer.core.context import RetryConfig

        config = RetryConfig(initial_delay_ms=10.0, max_delay_ms=1000.0, backoff_multiplier=2.0)

        # Attempt 0: 10ms
        assert config.calculate_delay(0) == pytest.approx(0.01)
        # Attempt 1: 20ms
        assert config.calculate_delay(1) == pytest.approx(0.02)
        # Attempt 2: 40ms
        assert config.calculate_delay(2) == pytest.approx(0.04)
        # Attempt 5: 320ms
        assert config.calculate_delay(5) == pytest.approx(0.32)

    def test_calculate_delay_capped_at_max(self):
        """Test delay is capped at max_delay_ms."""
        from fdb_record_layer.core.context import RetryConfig

        config = RetryConfig(initial_delay_ms=100.0, max_delay_ms=500.0, backoff_multiplier=2.0)

        # Attempt 10 would be 100 * 2^10 = 102400ms, but capped at 500ms
        assert config.calculate_delay(10) == pytest.approx(0.5)


class TestTransactionExceptions:
    """Tests for transaction exception classes."""

    def test_transaction_conflict_error(self):
        """Test TransactionConflictError."""
        from fdb_record_layer.core.exceptions import TransactionConflictError

        error = TransactionConflictError("Test conflict")
        assert str(error) == "Test conflict"

    def test_transaction_retry_limit_exceeded(self):
        """Test TransactionRetryLimitExceeded."""
        from fdb_record_layer.core.exceptions import TransactionRetryLimitExceeded

        error = TransactionRetryLimitExceeded(5, ValueError("inner"))
        assert error.attempts == 5
        assert isinstance(error.last_error, ValueError)
        assert "5 attempts" in str(error)

    def test_transaction_timeout_error(self):
        """Test TransactionTimeoutError."""
        from fdb_record_layer.core.exceptions import TransactionTimeoutError

        error = TransactionTimeoutError(30.0)
        assert error.timeout_seconds == 30.0
        assert "30.0s" in str(error)


class TestFDBRecordContext:
    """Tests for FDBRecordContext."""

    def test_context_reset(self):
        """Test context reset clears state."""
        from fdb_record_layer.core.context import FDBRecordContext

        mock_db = MagicMock()
        mock_tr = MagicMock()
        mock_db.create_transaction.return_value = mock_tr

        ctx = FDBRecordContext(database=mock_db)
        _ = ctx.transaction  # Force transaction creation

        # Add some state
        ctx._read_version = 100
        ctx._commit_hooks.append(lambda: None)

        # Reset
        ctx.reset()

        # Verify state is cleared
        assert ctx._read_version is None
        assert ctx._committed_version is None
        assert ctx._commit_hooks == []
        assert ctx._transaction is None

    def test_reset_closed_context_raises(self):
        """Test resetting closed context raises error."""
        from fdb_record_layer.core.context import FDBRecordContext

        mock_db = MagicMock()
        ctx = FDBRecordContext(database=mock_db)
        ctx.close()

        with pytest.raises(RuntimeError, match="closed"):
            ctx.reset()

    def test_context_manager(self):
        """Test context manager protocol."""
        from fdb_record_layer.core.context import FDBRecordContext

        mock_db = MagicMock()

        with FDBRecordContext(database=mock_db) as ctx:
            assert not ctx.is_closed

        assert ctx.is_closed

    def test_ensure_active_raises_when_closed(self):
        """Test ensure_active raises when context is closed."""
        from fdb_record_layer.core.context import FDBRecordContext

        mock_db = MagicMock()
        ctx = FDBRecordContext(database=mock_db)
        ctx.close()

        with pytest.raises(RuntimeError):
            ctx.ensure_active()


class TestFDBRecordStoreBuilder:
    """Tests for FDBRecordStoreBuilder."""

    def test_builder_requires_context(self):
        """Test builder requires context."""
        from fdb_record_layer.core.store import FDBRecordStoreBuilder

        builder = FDBRecordStoreBuilder()
        builder.set_subspace(MockSubspace())
        builder.set_meta_data(MockMetaData())

        with pytest.raises(ValueError, match="Context is required"):
            builder.build()

    def test_builder_requires_subspace(self):
        """Test builder requires subspace."""
        from fdb_record_layer.core.store import FDBRecordStoreBuilder

        builder = FDBRecordStoreBuilder()
        builder.set_context(MockContext())
        builder.set_meta_data(MockMetaData())

        with pytest.raises(ValueError, match="Subspace is required"):
            builder.build()

    def test_builder_requires_metadata(self):
        """Test builder requires metadata."""
        from fdb_record_layer.core.store import FDBRecordStoreBuilder

        builder = FDBRecordStoreBuilder()
        builder.set_context(MockContext())
        builder.set_subspace(MockSubspace())

        with pytest.raises(ValueError, match="MetaData is required"):
            builder.build()

    def test_builder_fluent_api(self):
        """Test builder fluent API returns self."""
        from fdb_record_layer.core.store import FDBRecordStoreBuilder

        builder = FDBRecordStoreBuilder()

        # Each setter should return the builder
        result1 = builder.set_context(MockContext())
        result2 = builder.set_subspace(MockSubspace())
        result3 = builder.set_meta_data(MockMetaData())

        assert result1 is builder
        assert result2 is builder
        assert result3 is builder
