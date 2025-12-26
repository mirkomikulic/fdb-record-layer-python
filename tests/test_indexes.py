"""Tests for index maintainers."""

import struct
from unittest.mock import MagicMock

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

    def __getitem__(self, key: bytes) -> MockValue:
        data = self._data.get(key)
        return MockValue(data)

    def set(self, key: bytes, value: bytes) -> None:
        self._data[key] = value

    def clear(self, key: bytes) -> None:
        self._data.pop(key, None)

    def add(self, key: bytes, value: bytes) -> None:
        """Atomic add operation."""
        existing = self._data.get(key, b"\x00\x00\x00\x00\x00\x00\x00\x00")
        existing_val = struct.unpack("<q", existing)[0]
        new_val = struct.unpack("<q", value)[0]
        self._data[key] = struct.pack("<q", existing_val + new_val)

    def get_range(self, start: bytes, end: bytes, limit: int = 0):
        """Return items in the range."""
        items = [(k, v) for k, v in sorted(self._data.items()) if start <= k < end]
        if limit:
            items = items[:limit]
        return items


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
        key_str = key.decode()
        prefix_str = str(self._prefix)
        return eval(key_str[len(prefix_str) :])

    def range(self):
        """Return range boundaries."""
        mock_range = MagicMock()
        # Use the string representation with comma to ensure packed keys fall within range
        prefix_str = str(self._prefix)
        # Remove closing paren and add comma to match key format
        if prefix_str.endswith(",)"):
            prefix_base = prefix_str[:-1]  # Remove just the ')'
        elif prefix_str.endswith(")"):
            prefix_base = prefix_str[:-1] + ", "  # Remove ')' add ', '
        else:
            prefix_base = prefix_str
        mock_range.start = prefix_base.encode() + b"\x00"
        mock_range.stop = prefix_base.encode() + b"\xff"
        return mock_range


class MockKeyExpression:
    """Mock key expression for testing."""

    def __init__(self, field_name: str = "id"):
        self.field_name = field_name
        self._column_size = 1

    def evaluate(self, record) -> list[tuple]:
        value = getattr(record, self.field_name, None)
        if value is None:
            return []
        return [(value,)]

    def get_column_size(self) -> int:
        return self._column_size


class MockIndex:
    """Mock index for testing."""

    def __init__(
        self,
        name: str = "test_index",
        root_expression: MockKeyExpression | None = None,
    ):
        self.name = name
        self.root_expression = root_expression or MockKeyExpression("status")
        self.options = MagicMock()
        self.options.__dict__ = {}
        self.record_types: list[str] = []


class MockMetaData:
    """Mock record metadata for testing."""

    def __init__(self):
        self._record_types = {}

    def has_record_type(self, name: str) -> bool:
        return name in self._record_types


class MockDescriptor:
    """Mock protobuf descriptor for testing."""

    def __init__(self, name: str = "MockRecord"):
        self.name = name


class MockRecord:
    """Mock protobuf message for testing."""

    def __init__(self, **kwargs):
        record_type = kwargs.pop("_type", "MockRecord")
        self.DESCRIPTOR = MockDescriptor(record_type)
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestCountIndexMaintainer:
    """Tests for CountIndexMaintainer."""

    def _create_maintainer(self, index=None, subspace=None):
        """Create a CountIndexMaintainer for testing."""
        from fdb_record_layer.indexes.count_index import CountIndexMaintainer

        index = index or MockIndex(root_expression=MockKeyExpression("status"))
        subspace = subspace or MockSubspace(("count_idx",))
        metadata = MockMetaData()

        return CountIndexMaintainer(index, subspace, metadata)

    @pytest.mark.asyncio
    async def test_update_increments_count(self):
        """Test that update increments the count."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        record = MockRecord(status="active", id=1)
        await maintainer.update(tr, record, (1,))

        # Check count was incremented
        count = maintainer.get_count(tr, "active")
        assert count == 1

        # Update again with same status
        record2 = MockRecord(status="active", id=2)
        await maintainer.update(tr, record2, (2,))

        count = maintainer.get_count(tr, "active")
        assert count == 2

    @pytest.mark.asyncio
    async def test_remove_decrements_count(self):
        """Test that remove decrements the count."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        # Add two records
        record1 = MockRecord(status="active", id=1)
        record2 = MockRecord(status="active", id=2)
        await maintainer.update(tr, record1, (1,))
        await maintainer.update(tr, record2, (2,))

        assert maintainer.get_count(tr, "active") == 2

        # Remove one
        await maintainer.remove(tr, record1, (1,))

        assert maintainer.get_count(tr, "active") == 1

    def test_get_count_returns_zero_for_missing(self):
        """Test get_count returns 0 for non-existent key."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        count = maintainer.get_count(tr, "nonexistent")
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_total_count(self):
        """Test get_total_count sums all counts."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        # Add records with different statuses
        await maintainer.update(tr, MockRecord(status="active"), (1,))
        await maintainer.update(tr, MockRecord(status="active"), (2,))
        await maintainer.update(tr, MockRecord(status="inactive"), (3,))

        total = maintainer.get_total_count(tr)
        assert total == 3

    @pytest.mark.asyncio
    async def test_scan_returns_empty_cursor(self):
        """Test that scan returns empty cursor for COUNT index."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        cursor = await maintainer.scan(tr, None, None, 10, lambda x, y: None)

        # Should return empty list
        results = []
        async for item in cursor:
            results.append(item)
        assert results == []


class TestSumIndexMaintainer:
    """Tests for SumIndexMaintainer."""

    def _create_maintainer(self, index=None, subspace=None, value_field="amount"):
        """Create a SumIndexMaintainer for testing."""
        from fdb_record_layer.indexes.count_index import SumIndexMaintainer

        index = index or MockIndex(root_expression=MockKeyExpression("category"))
        subspace = subspace or MockSubspace(("sum_idx",))
        metadata = MockMetaData()

        return SumIndexMaintainer(index, subspace, metadata, value_field=value_field)

    @pytest.mark.asyncio
    async def test_update_adds_to_sum(self):
        """Test that update adds value to sum."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        record = MockRecord(category="sales", amount=100)
        await maintainer.update(tr, record, (1,))

        sum_val = maintainer.get_sum(tr, "sales")
        assert sum_val == 100

        # Add another
        record2 = MockRecord(category="sales", amount=50)
        await maintainer.update(tr, record2, (2,))

        sum_val = maintainer.get_sum(tr, "sales")
        assert sum_val == 150

    @pytest.mark.asyncio
    async def test_remove_subtracts_from_sum(self):
        """Test that remove subtracts value from sum."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        record1 = MockRecord(category="sales", amount=100)
        record2 = MockRecord(category="sales", amount=50)
        await maintainer.update(tr, record1, (1,))
        await maintainer.update(tr, record2, (2,))

        assert maintainer.get_sum(tr, "sales") == 150

        # Remove one
        await maintainer.remove(tr, record1, (1,))

        assert maintainer.get_sum(tr, "sales") == 50

    def test_get_sum_returns_zero_for_missing(self):
        """Test get_sum returns 0 for non-existent key."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        sum_val = maintainer.get_sum(tr, "nonexistent")
        assert sum_val == 0

    @pytest.mark.asyncio
    async def test_get_total_sum(self):
        """Test get_total_sum sums all sums."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        await maintainer.update(tr, MockRecord(category="sales", amount=100), (1,))
        await maintainer.update(tr, MockRecord(category="marketing", amount=50), (2,))

        total = maintainer.get_total_sum(tr)
        assert total == 150


class TestMinMaxIndexMaintainer:
    """Tests for MinMaxIndexMaintainer."""

    def _create_maintainer(self, track_max=True, value_field="score"):
        """Create a MinMaxIndexMaintainer for testing."""
        from fdb_record_layer.indexes.count_index import MinMaxIndexMaintainer

        index = MockIndex(root_expression=MockKeyExpression("player"))
        subspace = MockSubspace(("minmax_idx",))
        metadata = MockMetaData()

        return MinMaxIndexMaintainer(
            index,
            subspace,
            metadata,
            track_max=track_max,
            value_field=value_field,
        )

    @pytest.mark.asyncio
    async def test_max_updates_on_higher_value(self):
        """Test MAX updates when new value is higher."""
        maintainer = self._create_maintainer(track_max=True)
        tr = MockTransaction()

        # First update sets initial value
        record1 = MockRecord(player="alice", score=100)
        await maintainer.update(tr, record1, (1,))

        assert maintainer.get_value(tr, "alice") == 100

        # Higher score updates
        record2 = MockRecord(player="alice", score=150)
        await maintainer.update(tr, record2, (2,))

        assert maintainer.get_value(tr, "alice") == 150

        # Lower score doesn't update
        record3 = MockRecord(player="alice", score=50)
        await maintainer.update(tr, record3, (3,))

        assert maintainer.get_value(tr, "alice") == 150

    @pytest.mark.asyncio
    async def test_min_updates_on_lower_value(self):
        """Test MIN updates when new value is lower."""
        maintainer = self._create_maintainer(track_max=False)
        tr = MockTransaction()

        # First update sets initial value
        record1 = MockRecord(player="bob", score=100)
        await maintainer.update(tr, record1, (1,))

        assert maintainer.get_value(tr, "bob") == 100

        # Lower score updates
        record2 = MockRecord(player="bob", score=50)
        await maintainer.update(tr, record2, (2,))

        assert maintainer.get_value(tr, "bob") == 50

        # Higher score doesn't update
        record3 = MockRecord(player="bob", score=75)
        await maintainer.update(tr, record3, (3,))

        assert maintainer.get_value(tr, "bob") == 50

    @pytest.mark.asyncio
    async def test_remove_does_nothing(self):
        """Test that remove doesn't change MIN_EVER/MAX_EVER."""
        maintainer = self._create_maintainer(track_max=True)
        tr = MockTransaction()

        record = MockRecord(player="charlie", score=200)
        await maintainer.update(tr, record, (1,))

        assert maintainer.get_value(tr, "charlie") == 200

        # Remove shouldn't change the value
        await maintainer.remove(tr, record, (1,))

        assert maintainer.get_value(tr, "charlie") == 200

    def test_get_value_returns_none_for_missing(self):
        """Test get_value returns None for non-existent key."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        value = maintainer.get_value(tr, "nonexistent")
        assert value is None


class TestValueIndexMaintainer:
    """Tests for ValueIndexMaintainer."""

    def _create_maintainer(self, index=None, subspace=None):
        """Create a ValueIndexMaintainer for testing."""
        from fdb_record_layer.indexes.value_index import ValueIndexMaintainer

        if index is None:
            expr = MockKeyExpression("email")
            expr._column_size = 1
            index = MockIndex(name="email_idx", root_expression=expr)
            index.record_types = ["Person"]

        subspace = subspace or MockSubspace(("value_idx",))
        metadata = MockMetaData()

        return ValueIndexMaintainer(index, subspace, metadata)

    @pytest.mark.asyncio
    async def test_update_adds_index_entry(self):
        """Test that update adds an index entry."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        record = MockRecord(email="alice@example.com", id=1)
        await maintainer.update(tr, record, (1,))

        # Check that entry was added
        assert len(tr._data) == 1

    @pytest.mark.asyncio
    async def test_remove_clears_index_entry(self):
        """Test that remove clears the index entry."""
        maintainer = self._create_maintainer()
        tr = MockTransaction()

        record = MockRecord(email="bob@example.com", id=2)
        await maintainer.update(tr, record, (2,))

        assert len(tr._data) == 1

        await maintainer.remove(tr, record, (2,))

        assert len(tr._data) == 0


class TestIndexScanRange:
    """Tests for IndexScanRange."""

    def test_equality_range(self):
        """Test creating an equality scan range."""
        from fdb_record_layer.indexes.maintainer import IndexScanRange

        scan_range = IndexScanRange(low=("value",), high=("value",))

        assert scan_range.low == ("value",)
        assert scan_range.high == ("value",)

    def test_range_with_bounds(self):
        """Test creating a range with bounds."""
        from fdb_record_layer.indexes.maintainer import IndexScanRange

        scan_range = IndexScanRange(
            low=(10,),
            high=(20,),
            low_inclusive=True,
            high_inclusive=False,
        )

        assert scan_range.low == (10,)
        assert scan_range.high == (20,)
        assert scan_range.low_inclusive is True
        assert scan_range.high_inclusive is False

    def test_open_ended_range(self):
        """Test creating an open-ended range."""
        from fdb_record_layer.indexes.maintainer import IndexScanRange

        # Low bound only
        scan_range = IndexScanRange(low=(5,), high=None)
        assert scan_range.low == (5,)
        assert scan_range.high is None

        # High bound only
        scan_range = IndexScanRange(low=None, high=(100,))
        assert scan_range.low is None
        assert scan_range.high == (100,)


class TestOnlineIndexBuilder:
    """Tests for OnlineIndexBuilder."""

    def test_build_config_defaults(self):
        """Test BuildConfig has sensible defaults."""
        from fdb_record_layer.indexes.builder import BuildConfig

        config = BuildConfig()

        assert config.batch_size == 100
        assert config.max_records == 0
        assert config.inter_batch_delay == 0.0
        assert config.max_retries == 3
        assert config.continue_on_error is True

    def test_build_progress_initial_state(self):
        """Test BuildProgress initial state."""
        from fdb_record_layer.indexes.builder import BuildProgress, BuildState

        progress = BuildProgress(index_name="test_index")

        assert progress.index_name == "test_index"
        assert progress.state == BuildState.NOT_STARTED
        assert progress.records_scanned == 0
        assert progress.records_indexed == 0
        assert progress.errors == 0
        assert progress.batches_completed == 0

    def test_build_progress_duration(self):
        """Test BuildProgress duration calculation."""
        import time

        from fdb_record_layer.indexes.builder import BuildProgress

        progress = BuildProgress(index_name="test")
        progress.start_time = time.time() - 10  # 10 seconds ago

        duration = progress.duration_seconds
        assert 9.9 < duration < 10.1

    def test_build_progress_rate(self):
        """Test BuildProgress rate calculation."""
        import time

        from fdb_record_layer.indexes.builder import BuildProgress

        progress = BuildProgress(index_name="test")
        progress.start_time = time.time() - 10  # 10 seconds ago
        progress.records_indexed = 100

        rate = progress.records_per_second
        assert 9.9 < rate < 10.1  # ~10 records/second

    def test_build_progress_to_dict(self):
        """Test BuildProgress serialization."""
        from fdb_record_layer.indexes.builder import BuildProgress, BuildState

        progress = BuildProgress(
            index_name="test_index",
            state=BuildState.COMPLETED,
            records_scanned=100,
            records_indexed=95,
            errors=5,
        )

        d = progress.to_dict()

        assert d["index_name"] == "test_index"
        assert d["state"] == "completed"
        assert d["records_scanned"] == 100
        assert d["records_indexed"] == 95
        assert d["errors"] == 5

    def test_build_state_values(self):
        """Test BuildState enum values."""
        from fdb_record_layer.indexes.builder import BuildState

        assert BuildState.NOT_STARTED.value == "not_started"
        assert BuildState.IN_PROGRESS.value == "in_progress"
        assert BuildState.COMPLETED.value == "completed"
        assert BuildState.FAILED.value == "failed"
        assert BuildState.CANCELLED.value == "cancelled"


class TestIndexStateManager:
    """Tests for IndexStateManager."""

    def _create_manager(self):
        """Create an IndexStateManager for testing."""
        from fdb_record_layer.indexes.builder import IndexStateManager
        from fdb_record_layer.metadata.index import IndexState

        # Create mock store
        mock_store = MagicMock()
        mock_store.get_index_state = MagicMock(return_value=IndexState.READABLE)
        mock_store.set_index_state = MagicMock()
        mock_store._context = MagicMock()
        mock_store._context.commit = MagicMock(return_value=None)
        mock_store._context.ensure_active = MagicMock()

        return IndexStateManager(mock_store), mock_store

    def test_get_state(self):
        """Test getting index state."""
        from fdb_record_layer.metadata.index import IndexState

        manager, mock_store = self._create_manager()
        mock_store.get_index_state.return_value = IndexState.WRITE_ONLY

        state = manager.get_state("test_index")

        assert state == IndexState.WRITE_ONLY
        mock_store.get_index_state.assert_called_once_with("test_index")

    def test_set_state(self):
        """Test setting index state."""
        from fdb_record_layer.metadata.index import IndexState

        manager, mock_store = self._create_manager()

        manager.set_state("test_index", IndexState.DISABLED)

        mock_store.set_index_state.assert_called_once_with("test_index", IndexState.DISABLED)

    def test_is_readable(self):
        """Test is_readable check."""
        from fdb_record_layer.metadata.index import IndexState

        manager, mock_store = self._create_manager()
        mock_store.get_index_state.return_value = IndexState.READABLE

        assert manager.is_readable("test_index") is True

        mock_store.get_index_state.return_value = IndexState.WRITE_ONLY
        assert manager.is_readable("test_index") is False

    def test_is_write_only(self):
        """Test is_write_only check."""
        from fdb_record_layer.metadata.index import IndexState

        manager, mock_store = self._create_manager()
        mock_store.get_index_state.return_value = IndexState.WRITE_ONLY

        assert manager.is_write_only("test_index") is True

        mock_store.get_index_state.return_value = IndexState.READABLE
        assert manager.is_write_only("test_index") is False

    def test_is_disabled(self):
        """Test is_disabled check."""
        from fdb_record_layer.metadata.index import IndexState

        manager, mock_store = self._create_manager()
        mock_store.get_index_state.return_value = IndexState.DISABLED

        assert manager.is_disabled("test_index") is True

        mock_store.get_index_state.return_value = IndexState.READABLE
        assert manager.is_disabled("test_index") is False
