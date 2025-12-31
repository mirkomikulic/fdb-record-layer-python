"""Java-compatible protobuf definitions.

This module provides protobuf message classes compatible with the
Java FDB Record Layer's record_metadata.proto definitions.
"""

from fdb_record_layer.compat.proto.record_metadata_pb2 import (
    AndPredicate,
    ComparisonType,
    ConstantPredicate,
    # Store header
    DataStoreInfo,
    Empty,
    FanType,
    Field,
    FormerIndex,
    # Index
    Index,
    IndexOption,
    IndexType,
    # Key expressions
    KeyExpression,
    List,
    # Metadata
    MetaData,
    Nesting,
    NotPredicate,
    NullInterpretation,
    OrPredicate,
    Predicate,
    RecordCountState,
    # Record type
    RecordType,
    RecordTypeKey,
    StoreLockState,
    Then,
    UserFieldEntry,
    Value,
    ValuePredicate,
)

__all__ = [
    # Key expressions
    "KeyExpression",
    "Then",
    "Nesting",
    "Field",
    "Empty",
    "Value",
    "RecordTypeKey",
    "List",
    "FanType",
    "NullInterpretation",
    # Store header
    "DataStoreInfo",
    "UserFieldEntry",
    "RecordCountState",
    "StoreLockState",
    # Index
    "Index",
    "IndexType",
    "IndexOption",
    "Predicate",
    "AndPredicate",
    "OrPredicate",
    "NotPredicate",
    "ValuePredicate",
    "ComparisonType",
    "ConstantPredicate",
    # Record type
    "RecordType",
    "FormerIndex",
    # Metadata
    "MetaData",
]
