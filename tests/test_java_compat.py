"""Tests for Java Record Layer compatibility.

These tests verify that our storage format matches the Java FDB Record Layer,
enabling data interchange between Java and Python applications.
"""

import struct
from unittest.mock import MagicMock

import pytest

# ============================================================================
# Test fixtures and mocks
# ============================================================================


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

    def clear_range(self, start: bytes, end: bytes) -> None:
        keys_to_delete = [k for k in self._data if start <= k < end]
        for k in keys_to_delete:
            del self._data[k]

    def get_range(self, start: bytes, end: bytes):
        """Return items in the range."""
        result = []
        for k, v in sorted(self._data.items()):
            if start <= k < end:
                kv = MagicMock()
                kv.key = k
                kv.value = v
                result.append(kv)
        return result


class MockSubspace:
    """Mock FDB subspace for testing with tuple layer packing."""

    def __init__(self, prefix: bytes = b""):
        self._prefix = prefix

    def pack(self, key: tuple) -> bytes:
        """Pack tuple into bytes."""
        parts = [self._prefix]
        for elem in key:
            if isinstance(elem, int):
                # Simple integer encoding (not full tuple layer, but close enough)
                if 0 <= elem < 256:
                    parts.append(b"\x15" + elem.to_bytes(1, "big", signed=False))
                else:
                    parts.append(struct.pack(">q", elem))
            elif isinstance(elem, bytes):
                parts.append(b"\x01" + elem + b"\x00")
            else:
                parts.append(str(elem).encode())
        return b"".join(parts)

    def unpack(self, key: bytes) -> tuple:
        """Simplified unpack for testing."""
        # Return empty tuple if key doesn't start with prefix
        if not key.startswith(self._prefix):
            return ()
        suffix = key[len(self._prefix) :]
        # Extract integer if present
        if suffix and suffix[0:1] == b"\x15":
            return (suffix[1],)
        return ()

    def subspace(self, key: tuple) -> "MockSubspace":
        """Create a sub-subspace."""
        return MockSubspace(self.pack(key))

    def range(self) -> tuple[bytes, bytes]:
        """Return range boundaries."""
        return (self._prefix, self._prefix + b"\xff")


# ============================================================================
# Keyspace Constants Tests
# ============================================================================


class TestKeyspaceConstants:
    """Test that keyspace constants match Java."""

    def test_keyspace_enum_values(self):
        """Test all keyspace constants have correct values."""
        from fdb_record_layer.compat.keyspace import FDBRecordStoreKeyspace

        # These values must match Java exactly
        assert FDBRecordStoreKeyspace.STORE_INFO == 0
        assert FDBRecordStoreKeyspace.RECORD == 1
        assert FDBRecordStoreKeyspace.INDEX == 2
        assert FDBRecordStoreKeyspace.INDEX_SECONDARY_SPACE == 3
        assert FDBRecordStoreKeyspace.RECORD_COUNT == 4
        assert FDBRecordStoreKeyspace.INDEX_STATE_SPACE == 5
        assert FDBRecordStoreKeyspace.INDEX_RANGE_SPACE == 6
        assert FDBRecordStoreKeyspace.INDEX_UNIQUENESS_VIOLATIONS_SPACE == 7
        assert FDBRecordStoreKeyspace.RECORD_VERSION_SPACE == 8
        assert FDBRecordStoreKeyspace.INDEX_BUILD_SPACE == 9

    def test_convenience_constants(self):
        """Test convenience constants match enum values."""
        from fdb_record_layer.compat.keyspace import (
            INDEX_BUILD_SPACE_KEY,
            INDEX_KEY,
            INDEX_RANGE_SPACE_KEY,
            INDEX_SECONDARY_SPACE_KEY,
            INDEX_STATE_SPACE_KEY,
            INDEX_UNIQUENESS_VIOLATIONS_KEY,
            RECORD_COUNT_KEY,
            RECORD_KEY,
            RECORD_VERSION_SPACE_KEY,
            STORE_INFO_KEY,
        )

        assert STORE_INFO_KEY == 0
        assert RECORD_KEY == 1
        assert INDEX_KEY == 2
        assert INDEX_SECONDARY_SPACE_KEY == 3
        assert RECORD_COUNT_KEY == 4
        assert INDEX_STATE_SPACE_KEY == 5
        assert INDEX_RANGE_SPACE_KEY == 6
        assert INDEX_UNIQUENESS_VIOLATIONS_KEY == 7
        assert RECORD_VERSION_SPACE_KEY == 8
        assert INDEX_BUILD_SPACE_KEY == 9

    def test_keyspace_count(self):
        """Test we have all 10 keyspace entries."""
        from fdb_record_layer.compat.keyspace import FDBRecordStoreKeyspace

        assert len(FDBRecordStoreKeyspace) == 10


# ============================================================================
# Split Helper Tests
# ============================================================================


class TestSplitHelper:
    """Test record splitting for large records."""

    def test_split_constants(self):
        """Test split constants match Java."""
        from fdb_record_layer.compat.split import (
            RECORD_VERSION,
            SPLIT_RECORD_SIZE,
            START_SPLIT_RECORD,
            UNSPLIT_RECORD,
        )

        assert SPLIT_RECORD_SIZE == 100_000  # 100KB
        assert UNSPLIT_RECORD == 0
        assert START_SPLIT_RECORD == 1
        assert RECORD_VERSION == -1

    def test_needs_split_small_record(self):
        """Test small records don't need splitting."""
        from fdb_record_layer.compat.split import SplitHelper

        data = b"x" * 50_000  # 50KB
        assert not SplitHelper.needs_split(data)

    def test_needs_split_large_record(self):
        """Test large records need splitting."""
        from fdb_record_layer.compat.split import SplitHelper

        data = b"x" * 150_000  # 150KB
        assert SplitHelper.needs_split(data)

    def test_needs_split_boundary(self):
        """Test boundary condition at exactly 100KB."""
        from fdb_record_layer.compat.split import SPLIT_RECORD_SIZE, SplitHelper

        # Exactly at limit - no split
        data_at_limit = b"x" * SPLIT_RECORD_SIZE
        assert not SplitHelper.needs_split(data_at_limit)

        # One byte over - needs split
        data_over_limit = b"x" * (SPLIT_RECORD_SIZE + 1)
        assert SplitHelper.needs_split(data_over_limit)

    def test_save_unsplit_record_with_suffix(self):
        """Test saving small record with unsplit suffix."""
        from fdb_record_layer.compat.split import UNSPLIT_RECORD, SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)
        data = b"small record data"

        count = SplitHelper.save_possibly_split(tr, subspace, primary_key, data)

        assert count == 1
        # Key should be (primary_key, UNSPLIT_RECORD)
        expected_key = subspace.pack(primary_key + (UNSPLIT_RECORD,))
        assert expected_key in tr._data
        assert tr._data[expected_key] == data

    def test_save_unsplit_record_without_suffix(self):
        """Test saving small record without suffix (older format)."""
        from fdb_record_layer.compat.split import SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)
        data = b"small record data"

        count = SplitHelper.save_possibly_split(
            tr, subspace, primary_key, data, omit_unsplit_suffix=True
        )

        assert count == 1
        # Key should be just primary_key (no suffix)
        expected_key = subspace.pack(primary_key)
        assert expected_key in tr._data
        assert tr._data[expected_key] == data

    def test_save_split_record(self):
        """Test saving large record creates multiple chunks."""
        from fdb_record_layer.compat.split import (
            START_SPLIT_RECORD,
            SplitHelper,
        )

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)
        # Create 250KB record - should split into 3 chunks
        data = b"x" * 250_000

        count = SplitHelper.save_possibly_split(tr, subspace, primary_key, data)

        assert count == 3  # 100KB + 100KB + 50KB

        # Verify chunks exist with correct suffixes
        record_subspace = subspace.subspace(primary_key)
        for i in range(3):
            key = record_subspace.pack((START_SPLIT_RECORD + i,))
            assert key in tr._data

    def test_delete_possibly_split(self):
        """Test deleting clears all record data."""
        from fdb_record_layer.compat.split import SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)

        # Save a split record
        data = b"x" * 250_000
        SplitHelper.save_possibly_split(tr, subspace, primary_key, data)

        # Verify data exists
        assert len(tr._data) > 0

        # Delete
        SplitHelper.delete_possibly_split(tr, subspace, primary_key)

        # All chunks should be cleared (using range clear)
        record_subspace = subspace.subspace(primary_key)
        start, end = record_subspace.range()
        remaining = [k for k in tr._data if start <= k < end]
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_load_unsplit_record(self):
        """Test loading an unsplit record."""
        from fdb_record_layer.compat.split import UNSPLIT_RECORD, SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)
        data = b"test record data"

        # Store directly with unsplit suffix
        key = subspace.pack(primary_key + (UNSPLIT_RECORD,))
        tr._data[key] = data

        # Load
        result = await SplitHelper.load_possibly_split(tr, subspace, primary_key)
        assert result == data

    @pytest.mark.asyncio
    async def test_load_record_not_found(self):
        """Test loading non-existent record returns None."""
        from fdb_record_layer.compat.split import SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (999,)

        result = await SplitHelper.load_possibly_split(tr, subspace, primary_key)
        assert result is None

    def test_save_version(self):
        """Test saving record version."""
        from fdb_record_layer.compat.split import RECORD_VERSION, SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)
        version = b"\x00" * 10  # 10-byte versionstamp

        SplitHelper.save_version(tr, subspace, primary_key, version)

        # Key should be (primary_key, RECORD_VERSION)
        expected_key = subspace.pack(primary_key + (RECORD_VERSION,))
        assert expected_key in tr._data
        assert tr._data[expected_key] == version

    @pytest.mark.asyncio
    async def test_load_version(self):
        """Test loading record version."""
        from fdb_record_layer.compat.split import RECORD_VERSION, SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)
        version = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a"

        # Store version
        key = subspace.pack(primary_key + (RECORD_VERSION,))
        tr._data[key] = version

        # Load
        result = await SplitHelper.load_version(tr, subspace, primary_key)
        assert result == version

    @pytest.mark.asyncio
    async def test_load_version_not_found(self):
        """Test loading non-existent version returns None."""
        from fdb_record_layer.compat.split import SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (999,)

        result = await SplitHelper.load_version(tr, subspace, primary_key)
        assert result is None

    def test_delete_version(self):
        """Test deleting record version."""
        from fdb_record_layer.compat.split import RECORD_VERSION, SplitHelper

        tr = MockTransaction()
        subspace = MockSubspace(b"test:")
        primary_key = (123,)
        version = b"\x00" * 10

        # Store version
        key = subspace.pack(primary_key + (RECORD_VERSION,))
        tr._data[key] = version

        # Delete
        SplitHelper.delete_version(tr, subspace, primary_key)

        assert key not in tr._data


# ============================================================================
# Store Header Tests
# ============================================================================


class TestStoreHeader:
    """Test store header (DataStoreInfo) handling."""

    def test_format_version_constants(self):
        """Test format version constants match Java."""
        from fdb_record_layer.compat.store_header import FormatVersion

        assert FormatVersion.V0 == 0
        assert FormatVersion.SAVE_UNSPLIT_WITH_SUFFIX == 1
        assert FormatVersion.SAVE_VERSION_WITH_RECORD == 2
        assert FormatVersion.RECORD_COUNT_ADDED == 3
        assert FormatVersion.CURRENT == 3

    def test_record_count_state_constants(self):
        """Test RecordCountState constants."""
        from fdb_record_layer.compat.store_header import RecordCountState

        assert RecordCountState.READABLE == 1
        assert RecordCountState.WRITE_ONLY == 2
        assert RecordCountState.DISABLED == 3

    def test_store_lock_state_constants(self):
        """Test StoreLockState constants."""
        from fdb_record_layer.compat.store_header import StoreLockState

        assert StoreLockState.UNLOCKED == 1
        assert StoreLockState.READ_ONLY == 2
        assert StoreLockState.LOCKED == 3

    def test_default_header_values(self):
        """Test default header values."""
        from fdb_record_layer.compat.store_header import (
            FormatVersion,
            RecordCountState,
            StoreHeader,
            StoreLockState,
        )

        header = StoreHeader()

        assert header.format_version == FormatVersion.CURRENT
        assert header.meta_data_version == 0
        assert header.user_version == 0
        assert header.omit_unsplit_record_suffix is False
        assert header.cacheable is True
        assert header.record_count_state == RecordCountState.READABLE
        assert header.store_lock_state == StoreLockState.UNLOCKED
        assert header.last_update_time == 0
        assert header.user_fields == {}

    def test_header_to_bytes_roundtrip(self):
        """Test header serialization roundtrip."""
        from fdb_record_layer.compat.store_header import (
            FormatVersion,
            RecordCountState,
            StoreHeader,
        )

        original = StoreHeader(
            format_version=FormatVersion.CURRENT,
            meta_data_version=5,
            user_version=10,
            omit_unsplit_record_suffix=True,
            cacheable=False,
            record_count_state=RecordCountState.WRITE_ONLY,
            last_update_time=1234567890,
            user_fields={"custom": b"data"},
        )

        # Serialize and deserialize
        data = original.to_bytes()
        restored = StoreHeader.from_bytes(data)

        assert restored.format_version == original.format_version
        assert restored.meta_data_version == original.meta_data_version
        assert restored.user_version == original.user_version
        assert restored.omit_unsplit_record_suffix == original.omit_unsplit_record_suffix
        assert restored.cacheable == original.cacheable
        assert restored.record_count_state == original.record_count_state
        assert restored.last_update_time == original.last_update_time
        assert restored.user_fields == original.user_fields

    def test_header_to_proto(self):
        """Test header converts to protobuf."""
        from fdb_record_layer.compat.store_header import StoreHeader

        header = StoreHeader(
            format_version=3,
            meta_data_version=1,
            user_version=2,
        )

        proto = header.to_proto()

        assert proto.format_version == 3
        assert proto.meta_data_version == 1
        assert proto.user_version == 2

    def test_header_from_proto(self):
        """Test header created from protobuf."""
        from fdb_record_layer.compat.proto import DataStoreInfo
        from fdb_record_layer.compat.store_header import StoreHeader

        proto = DataStoreInfo()
        proto.format_version = 3
        proto.meta_data_version = 5
        proto.user_version = 10
        proto.omit_unsplit_record_suffix = True

        header = StoreHeader.from_proto(proto)

        assert header.format_version == 3
        assert header.meta_data_version == 5
        assert header.user_version == 10
        assert header.omit_unsplit_record_suffix is True

    def test_increment_meta_data_version(self):
        """Test incrementing metadata version."""
        from fdb_record_layer.compat.store_header import StoreHeader

        header = StoreHeader(meta_data_version=5)
        header.increment_meta_data_version()
        assert header.meta_data_version == 6

    def test_check_format_version(self):
        """Test format version checking."""
        from fdb_record_layer.compat.store_header import FormatVersion, StoreHeader

        header = StoreHeader(format_version=FormatVersion.SAVE_VERSION_WITH_RECORD)

        # Should support older features
        assert header.check_format_version(FormatVersion.V0) is True
        assert header.check_format_version(FormatVersion.SAVE_UNSPLIT_WITH_SUFFIX) is True
        assert header.check_format_version(FormatVersion.SAVE_VERSION_WITH_RECORD) is True

        # Should not support newer features
        assert header.check_format_version(FormatVersion.RECORD_COUNT_ADDED) is False

    def test_should_omit_unsplit_suffix(self):
        """Test unsplit suffix omission logic."""
        from fdb_record_layer.compat.store_header import FormatVersion, StoreHeader

        # Old format - should omit
        old_format = StoreHeader(format_version=FormatVersion.V0)
        assert old_format.should_omit_unsplit_suffix is True

        # New format without flag - should not omit
        new_format = StoreHeader(
            format_version=FormatVersion.CURRENT, omit_unsplit_record_suffix=False
        )
        assert new_format.should_omit_unsplit_suffix is False

        # New format with flag - should omit
        new_format_with_flag = StoreHeader(
            format_version=FormatVersion.CURRENT, omit_unsplit_record_suffix=True
        )
        assert new_format_with_flag.should_omit_unsplit_suffix is True

    def test_should_save_version_with_record(self):
        """Test version saving logic."""
        from fdb_record_layer.compat.store_header import FormatVersion, StoreHeader

        # Old format - should not save version
        old_format = StoreHeader(format_version=FormatVersion.SAVE_UNSPLIT_WITH_SUFFIX)
        assert old_format.should_save_version_with_record is False

        # New format - should save version
        new_format = StoreHeader(format_version=FormatVersion.SAVE_VERSION_WITH_RECORD)
        assert new_format.should_save_version_with_record is True


# ============================================================================
# FDBRecordVersion Tests
# ============================================================================


class TestFDBRecordVersion:
    """Test record versioning."""

    def test_versionstamp_size(self):
        """Test versionstamp is 10 bytes."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        assert FDBRecordVersion.VERSIONSTAMP_SIZE == 10

    def test_create_version(self):
        """Test creating a version."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        version = FDBRecordVersion(global_version=12345, local_version=1)

        assert version.global_version == 12345
        assert version.local_version == 1
        assert version.is_complete is True

    def test_incomplete_version(self):
        """Test creating incomplete version."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        version = FDBRecordVersion.incomplete(local_version=5)

        assert version.is_complete is False
        assert version.local_version == 5

    def test_version_to_bytes(self):
        """Test version serialization."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        version = FDBRecordVersion(global_version=0x0102030405060708, local_version=0x090A)

        data = version.to_bytes()

        assert len(data) == 10
        assert data == b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a"

    def test_version_from_bytes(self):
        """Test version deserialization."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        data = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a"
        version = FDBRecordVersion.from_bytes(data)

        assert version.global_version == 0x0102030405060708
        assert version.local_version == 0x090A

    def test_version_roundtrip(self):
        """Test version serialization roundtrip."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        original = FDBRecordVersion(global_version=9876543210, local_version=42)
        data = original.to_bytes()
        restored = FDBRecordVersion.from_bytes(data)

        assert restored == original

    def test_version_comparison(self):
        """Test version ordering."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        v1 = FDBRecordVersion(global_version=100, local_version=1)
        v2 = FDBRecordVersion(global_version=100, local_version=2)
        v3 = FDBRecordVersion(global_version=200, local_version=1)

        assert v1 < v2  # Same global, different local
        assert v2 < v3  # Different global
        assert v1 < v3

    def test_version_equality(self):
        """Test version equality."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        v1 = FDBRecordVersion(global_version=100, local_version=1)
        v2 = FDBRecordVersion(global_version=100, local_version=1)
        v3 = FDBRecordVersion(global_version=100, local_version=2)

        assert v1 == v2
        assert v1 != v3

    def test_version_invalid_bytes_length(self):
        """Test version rejects invalid byte length."""
        from fdb_record_layer.compat.java_store import FDBRecordVersion

        with pytest.raises(ValueError, match="Expected 10 bytes"):
            FDBRecordVersion.from_bytes(b"\x01\x02\x03")


# ============================================================================
# Metadata Store Tests
# ============================================================================


class TestMetadataStore:
    """Test Java-compatible metadata storage."""

    def test_key_expression_to_proto_field(self):
        """Test converting field expression to proto."""
        from fdb_record_layer.compat.metadata_store import key_expression_to_proto
        from fdb_record_layer.expressions.field import FieldKeyExpression

        expr = FieldKeyExpression("user_id")
        proto = key_expression_to_proto(expr)

        assert proto.HasField("field")
        assert proto.field.field_name == "user_id"

    def test_key_expression_to_proto_concatenate(self):
        """Test converting concatenate expression to proto."""
        from fdb_record_layer.compat.metadata_store import key_expression_to_proto
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression
        from fdb_record_layer.expressions.field import FieldKeyExpression

        expr = ConcatenateKeyExpression(
            [
                FieldKeyExpression("first"),
                FieldKeyExpression("second"),
            ]
        )
        proto = key_expression_to_proto(expr)

        assert proto.HasField("then")
        assert len(proto.then.children) == 2
        assert proto.then.children[0].field.field_name == "first"
        assert proto.then.children[1].field.field_name == "second"

    def test_proto_to_key_expression_field(self):
        """Test converting proto to field expression."""
        from fdb_record_layer.compat.metadata_store import proto_to_key_expression
        from fdb_record_layer.compat.proto import FanType, Field, KeyExpression
        from fdb_record_layer.expressions.field import FieldKeyExpression

        proto = KeyExpression()
        proto.field.CopyFrom(Field(field_name="test_field", fan_type=FanType.SCALAR))

        expr = proto_to_key_expression(proto)

        assert isinstance(expr, FieldKeyExpression)
        assert expr.field_name == "test_field"

    def test_proto_to_key_expression_then(self):
        """Test converting proto then to concatenate expression."""
        from fdb_record_layer.compat.metadata_store import proto_to_key_expression
        from fdb_record_layer.compat.proto import FanType, Field, KeyExpression
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression

        # Build proto
        child1 = KeyExpression()
        child1.field.CopyFrom(Field(field_name="a", fan_type=FanType.SCALAR))

        child2 = KeyExpression()
        child2.field.CopyFrom(Field(field_name="b", fan_type=FanType.SCALAR))

        proto = KeyExpression()
        proto.then.children.append(child1)
        proto.then.children.append(child2)

        expr = proto_to_key_expression(proto)

        assert isinstance(expr, ConcatenateKeyExpression)
        assert len(expr.children) == 2

    def test_index_type_conversion(self):
        """Test index type string conversion."""
        from fdb_record_layer.compat.metadata_store import (
            index_type_to_string,
            string_to_index_type,
        )
        from fdb_record_layer.metadata.index import IndexType

        # Test all types roundtrip
        for idx_type in IndexType:
            string = index_type_to_string(idx_type)
            restored = string_to_index_type(string)
            assert restored == idx_type

    def test_assign_subspace_keys(self):
        """Test assigning integer subspace keys to indexes."""
        from fdb_record_layer.compat.metadata_store import assign_subspace_keys
        from fdb_record_layer.expressions.field import FieldKeyExpression
        from fdb_record_layer.metadata.index import Index, IndexType
        from fdb_record_layer.metadata.record_metadata import RecordMetaData

        # Create metadata with indexes
        metadata = RecordMetaData(
            version=1,
            record_types={},
            indexes={
                "idx1": Index(
                    name="idx1",
                    root_expression=FieldKeyExpression("field1"),
                    index_type=IndexType.VALUE,
                    record_types=["TestRecord"],
                ),
                "idx2": Index(
                    name="idx2",
                    root_expression=FieldKeyExpression("field2"),
                    index_type=IndexType.VALUE,
                    record_types=["TestRecord"],
                ),
            },
        )

        # Assign keys
        assign_subspace_keys(metadata)

        # Verify keys were assigned
        keys = {idx.subspace_key for idx in metadata.indexes.values()}
        assert keys == {0, 1}

    def test_metadata_to_proto_roundtrip(self):
        """Test metadata serialization roundtrip."""
        from fdb_record_layer.compat.metadata_store import JavaCompatibleMetaDataStore
        from fdb_record_layer.expressions.field import FieldKeyExpression
        from fdb_record_layer.metadata.index import Index, IndexType
        from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType

        subspace = MockSubspace(b"meta:")
        store = JavaCompatibleMetaDataStore(subspace)

        # Create metadata (descriptor can be None for basic testing)
        metadata = RecordMetaData(
            version=5,
            record_types={
                "Person": RecordType(
                    name="Person",
                    descriptor=None,  # type: ignore
                    primary_key=FieldKeyExpression("id"),
                ),
            },
            indexes={
                "name_idx": Index(
                    name="name_idx",
                    root_expression=FieldKeyExpression("name"),
                    index_type=IndexType.VALUE,
                    record_types=["Person"],
                ),
            },
        )

        # Convert to proto and back
        proto = store.metadata_to_proto(metadata)
        restored = store.proto_to_metadata(proto)

        assert restored.version == metadata.version
        assert "Person" in restored.record_types
        assert "name_idx" in restored.indexes
        assert restored.indexes["name_idx"].name == "name_idx"


# ============================================================================
# Proto Module Tests
# ============================================================================


class TestProtoModule:
    """Test protobuf definitions are correctly imported."""

    def test_key_expression_imports(self):
        """Test key expression protos are available."""
        from fdb_record_layer.compat.proto import (
            Empty,
            FanType,
            Field,
            KeyExpression,
            Nesting,
            Then,
        )

        # Just verify they exist and are classes
        assert KeyExpression is not None
        assert Then is not None
        assert Nesting is not None
        assert Field is not None
        assert Empty is not None
        assert FanType is not None

    def test_store_header_imports(self):
        """Test store header protos are available."""
        from fdb_record_layer.compat.proto import (
            DataStoreInfo,
            RecordCountState,
            StoreLockState,
        )

        assert DataStoreInfo is not None
        assert RecordCountState is not None
        assert StoreLockState is not None

    def test_index_imports(self):
        """Test index protos are available."""
        from fdb_record_layer.compat.proto import FormerIndex, Index, IndexType

        assert Index is not None
        assert IndexType is not None
        assert FormerIndex is not None

    def test_metadata_imports(self):
        """Test metadata protos are available."""
        from fdb_record_layer.compat.proto import MetaData, RecordType

        assert MetaData is not None
        assert RecordType is not None

    def test_fan_type_values(self):
        """Test FanType enum values."""
        from fdb_record_layer.compat.proto import FanType

        # These values must match Java's FanType enum
        # Note: 0 is FAN_TYPE_UNSPECIFIED (default proto3 behavior)
        assert FanType.SCALAR == 1
        assert FanType.FAN_OUT == 2
        assert FanType.CONCATENATE == 3


# ============================================================================
# Compat Module Exports Tests
# ============================================================================


class TestCompatModuleExports:
    """Test that compat module exports all required classes."""

    def test_keyspace_exports(self):
        """Test keyspace exports."""
        from fdb_record_layer.compat import (
            INDEX_KEY,
            RECORD_KEY,
            STORE_INFO_KEY,
            FDBRecordStoreKeyspace,
        )

        assert FDBRecordStoreKeyspace is not None
        assert STORE_INFO_KEY == 0
        assert RECORD_KEY == 1
        assert INDEX_KEY == 2

    def test_split_exports(self):
        """Test split exports."""
        from fdb_record_layer.compat import (
            RECORD_VERSION,
            SPLIT_RECORD_SIZE,
            START_SPLIT_RECORD,
            UNSPLIT_RECORD,
            SplitHelper,
        )

        assert SplitHelper is not None
        assert SPLIT_RECORD_SIZE == 100_000
        assert UNSPLIT_RECORD == 0
        assert START_SPLIT_RECORD == 1
        assert RECORD_VERSION == -1

    def test_store_header_exports(self):
        """Test store header exports."""
        from fdb_record_layer.compat import (
            FormatVersion,
            RecordCountState,
            StoreHeader,
            StoreLockState,
        )

        assert StoreHeader is not None
        assert FormatVersion is not None
        assert RecordCountState is not None
        assert StoreLockState is not None

    def test_metadata_store_exports(self):
        """Test metadata store exports."""
        from fdb_record_layer.compat import (
            JavaCompatibleMetaDataStore,
            assign_subspace_keys,
            key_expression_to_proto,
            proto_to_key_expression,
        )

        assert JavaCompatibleMetaDataStore is not None
        assert key_expression_to_proto is not None
        assert proto_to_key_expression is not None
        assert assign_subspace_keys is not None


# ============================================================================
# Integer Subspace Key Tests
# ============================================================================


class TestIntegerSubspaceKeys:
    """Test that indexes use integer subspace keys (not string names)."""

    def test_subspace_key_is_integer(self):
        """Test subspace keys are assigned as integers."""
        from fdb_record_layer.compat.metadata_store import assign_subspace_keys
        from fdb_record_layer.expressions.field import FieldKeyExpression
        from fdb_record_layer.metadata.index import Index, IndexType
        from fdb_record_layer.metadata.record_metadata import RecordMetaData

        metadata = RecordMetaData(
            version=1,
            record_types={},
            indexes={
                "my_string_named_index": Index(
                    name="my_string_named_index",
                    root_expression=FieldKeyExpression("field"),
                    index_type=IndexType.VALUE,
                    record_types=["Record"],
                ),
            },
        )

        assign_subspace_keys(metadata)

        index = metadata.indexes["my_string_named_index"]
        assert isinstance(index.subspace_key, int)
        assert index.subspace_key == 0

    def test_subspace_key_packed_as_big_endian_long(self):
        """Test subspace keys are packed as big-endian 8-byte integers."""
        from fdb_record_layer.compat.metadata_store import JavaCompatibleMetaDataStore
        from fdb_record_layer.expressions.field import FieldKeyExpression
        from fdb_record_layer.metadata.index import Index, IndexType
        from fdb_record_layer.metadata.record_metadata import RecordMetaData

        subspace = MockSubspace(b"test:")
        store = JavaCompatibleMetaDataStore(subspace)

        metadata = RecordMetaData(
            version=1,
            record_types={},
            indexes={
                "test_idx": Index(
                    name="test_idx",
                    root_expression=FieldKeyExpression("field"),
                    index_type=IndexType.VALUE,
                    record_types=["Record"],
                ),
            },
        )

        proto = store.metadata_to_proto(metadata)

        # Check the subspace_key is packed as big-endian long
        idx_proto = proto.indexes[0]
        assert len(idx_proto.subspace_key) == 8
        key_value = struct.unpack(">q", idx_proto.subspace_key)[0]
        assert key_value == 0

    def test_existing_subspace_key_preserved(self):
        """Test existing subspace keys are preserved."""
        from fdb_record_layer.compat.metadata_store import assign_subspace_keys
        from fdb_record_layer.expressions.field import FieldKeyExpression
        from fdb_record_layer.metadata.index import Index, IndexType
        from fdb_record_layer.metadata.record_metadata import RecordMetaData

        index = Index(
            name="existing_idx",
            root_expression=FieldKeyExpression("field"),
            index_type=IndexType.VALUE,
            record_types=["Record"],
        )
        index.subspace_key = 42  # Pre-assigned key

        metadata = RecordMetaData(
            version=1,
            record_types={},
            indexes={"existing_idx": index},
        )

        assign_subspace_keys(metadata)

        # Key should be preserved
        assert metadata.indexes["existing_idx"].subspace_key == 42
