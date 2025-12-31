"""Store header (DataStoreInfo) handling.

The Java Record Layer stores a header at STORE_INFO containing format
version, metadata version, and other store-level configuration.

See: RecordMetaDataProto.DataStoreInfo
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

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

    READABLE = 0
    WRITE_ONLY = 1
    DISABLED = 2


class StoreLockState(IntEnum):
    """Lock state preventing modifications."""

    UNLOCKED = 0
    READ_ONLY = 1
    LOCKED = 2


@dataclass
class StoreHeader:
    """Store header matching Java DataStoreInfo proto.

    This is stored at STORE_INFO key and contains store-level metadata.
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

    def to_bytes(self) -> bytes:
        """Serialize to bytes (simplified format, not proto-compatible yet).

        For full Java compatibility, this should use the actual protobuf
        definition from record_metadata.proto.
        """
        # Simple binary format for now
        # TODO: Use actual protobuf for full compatibility
        flags = 0
        if self.omit_unsplit_record_suffix:
            flags |= 1
        if self.cacheable:
            flags |= 2

        return struct.pack(
            "<IIIIBBBI",
            self.format_version,
            self.meta_data_version,
            self.user_version,
            flags,
            self.record_count_state,
            self.store_lock_state,
            0,  # reserved
            self.last_update_time,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> StoreHeader:
        """Deserialize from bytes."""
        if len(data) < 24:
            # Minimal header
            return cls()

        (
            format_version,
            meta_data_version,
            user_version,
            flags,
            record_count_state,
            store_lock_state,
            _reserved,
            last_update_time,
        ) = struct.unpack("<IIIIBBBI", data[:24])

        return cls(
            format_version=format_version,
            meta_data_version=meta_data_version,
            user_version=user_version,
            omit_unsplit_record_suffix=bool(flags & 1),
            cacheable=bool(flags & 2),
            record_count_state=RecordCountState(record_count_state),
            store_lock_state=StoreLockState(store_lock_state),
            last_update_time=last_update_time,
        )

    def save(self, tr: Transaction, subspace: Subspace) -> None:
        """Save header to store."""
        from fdb_record_layer.compat.keyspace import STORE_INFO_KEY

        key = subspace.pack((STORE_INFO_KEY,))
        tr.set(key, self.to_bytes())

    @classmethod
    async def load(cls, tr: Transaction, subspace: Subspace) -> StoreHeader | None:
        """Load header from store."""
        import asyncio

        from fdb_record_layer.compat.keyspace import STORE_INFO_KEY

        key = subspace.pack((STORE_INFO_KEY,))

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
