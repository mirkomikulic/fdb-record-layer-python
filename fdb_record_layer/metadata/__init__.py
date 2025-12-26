"""Metadata and schema management."""

from fdb_record_layer.metadata.evolution import (
    EvolutionChange,
    EvolutionIssue,
    EvolutionResult,
    EvolutionSeverity,
    MetaDataEvolutionValidator,
    validate_evolution,
)
from fdb_record_layer.metadata.index import (
    FormerIndex,
    Index,
    IndexOptions,
    IndexState,
    IndexType,
)
from fdb_record_layer.metadata.meta_data_builder import (
    RecordMetaDataBuilder,
    build_record_metadata,
)
from fdb_record_layer.metadata.meta_data_store import (
    CachedMetaDataStore,
    FDBMetaDataStore,
    MetaDataHeader,
    MetaDataSerializer,
)
from fdb_record_layer.metadata.record_metadata import (
    RecordMetaData,
    RecordType,
)

__all__ = [
    # Core metadata
    "RecordMetaData",
    "RecordType",
    "RecordMetaDataBuilder",
    "build_record_metadata",
    # Index
    "Index",
    "IndexType",
    "IndexState",
    "IndexOptions",
    "FormerIndex",
    # Metadata store
    "FDBMetaDataStore",
    "CachedMetaDataStore",
    "MetaDataHeader",
    "MetaDataSerializer",
    # Evolution
    "MetaDataEvolutionValidator",
    "EvolutionResult",
    "EvolutionIssue",
    "EvolutionChange",
    "EvolutionSeverity",
    "validate_evolution",
]
