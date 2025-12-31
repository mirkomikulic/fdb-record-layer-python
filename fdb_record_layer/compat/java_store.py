"""Java-compatible FDB Record Store.

This module provides a record store implementation that uses the same
storage format as the Java FDB Record Layer, enabling data interchange
between Java and Python applications.

Key differences from the standard FDBRecordStore:
- Uses integer keyspace constants instead of string names
- Supports record splitting for large records (>100KB)
- Stores header with format version at STORE_INFO
- Supports record versioning
- Uses Java-compatible index key format
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from fdb_record_layer.compat.keyspace import (
    INDEX_BUILD_SPACE_KEY,
    INDEX_KEY,
    INDEX_STATE_SPACE_KEY,
    RECORD_COUNT_KEY,
    RECORD_KEY,
)
from fdb_record_layer.compat.split import SplitHelper
from fdb_record_layer.compat.store_header import FormatVersion, StoreHeader
from fdb_record_layer.core.exceptions import (
    InvalidPrimaryKeyException,
    RecordTypeNotFoundException,
)
from fdb_record_layer.core.record import FDBStoredRecord
from fdb_record_layer.cursors.base import RecordCursor
from fdb_record_layer.indexes.maintainer import IndexMaintainer, IndexScanRange
from fdb_record_layer.indexes.value_index import ValueIndexMaintainer
from fdb_record_layer.serialization.proto_serializer import get_default_serializer
from fdb_record_layer.serialization.serializer import RecordSerializer

if TYPE_CHECKING:
    from fdb import Transaction
    from fdb.subspace_impl import Subspace
    from google.protobuf.message import Message

    from fdb_record_layer.core.context import FDBRecordContext
    from fdb_record_layer.metadata.record_metadata import RecordMetaData

_logger = logging.getLogger("fdb_record_layer.compat.java_store")

M = TypeVar("M", bound="Message")


class FDBRecordVersion:
    """Record version using FDB versionstamp.

    A versionstamp is a 10-byte value that is globally ordered by
    commit time, enabling optimistic concurrency control.
    """

    # Versionstamp size in bytes
    VERSIONSTAMP_SIZE = 10

    # Incomplete marker (before commit)
    INCOMPLETE_MARKER = b"\xff" * 10

    def __init__(self, global_version: int = 0, local_version: int = 0):
        """Create a record version.

        Args:
            global_version: 8-byte transaction version
            local_version: 2-byte ordering within transaction
        """
        self.global_version = global_version
        self.local_version = local_version

    @property
    def is_complete(self) -> bool:
        """Whether the version has been committed."""
        return self.global_version != 0xFFFFFFFFFFFFFFFF

    def to_bytes(self) -> bytes:
        """Serialize to 10 bytes."""
        return self.global_version.to_bytes(8, "big") + self.local_version.to_bytes(2, "big")

    @classmethod
    def from_bytes(cls, data: bytes) -> FDBRecordVersion:
        """Deserialize from 10 bytes."""
        if len(data) != cls.VERSIONSTAMP_SIZE:
            raise ValueError(f"Expected {cls.VERSIONSTAMP_SIZE} bytes, got {len(data)}")

        global_version = int.from_bytes(data[:8], "big")
        local_version = int.from_bytes(data[8:], "big")
        return cls(global_version, local_version)

    @classmethod
    def incomplete(cls, local_version: int = 0) -> FDBRecordVersion:
        """Create an incomplete version (to be filled at commit)."""
        return cls(0xFFFFFFFFFFFFFFFF, local_version)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FDBRecordVersion):
            return False
        return (
            self.global_version == other.global_version
            and self.local_version == other.local_version
        )

    def __lt__(self, other: FDBRecordVersion) -> bool:
        if self.global_version != other.global_version:
            return self.global_version < other.global_version
        return self.local_version < other.local_version

    def __repr__(self) -> str:
        if not self.is_complete:
            return f"FDBRecordVersion(incomplete, local={self.local_version})"
        return f"FDBRecordVersion({self.global_version}, {self.local_version})"


class JavaCompatibleStore(Generic[M]):
    """Java-compatible FDB Record Store.

    This store uses the same storage format as the Java FDB Record Layer,
    enabling data interchange between Java and Python applications.

    Key format:
    - Records: (subspace, 1, primary_key..., suffix)
    - Indexes: (subspace, 2, index_subspace_key, values..., pk...)
    - Header: (subspace, 0) -> StoreHeader

    Example:
        >>> store = JavaCompatibleStore(ctx, subspace, metadata)
        >>> await store.save_record(person)
        >>> record = await store.load_record("Person", (person_id,))
    """

    def __init__(
        self,
        context: FDBRecordContext,
        subspace: Subspace,
        meta_data: RecordMetaData,
        serializer: RecordSerializer | None = None,
        format_version: FormatVersion = FormatVersion.CURRENT,
    ) -> None:
        """Initialize the Java-compatible record store.

        Args:
            context: The record context with transaction.
            subspace: The subspace for this store's data.
            meta_data: The record metadata defining types and indexes.
            serializer: Optional custom serializer. Defaults to protobuf.
            format_version: Storage format version (default: current).
        """
        self._context = context
        self._subspace = subspace
        self._meta_data = meta_data
        self._serializer = serializer or get_default_serializer()
        self._format_version = format_version

        # Initialize subspaces using Java constants
        self._records_subspace = subspace.subspace((RECORD_KEY,))
        self._index_subspace = subspace.subspace((INDEX_KEY,))
        self._index_state_subspace = subspace.subspace((INDEX_STATE_SPACE_KEY,))
        self._index_build_subspace = subspace.subspace((INDEX_BUILD_SPACE_KEY,))
        self._record_count_subspace = subspace.subspace((RECORD_COUNT_KEY,))

        # Store header (loaded/created on first access)
        self._header: StoreHeader | None = None

        # Index maintainers
        self._index_maintainers: dict[str, IndexMaintainer] = {}
        self._init_index_maintainers()

    def _init_index_maintainers(self) -> None:
        """Initialize maintainers for all indexes."""
        for index in self._meta_data.indexes.values():
            maintainer = self._create_maintainer(index)
            self._index_maintainers[index.name] = maintainer

    def _create_maintainer(self, index: Any) -> IndexMaintainer:
        """Create the appropriate maintainer for an index type."""
        from fdb_record_layer.indexes.registry import get_default_registry

        # Use index subspace key (integer) for Java compatibility
        # Fall back to index name if no subspace_key defined
        subspace_key = getattr(index, "subspace_key", None) or index.name
        index_subspace = self._index_subspace.subspace((subspace_key,))

        registry = get_default_registry()

        try:
            return registry.create_maintainer(index, index_subspace, self._meta_data)
        except ValueError:
            return ValueIndexMaintainer(index, index_subspace, self._meta_data)

    @property
    def context(self) -> FDBRecordContext:
        """Get the record context."""
        return self._context

    @property
    def transaction(self) -> Transaction:
        """Get the underlying FDB transaction."""
        return self._context.transaction

    @property
    def meta_data(self) -> RecordMetaData:
        """Get the record metadata."""
        return self._meta_data

    async def get_header(self) -> StoreHeader:
        """Get the store header, loading or creating if needed."""
        if self._header is None:
            self._header = await StoreHeader.load(self.transaction, self._subspace)
            if self._header is None:
                self._header = StoreHeader(format_version=self._format_version)
                self._header.save(self.transaction, self._subspace)
        return self._header

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def save_record(
        self,
        record: M,
        record_type_name: str | None = None,
        version: FDBRecordVersion | None = None,
    ) -> FDBStoredRecord[M]:
        """Save a record with Java-compatible format.

        Args:
            record: The protobuf message to save.
            record_type_name: Optional explicit record type name.
            version: Optional record version for optimistic locking.

        Returns:
            The stored record wrapper with version info.
        """
        start_time = time.perf_counter()
        self._context.ensure_active()

        # Get header for format settings
        header = await self.get_header()

        # Determine record type
        if record_type_name is None:
            record_type_name = record.DESCRIPTOR.name

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Compute primary key
        primary_key_values = record_type.primary_key.evaluate(record)
        if len(primary_key_values) != 1:
            raise InvalidPrimaryKeyException(
                f"Primary key must evaluate to exactly one value, got {len(primary_key_values)}"
            )
        primary_key = primary_key_values[0]

        # Load existing record for index cleanup
        old_record = await self._load_raw_record(primary_key)
        is_update = old_record is not None

        # Serialize record
        record_bytes = self._serializer.serialize(record)

        # Save using split helper (handles large records)
        SplitHelper.save_possibly_split(
            self.transaction,
            self._records_subspace,
            primary_key,
            record_bytes,
            omit_unsplit_suffix=header.should_omit_unsplit_suffix,
        )

        # Save version if provided and format supports it
        if version and header.should_save_version_with_record:
            SplitHelper.save_version(
                self.transaction,
                self._records_subspace,
                primary_key,
                version.to_bytes(),
            )

        # Update indexes
        await self._update_indexes(record_type, primary_key, old_record, record)

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Record saved (Java format)",
            extra={
                "record_type": record_type_name,
                "primary_key": str(primary_key),
                "is_update": is_update,
                "size_bytes": len(record_bytes),
                "duration_ms": round(duration_ms, 2),
            },
        )

        return FDBStoredRecord(
            primary_key=primary_key,
            record=record,
            record_type=record_type,
        )

    async def load_record(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> FDBStoredRecord[M] | None:
        """Load a record by primary key.

        Args:
            record_type_name: The record type name.
            primary_key: The primary key tuple.

        Returns:
            The stored record, or None if not found.
        """
        start_time = time.perf_counter()
        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Load using split helper (handles split records)
        record_bytes = await SplitHelper.load_possibly_split(
            self.transaction,
            self._records_subspace,
            primary_key,
        )

        if record_bytes is None:
            duration_ms = (time.perf_counter() - start_time) * 1000
            _logger.debug(
                "Record not found (Java format)",
                extra={
                    "record_type": record_type_name,
                    "primary_key": str(primary_key),
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return None

        # Deserialize
        record = self._serializer.deserialize(record_bytes, record_type)  # type: ignore[arg-type]

        # Load version if available
        version_bytes = await SplitHelper.load_version(
            self.transaction,
            self._records_subspace,
            primary_key,
        )
        version = FDBRecordVersion.from_bytes(version_bytes) if version_bytes else None

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Record loaded (Java format)",
            extra={
                "record_type": record_type_name,
                "primary_key": str(primary_key),
                "size_bytes": len(record_bytes),
                "has_version": version is not None,
                "duration_ms": round(duration_ms, 2),
            },
        )

        stored: FDBStoredRecord[M] = FDBStoredRecord(
            primary_key=primary_key,
            record=record,  # type: ignore[arg-type]
            record_type=record_type,
        )
        # Attach version as attribute
        stored._version = version  # type: ignore[attr-defined]
        return stored

    async def delete_record(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> bool:
        """Delete a record by primary key.

        Args:
            record_type_name: The record type name.
            primary_key: The primary key tuple.

        Returns:
            True if a record was deleted, False if not found.
        """
        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Load existing record for index cleanup
        old_record = await self._load_raw_record(primary_key)

        if old_record is None:
            return False

        # Remove from indexes
        await self._remove_from_indexes(record_type, primary_key, old_record)

        # Delete record (handles split records)
        SplitHelper.delete_possibly_split(
            self.transaction,
            self._records_subspace,
            primary_key,
        )

        # Delete version
        SplitHelper.delete_version(
            self.transaction,
            self._records_subspace,
            primary_key,
        )

        return True

    async def record_exists(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> bool:
        """Check if a record exists.

        Args:
            record_type_name: The record type name.
            primary_key: The primary key tuple.

        Returns:
            True if the record exists.
        """
        # Try to load the record
        record = await self.load_record(record_type_name, primary_key)
        return record is not None

    # =========================================================================
    # Index Operations
    # =========================================================================

    async def scan_index(
        self,
        index_name: str,
        scan_range: IndexScanRange | None = None,
        limit: int = 0,
        continuation: bytes | None = None,
    ) -> RecordCursor:
        """Scan an index and return matching records.

        Args:
            index_name: Name of the index to scan.
            scan_range: Optional range to scan.
            limit: Maximum records to return (0 = unlimited).
            continuation: Optional continuation from previous scan.

        Returns:
            Cursor over matching records.
        """
        self._context.ensure_active()

        if index_name not in self._index_maintainers:
            raise ValueError(f"Unknown index: {index_name}")

        maintainer = self._index_maintainers[index_name]

        async def load_record(rt_name: str, pk: tuple) -> FDBStoredRecord | None:
            return await self.load_record(rt_name, pk)

        return await maintainer.scan(
            self.transaction,
            scan_range,
            continuation,
            limit if limit > 0 else 10000,
            load_record,  # type: ignore[arg-type]
        )

    # =========================================================================
    # Internal Methods
    # =========================================================================

    async def _load_raw_record(self, primary_key: tuple[Any, ...]) -> M | None:
        """Load raw record bytes and deserialize."""
        record_bytes = await SplitHelper.load_possibly_split(
            self.transaction,
            self._records_subspace,
            primary_key,
        )

        if record_bytes is None:
            return None

        # Try to determine record type from metadata
        # For now, use first registered type
        for record_type in self._meta_data.record_types.values():
            try:
                return self._serializer.deserialize(record_bytes, record_type)  # type: ignore[return-value, arg-type]
            except Exception:
                continue

        return None

    async def _update_indexes(
        self,
        record_type: Any,
        primary_key: tuple[Any, ...],
        old_record: M | None,
        new_record: M,
    ) -> None:
        """Update all applicable indexes."""
        for index in self._meta_data.indexes.values():
            if not index.record_types or record_type.name not in index.record_types:
                continue

            maintainer = self._index_maintainers[index.name]

            # Remove old entries
            if old_record is not None:
                await maintainer.remove(self.transaction, old_record, primary_key)

            # Add new entries
            await maintainer.update(self.transaction, new_record, primary_key)

    async def _remove_from_indexes(
        self,
        record_type: Any,
        primary_key: tuple[Any, ...],
        record: M,
    ) -> None:
        """Remove record from all applicable indexes."""
        for index in self._meta_data.indexes.values():
            if not index.record_types or record_type.name not in index.record_types:
                continue

            maintainer = self._index_maintainers[index.name]
            await maintainer.remove(self.transaction, record, primary_key)
