"""FDB Record Layer - Python implementation of FoundationDB Record Layer.

A record-oriented database layer built on FoundationDB providing:
- Protobuf-based schema definition
- Automatic secondary index maintenance
- Query execution with index selection
- Async-first API with continuation support

Example:
    >>> import fdb_record_layer as frl
    >>> from my_proto_pb2 import Person, DESCRIPTOR
    >>>
    >>> # Define schema
    >>> metadata = (
    ...     frl.RecordMetaDataBuilder(DESCRIPTOR)
    ...     .set_record_type("Person", primary_key=frl.field("id"))
    ...     .add_index("Person", "email_idx", frl.field("email"))
    ...     .build()
    ... )
    >>>
    >>> # Use the store
    >>> db = frl.FDBDatabase()
    >>> async with db.open_context() as ctx:
    ...     store = frl.FDBRecordStore(ctx, subspace, metadata)
    ...     await store.save_record(person)
"""

__version__ = "0.1.0"

# Tracking for optional dependencies
_HAS_FDB = False
_HAS_PROTOBUF = False

# Core imports - require FDB
try:
    from fdb_record_layer.core.context import FDBDatabase, FDBRecordContext

    _HAS_FDB = True
except ImportError:
    FDBDatabase = None  # type: ignore
    FDBRecordContext = None  # type: ignore

# Exceptions (no external dependencies)
from fdb_record_layer.core.exceptions import (
    IndexNotFoundException,
    InvalidPrimaryKeyException,
    MetaDataException,
    QueryException,
    RecordLayerException,
    RecordNotFoundException,
    RecordTypeNotFoundException,
    SchemaEvolutionException,
    SerializationException,
)

# Record types (no external dependencies)
from fdb_record_layer.core.record import FDBQueriedRecord, FDBStoredRecord, IndexEntry

# Store imports - require FDB
try:
    from fdb_record_layer.core.store import FDBRecordStore, FDBRecordStoreBuilder
except ImportError:
    FDBRecordStore = None  # type: ignore
    FDBRecordStoreBuilder = None  # type: ignore

# Cursors (no external dependencies)
from fdb_record_layer.cursors.base import (
    FilterCursor,
    ListCursor,
    MapCursor,
    RecordCursor,
    from_list,
)
from fdb_record_layer.cursors.result import (
    NoNextReason,
    RecordCursorContinuation,
    RecordCursorResult,
)

# Key expressions (no external dependencies)
from fdb_record_layer.expressions.base import (
    EMPTY,
    FanType,
    KeyExpression,
    LiteralKeyExpression,
    empty,
    literal,
)
from fdb_record_layer.expressions.concat import ConcatenateKeyExpression, concat
from fdb_record_layer.expressions.field import FieldKeyExpression, field
from fdb_record_layer.expressions.nest import NestKeyExpression, nest
from fdb_record_layer.expressions.record_type import RecordTypeKeyExpression, record_type

# Indexes (no external dependencies)
from fdb_record_layer.indexes.maintainer import IndexMaintainer, IndexScanRange
from fdb_record_layer.indexes.value_index import ValueIndexMaintainer

# Metadata (no external dependencies)
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
from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType

# Serialization - requires protobuf
try:
    from fdb_record_layer.serialization.proto_serializer import (
        CompressedSerializer,
        ProtobufSerializer,
    )

    _HAS_PROTOBUF = True
except ImportError:
    CompressedSerializer = None  # type: ignore
    ProtobufSerializer = None  # type: ignore

# Planners (no external dependencies)
from fdb_record_layer.planner.heuristic import HeuristicPlanner, RecordQueryPlanner

# Plans (no external dependencies)
from fdb_record_layer.plans.base import (
    ExecutionContext,
    PlanComplexity,
    RecordQueryPlan,
)
from fdb_record_layer.plans.filter_plan import FilterPlan
from fdb_record_layer.plans.index_plan import IndexScanPlan
from fdb_record_layer.plans.scan_plan import ScanPlan

# Query components (no external dependencies)
from fdb_record_layer.query.comparisons import Comparison, ComparisonType
from fdb_record_layer.query.components import (
    AndComponent,
    FieldComponent,
    NotComponent,
    OrComponent,
    QueryComponent,
)
from fdb_record_layer.query.predicates import Field
from fdb_record_layer.query.query import (
    BoundRecordQuery,
    Query,
    QueryBuilder,
    RecordQuery,
    RecordQueryBuilder,
)
from fdb_record_layer.serialization.serializer import RecordSerializer

# Health and Lifecycle utilities (no external dependencies)
from fdb_record_layer.utils.health import (
    ComponentHealth,
    HealthChecker,
    HealthReport,
    HealthStatus,
    get_health_checker,
    reset_health_checker,
)
from fdb_record_layer.utils.lifecycle import (
    InFlightContext,
    LifecycleManager,
    LifecycleState,
    ShutdownConfig,
    get_lifecycle,
    init_lifecycle,
    reset_lifecycle,
    shutdown,
)
from fdb_record_layer.utils.logging import (
    LogContext,
    StructuredFormatter,
    configure_logging,
    get_logger,
    log_operation,
    log_timing,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "FDBDatabase",
    "FDBRecordContext",
    "FDBRecordStore",
    "FDBRecordStoreBuilder",
    "FDBStoredRecord",
    "FDBQueriedRecord",
    "IndexEntry",
    # Exceptions
    "RecordLayerException",
    "RecordNotFoundException",
    "RecordTypeNotFoundException",
    "IndexNotFoundException",
    "InvalidPrimaryKeyException",
    "MetaDataException",
    "SchemaEvolutionException",
    "QueryException",
    "SerializationException",
    # Metadata
    "RecordMetaData",
    "RecordMetaDataBuilder",
    "build_record_metadata",
    "RecordType",
    "Index",
    "IndexType",
    "IndexState",
    "IndexOptions",
    "FormerIndex",
    # Key Expressions
    "KeyExpression",
    "FieldKeyExpression",
    "ConcatenateKeyExpression",
    "NestKeyExpression",
    "RecordTypeKeyExpression",
    "LiteralKeyExpression",
    "FanType",
    "EMPTY",
    # Expression helpers
    "field",
    "concat",
    "nest",
    "record_type",
    "empty",
    "literal",
    # Cursors
    "RecordCursor",
    "RecordCursorResult",
    "RecordCursorContinuation",
    "NoNextReason",
    "ListCursor",
    "MapCursor",
    "FilterCursor",
    "from_list",
    # Indexes
    "IndexMaintainer",
    "IndexScanRange",
    "ValueIndexMaintainer",
    # Serialization
    "RecordSerializer",
    "ProtobufSerializer",
    "CompressedSerializer",
    # Query
    "Query",
    "QueryBuilder",
    "RecordQuery",
    "RecordQueryBuilder",
    "BoundRecordQuery",
    "QueryComponent",
    "FieldComponent",
    "AndComponent",
    "OrComponent",
    "NotComponent",
    "Comparison",
    "ComparisonType",
    "Field",
    # Planners
    "RecordQueryPlanner",
    "HeuristicPlanner",
    # Plans
    "RecordQueryPlan",
    "ExecutionContext",
    "PlanComplexity",
    "ScanPlan",
    "IndexScanPlan",
    "FilterPlan",
    # Health checks
    "HealthChecker",
    "HealthReport",
    "HealthStatus",
    "ComponentHealth",
    "get_health_checker",
    "reset_health_checker",
    # Lifecycle management
    "LifecycleManager",
    "LifecycleState",
    "ShutdownConfig",
    "InFlightContext",
    "get_lifecycle",
    "init_lifecycle",
    "reset_lifecycle",
    "shutdown",
    # Logging utilities
    "LogContext",
    "StructuredFormatter",
    "configure_logging",
    "get_logger",
    "log_operation",
    "log_timing",
]
