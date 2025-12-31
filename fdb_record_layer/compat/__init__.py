"""Java Record Layer compatibility module.

This module provides storage format compatibility with the Java
FoundationDB Record Layer, enabling data interchange between
Java and Python applications.

Key components:
- KeyspaceLayout: Java-compatible subspace constants
- RecordSplitter: Handle large records (>100KB)
- StoreHeader: DataStoreInfo proto handling
- JavaCompatibleStore: Drop-in replacement for FDBRecordStore
- JavaCompatibleMetaDataStore: Protobuf-based metadata storage
"""

from fdb_record_layer.compat.keyspace import (
    FDBRecordStoreKeyspace,
    STORE_INFO_KEY,
    RECORD_KEY,
    INDEX_KEY,
    INDEX_SECONDARY_SPACE_KEY,
    RECORD_COUNT_KEY,
    INDEX_STATE_SPACE_KEY,
    INDEX_RANGE_SPACE_KEY,
    INDEX_UNIQUENESS_VIOLATIONS_KEY,
    RECORD_VERSION_SPACE_KEY,
    INDEX_BUILD_SPACE_KEY,
)

from fdb_record_layer.compat.split import (
    SplitHelper,
    SPLIT_RECORD_SIZE,
    UNSPLIT_RECORD,
    START_SPLIT_RECORD,
    RECORD_VERSION,
)

from fdb_record_layer.compat.store_header import (
    StoreHeader,
    FormatVersion,
    RecordCountState,
    StoreLockState,
)

from fdb_record_layer.compat.metadata_store import (
    JavaCompatibleMetaDataStore,
    key_expression_to_proto,
    proto_to_key_expression,
    assign_subspace_keys,
)

__all__ = [
    # Keyspace
    "FDBRecordStoreKeyspace",
    "STORE_INFO_KEY",
    "RECORD_KEY",
    "INDEX_KEY",
    "INDEX_SECONDARY_SPACE_KEY",
    "RECORD_COUNT_KEY",
    "INDEX_STATE_SPACE_KEY",
    "INDEX_RANGE_SPACE_KEY",
    "INDEX_UNIQUENESS_VIOLATIONS_KEY",
    "RECORD_VERSION_SPACE_KEY",
    "INDEX_BUILD_SPACE_KEY",
    # Split
    "SplitHelper",
    "SPLIT_RECORD_SIZE",
    "UNSPLIT_RECORD",
    "START_SPLIT_RECORD",
    "RECORD_VERSION",
    # Store Header
    "StoreHeader",
    "FormatVersion",
    "RecordCountState",
    "StoreLockState",
    # Metadata Store
    "JavaCompatibleMetaDataStore",
    "key_expression_to_proto",
    "proto_to_key_expression",
    "assign_subspace_keys",
]
