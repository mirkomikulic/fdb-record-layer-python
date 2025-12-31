"""Store header (DataStoreInfo) handling.

The Java Record Layer stores a header at STORE_INFO containing format
version, metadata version, and other store-level configuration.

This uses the actual protobuf definition for full Java compatibility.

See: RecordMetaDataProto.DataStoreInfo
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from fdb_record_layer.compat.proto import (
    DataStoreInfo as DataStoreInfoProto,
    RecordCountState as RecordCountStateProto,
    StoreLockState as StoreLockStateProto,
)

if TYPE_CHECKING:
    from fdb import Transaction
    from fdb.subspace_impl import Subspace


class FormatVersion(IntEnum):
    """Format version constants matching Java.

    These control various storage format behaviors.
    """

    # Initial version
    V0 = 0

    # Added unsplit record suffix
    SAVE_UNSPLIT_WITH_SUFFIX = 1

    # Save version with record (inline)
    SAVE_VERSION_WITH_RECORD = 2

    # Record count key added
    RECORD_COUNT_ADDED = 3

    # Current recommended version
    CURRENT = 3


class RecordCountState(IntEnum):
    """State of record count tracking."""

    READABLE = 1
    WRITE_ONLY = 2
    DISABLED = 3


class StoreLockState(IntEnum):
    """Lock state preventing modifications."""

    UNLOCKED = 1
    READ_ONLY = 2
    LOCKED = 3


@dataclass
class StoreHeader:
    """Store header matching Java DataStoreInfo proto.

    This is stored at STORE_INFO key and contains store-level metadata.
    Uses proper protobuf serialization for Java compatibility.
    """

    # Format version (controls storage format behaviors)
    format_version: int = FormatVersion.CURRENT

    # Metadata version (monotonically increasing)
    meta_data_version: int = 0

    # User-controlled version for application logic
    user_version: int = 0

    # Whether to omit suffix for unsplit records
    omit_unsplit_record_suffix: bool = False

    # Whether store info is cacheable
    cacheable: bool = True

    # Record count state
    record_count_state: RecordCountState = RecordCountState.READABLE

    # Store lock state
    store_lock_state: StoreLockState = StoreLockState.UNLOCKED

    # Last update timestamp (milliseconds)
    last_update_time: int = 0

    # User-defined fields (key-value pairs)
    user_fields: dict[str, bytes] = field(default_factory=dict)

    def to_proto(self) -> DataStoreInfoProto:
        """Convert to protobuf message."""
        proto = DataStoreInfoProto()
        proto.format_version = self.format_version
        proto.meta_data_version = self.meta_data_version
        proto.user_version = self.user_version
        proto.omit_unsplit_record_suffix = self.omit_unsplit_record_suffix
        proto.cacheable = self.cacheable
        proto.last_update_time = self.last_update_time

        if self.record_count_state:
            proto.record_count_state = self.record_count_state

        if self.store_lock_state:
            proto.store_lock_state = self.store_lock_state

        for key, value in self.user_fields.items():
            entry = proto.user_field.add()
            entry.key = key
            entry.value = value

        return proto

    @classmethod
    def from_proto(cls, proto: DataStoreInfoProto) -> StoreHeader:
        """Create from protobuf message."""
        user_fields = {}
        for entry in proto.user_field:
            user_fields[entry.key] = entry.value

        record_count_state = RecordCountState.READABLE
        if proto.record_count_state:
            record_count_state = RecordCountState(proto.record_count_state)

        store_lock_state = StoreLockState.UNLOCKED
        if proto.store_lock_state:
            store_lock_state = StoreLockState(proto.store_lock_state)

        return cls(
            format_version=proto.format_version,
            meta_data_version=proto.meta_data_version,
            user_version=proto.user_version,
            omit_unsplit_record_suffix=proto.omit_unsplit_record_suffix,
            cacheable=proto.cacheable,
            record_count_state=record_count_state,
            store_lock_state=store_lock_state,
            last_update_time=proto.last_update_time,
            user_fields=user_fields,
        )

    def to_bytes(self) -> bytes:
        """Serialize to bytes using protobuf (Java compatible)."""
        return self.to_proto().SerializeToString()

    @classmethod
    def from_bytes(cls, data: bytes) -> StoreHeader:
        """Deserialize from bytes using protobuf."""
        proto = DataStoreInfoProto()
        proto.ParseFromString(data)
        return cls.from_proto(proto)

    def save(self, tr: Transaction, subspace: Subspace) -> None:
        """Save header to store."""
        from fdb_record_layer.compat.keyspace import STORE_INFO_KEY

        key = subspace.pack((int(STORE_INFO_KEY),))
        tr.set(key, self.to_bytes())

    @classmethod
    async def load(cls, tr: Transaction, subspace: Subspace) -> StoreHeader | None:
        """Load header from store."""
        import asyncio

        from fdb_record_layer.compat.keyspace import STORE_INFO_KEY

        key = subspace.pack((int(STORE_INFO_KEY),))

        loop = asyncio.get_event_loop()
        value = await loop.run_in_executor(None, lambda: tr[key])

        if value.present():
            return cls.from_bytes(bytes(value))
        return None

    def increment_meta_data_version(self) -> None:
        """Increment metadata version (called on schema changes)."""
        self.meta_data_version += 1

    def check_format_version(self, required: FormatVersion) -> bool:
        """Check if format version supports a feature."""
        return self.format_version >= required

    @property
    def should_omit_unsplit_suffix(self) -> bool:
        """Whether to omit suffix for unsplit records."""
        return (
            self.omit_unsplit_record_suffix
            or self.format_version < FormatVersion.SAVE_UNSPLIT_WITH_SUFFIX
        )

    @property
    def should_save_version_with_record(self) -> bool:
        """Whether to save version inline with record."""
        return self.format_version >= FormatVersion.SAVE_VERSION_WITH_RECORD
