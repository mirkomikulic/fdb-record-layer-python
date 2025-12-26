"""Index metadata definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb_record_layer.expressions.base import KeyExpression


class IndexType(str, Enum):
    """Types of indexes supported by the record layer.

    VALUE: Standard secondary index mapping key values to primary keys.
    COUNT: Aggregate index maintaining counts.
    SUM: Aggregate index maintaining sums.
    MIN_EVER: Aggregate tracking minimum value ever seen.
    MAX_EVER: Aggregate tracking maximum value ever seen.
    RANK: Index supporting rank/leaderboard queries.
    TEXT: Full-text search index.
    VERSION: Index on record versions.
    """

    VALUE = "value"
    COUNT = "count"
    SUM = "sum"
    MIN_EVER = "min_ever"
    MAX_EVER = "max_ever"
    RANK = "rank"
    TEXT = "text"
    VERSION = "version"


class IndexState(str, Enum):
    """States an index can be in.

    DISABLED: Index is not maintained or queryable.
    WRITE_ONLY: Index is maintained on writes but not yet queryable.
    READABLE: Index is fully operational.
    """

    DISABLED = "disabled"
    WRITE_ONLY = "write_only"
    READABLE = "readable"


@dataclass
class IndexOptions:
    """Options for index configuration.

    Attributes:
        unique: Whether the index enforces uniqueness.
        sparse: Whether null values are excluded from the index.
        allow_duplicates: Whether duplicate index entries are allowed.
    """

    unique: bool = False
    sparse: bool = False
    allow_duplicates: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "unique": self.unique,
            "sparse": self.sparse,
            "allow_duplicates": self.allow_duplicates,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexOptions:
        """Create from dictionary."""
        return cls(
            unique=data.get("unique", False),
            sparse=data.get("sparse", False),
            allow_duplicates=data.get("allow_duplicates", True),
        )


@dataclass
class Index:
    """Metadata for a secondary index.

    An index defines:
    - What expression to compute for index keys
    - What type of index (VALUE, COUNT, RANK, etc.)
    - Which record types it applies to
    - Various options

    Attributes:
        name: Unique name for the index.
        root_expression: Key expression defining what to index.
        index_type: The type of index.
        record_types: Record types this index applies to. None means all types.
        options: Additional index options.
        added_version: Metadata version when this index was added.
        last_modified_version: Metadata version of last modification.
        predicate: Optional predicate for sparse indexes.
        subspace_key: Optional custom subspace key for index storage.
    """

    name: str
    root_expression: KeyExpression
    index_type: IndexType = IndexType.VALUE
    record_types: list[str] | None = None
    options: IndexOptions = field(default_factory=IndexOptions)
    added_version: int = 0
    last_modified_version: int = 0
    predicate: Any | None = None  # QueryComponent for sparse indexes
    subspace_key: Any | None = None

    @property
    def is_universal(self) -> bool:
        """Check if this index applies to all record types."""
        return self.record_types is None

    def applies_to_record_type(self, record_type_name: str) -> bool:
        """Check if this index applies to a given record type.

        Args:
            record_type_name: The record type name to check.

        Returns:
            True if the index applies to this record type.
        """
        if self.record_types is None:
            return True
        return record_type_name in self.record_types

    def get_column_size(self) -> int:
        """Get the number of columns in the index key."""
        return self.root_expression.get_column_size()


@dataclass
class FormerIndex:
    """Metadata for an index that has been removed.

    Tracking former indexes allows safe cleanup and prevents
    accidentally reusing index names with incompatible definitions.

    Attributes:
        name: The former index name.
        added_version: When the original index was added.
        removed_version: When the index was removed.
        subspace_key: The subspace key that was used.
    """

    name: str
    added_version: int
    removed_version: int
    subspace_key: Any | None = None
