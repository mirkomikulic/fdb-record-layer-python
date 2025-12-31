"""Java-compatible keyspace constants.

These constants match the exact values used by the Java FDB Record Layer,
enabling data interchange between Java and Python applications.

See: com.apple.foundationdb.record.provider.foundationdb.FDBRecordStoreKeyspace
"""

from enum import IntEnum


class FDBRecordStoreKeyspace(IntEnum):
    """Keyspace constants matching Java FDBRecordStoreKeyspace.

    These are the first tuple element within a record store's subspace,
    used to separate different types of data.
    """

    # Store header containing format version, metadata version, etc.
    STORE_INFO = 0

    # Record data storage
    RECORD = 1

    # Index entries
    INDEX = 2

    # Secondary index space (for index-specific metadata)
    INDEX_SECONDARY_SPACE = 3

    # Record count tracking
    RECORD_COUNT = 4

    # Index state (readable, write-only, disabled)
    INDEX_STATE_SPACE = 5

    # Index build range tracking
    INDEX_RANGE_SPACE = 6

    # Uniqueness violation tracking for unique indexes
    INDEX_UNIQUENESS_VIOLATIONS_SPACE = 7

    # Record version storage (legacy, before inline versions)
    RECORD_VERSION_SPACE = 8

    # Online index build progress
    INDEX_BUILD_SPACE = 9


# Convenience constants matching Java static fields
STORE_INFO_KEY = FDBRecordStoreKeyspace.STORE_INFO
RECORD_KEY = FDBRecordStoreKeyspace.RECORD
INDEX_KEY = FDBRecordStoreKeyspace.INDEX
INDEX_SECONDARY_SPACE_KEY = FDBRecordStoreKeyspace.INDEX_SECONDARY_SPACE
RECORD_COUNT_KEY = FDBRecordStoreKeyspace.RECORD_COUNT
INDEX_STATE_SPACE_KEY = FDBRecordStoreKeyspace.INDEX_STATE_SPACE
INDEX_RANGE_SPACE_KEY = FDBRecordStoreKeyspace.INDEX_RANGE_SPACE
INDEX_UNIQUENESS_VIOLATIONS_KEY = FDBRecordStoreKeyspace.INDEX_UNIQUENESS_VIOLATIONS_SPACE
RECORD_VERSION_SPACE_KEY = FDBRecordStoreKeyspace.RECORD_VERSION_SPACE
INDEX_BUILD_SPACE_KEY = FDBRecordStoreKeyspace.INDEX_BUILD_SPACE
