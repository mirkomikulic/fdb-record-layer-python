"""Schema evolution validation and migration.

The MetaDataEvolutionValidator ensures that schema changes are safe and
compatible with existing data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb_record_layer.metadata.index import Index
    from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType


class EvolutionChange(Enum):
    """Types of schema changes."""

    # Record type changes
    RECORD_TYPE_ADDED = auto()
    RECORD_TYPE_REMOVED = auto()
    PRIMARY_KEY_CHANGED = auto()

    # Field changes
    FIELD_ADDED = auto()
    FIELD_REMOVED = auto()
    FIELD_TYPE_CHANGED = auto()
    FIELD_LABEL_CHANGED = auto()  # optional -> required, etc.

    # Index changes
    INDEX_ADDED = auto()
    INDEX_REMOVED = auto()
    INDEX_DEFINITION_CHANGED = auto()
    INDEX_TYPE_CHANGED = auto()
    INDEX_OPTIONS_CHANGED = auto()

    # Version changes
    VERSION_INCREASED = auto()
    VERSION_DECREASED = auto()


class EvolutionSeverity(Enum):
    """Severity levels for evolution changes."""

    INFO = auto()  # Safe, no action needed
    WARNING = auto()  # May require attention
    ERROR = auto()  # Breaking change, likely data loss
    REQUIRES_REBUILD = auto()  # Requires index rebuild


@dataclass
class EvolutionIssue:
    """An issue found during schema evolution validation."""

    change_type: EvolutionChange
    severity: EvolutionSeverity
    message: str
    old_value: Any | None = None
    new_value: Any | None = None
    record_type: str | None = None
    index_name: str | None = None

    def __repr__(self) -> str:
        prefix = f"[{self.severity.name}] {self.change_type.name}"
        if self.record_type:
            prefix += f" ({self.record_type})"
        if self.index_name:
            prefix += f" ({self.index_name})"
        return f"{prefix}: {self.message}"


@dataclass
class EvolutionResult:
    """Result of schema evolution validation."""

    is_valid: bool
    issues: list[EvolutionIssue] = field(default_factory=list)
    requires_rebuild: set[str] = field(default_factory=set)  # Index names

    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return any(i.severity == EvolutionSeverity.ERROR for i in self.issues)

    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return any(i.severity == EvolutionSeverity.WARNING for i in self.issues)

    def get_errors(self) -> list[EvolutionIssue]:
        """Get all error-level issues."""
        return [i for i in self.issues if i.severity == EvolutionSeverity.ERROR]

    def get_warnings(self) -> list[EvolutionIssue]:
        """Get all warning-level issues."""
        return [i for i in self.issues if i.severity == EvolutionSeverity.WARNING]

    def summary(self) -> str:
        """Generate a summary of the validation result."""
        if self.is_valid and not self.issues:
            return "Schema evolution is valid with no issues."

        lines = []
        if not self.is_valid:
            lines.append("Schema evolution is INVALID:")
        else:
            lines.append("Schema evolution is valid with issues:")

        for issue in self.issues:
            lines.append(f"  {issue}")

        if self.requires_rebuild:
            lines.append(f"  Indexes requiring rebuild: {', '.join(self.requires_rebuild)}")

        return "\n".join(lines)


class MetaDataEvolutionValidator:
    """Validates schema evolution between metadata versions.

    This validator ensures that changes to the schema are compatible
    with existing data and don't cause data loss or corruption.

    Rules enforced:
    - Primary keys cannot be changed (would break record identity)
    - Required fields cannot be added (existing records don't have them)
    - Field types cannot be changed incompatibly
    - Removing indexes is allowed but logged
    - Changing index definitions requires rebuild

    Example:
        >>> validator = MetaDataEvolutionValidator()
        >>> result = validator.validate(old_metadata, new_metadata)
        >>> if not result.is_valid:
        ...     print(result.summary())
    """

    def __init__(
        self,
        allow_record_type_removal: bool = False,
        allow_field_removal: bool = True,
        allow_primary_key_change: bool = False,
    ) -> None:
        """Initialize the validator with options.

        Args:
            allow_record_type_removal: Allow removing record types.
            allow_field_removal: Allow removing fields.
            allow_primary_key_change: Allow changing primary keys (dangerous!).
        """
        self._allow_record_type_removal = allow_record_type_removal
        self._allow_field_removal = allow_field_removal
        self._allow_primary_key_change = allow_primary_key_change

    def validate(
        self, old_metadata: RecordMetaData, new_metadata: RecordMetaData
    ) -> EvolutionResult:
        """Validate schema evolution from old to new metadata.

        Args:
            old_metadata: The current metadata.
            new_metadata: The proposed new metadata.

        Returns:
            EvolutionResult with validation status and issues.
        """
        issues: list[EvolutionIssue] = []
        requires_rebuild: set[str] = set()

        # Validate version
        issues.extend(self._validate_version(old_metadata, new_metadata))

        # Validate record types
        issues.extend(self._validate_record_types(old_metadata, new_metadata))

        # Validate indexes
        index_issues, rebuild = self._validate_indexes(old_metadata, new_metadata)
        issues.extend(index_issues)
        requires_rebuild.update(rebuild)

        # Determine if valid (no errors)
        is_valid = not any(i.severity == EvolutionSeverity.ERROR for i in issues)

        return EvolutionResult(
            is_valid=is_valid,
            issues=issues,
            requires_rebuild=requires_rebuild,
        )

    def _validate_version(self, old: RecordMetaData, new: RecordMetaData) -> list[EvolutionIssue]:
        """Validate version changes."""
        issues = []

        if new.version < old.version:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.VERSION_DECREASED,
                    severity=EvolutionSeverity.ERROR,
                    message=f"Version cannot decrease from {old.version} to {new.version}",
                    old_value=old.version,
                    new_value=new.version,
                )
            )
        elif new.version == old.version:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.VERSION_INCREASED,
                    severity=EvolutionSeverity.WARNING,
                    message="Version not incremented for schema change",
                    old_value=old.version,
                    new_value=new.version,
                )
            )
        else:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.VERSION_INCREASED,
                    severity=EvolutionSeverity.INFO,
                    message=f"Version increased from {old.version} to {new.version}",
                    old_value=old.version,
                    new_value=new.version,
                )
            )

        return issues

    def _validate_record_types(
        self, old: RecordMetaData, new: RecordMetaData
    ) -> list[EvolutionIssue]:
        """Validate record type changes."""
        issues = []

        old_types = set(old.record_types.keys())
        new_types = set(new.record_types.keys())

        # Check for removed types
        removed = old_types - new_types
        for name in removed:
            severity = (
                EvolutionSeverity.WARNING
                if self._allow_record_type_removal
                else EvolutionSeverity.ERROR
            )
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.RECORD_TYPE_REMOVED,
                    severity=severity,
                    message=f"Record type '{name}' was removed",
                    record_type=name,
                )
            )

        # Check for added types
        added = new_types - old_types
        for name in added:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.RECORD_TYPE_ADDED,
                    severity=EvolutionSeverity.INFO,
                    message=f"Record type '{name}' was added",
                    record_type=name,
                )
            )

        # Check for changed types
        common = old_types & new_types
        for name in common:
            issues.extend(
                self._validate_record_type_change(old.record_types[name], new.record_types[name])
            )

        return issues

    def _validate_record_type_change(
        self, old_type: RecordType, new_type: RecordType
    ) -> list[EvolutionIssue]:
        """Validate changes to a single record type."""
        issues = []
        name = old_type.name

        # Check primary key
        old_pk = repr(old_type.primary_key)
        new_pk = repr(new_type.primary_key)
        if old_pk != new_pk:
            severity = (
                EvolutionSeverity.WARNING
                if self._allow_primary_key_change
                else EvolutionSeverity.ERROR
            )
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.PRIMARY_KEY_CHANGED,
                    severity=severity,
                    message=f"Primary key changed for '{name}'",
                    old_value=old_pk,
                    new_value=new_pk,
                    record_type=name,
                )
            )

        # Check fields (if descriptors are available)
        if old_type.descriptor and new_type.descriptor:
            issues.extend(self._validate_field_changes(old_type, new_type))

        return issues

    def _validate_field_changes(
        self, old_type: RecordType, new_type: RecordType
    ) -> list[EvolutionIssue]:
        """Validate field changes in a record type."""
        issues = []
        name = old_type.name

        old_fields = {f.name: f for f in old_type.descriptor.fields}
        new_fields = {f.name: f for f in new_type.descriptor.fields}

        # Check removed fields
        for field_name in set(old_fields.keys()) - set(new_fields.keys()):
            severity = (
                EvolutionSeverity.WARNING if self._allow_field_removal else EvolutionSeverity.ERROR
            )
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.FIELD_REMOVED,
                    severity=severity,
                    message=f"Field '{field_name}' removed from '{name}'",
                    record_type=name,
                )
            )

        # Check added fields
        for field_name in set(new_fields.keys()) - set(old_fields.keys()):
            new_field = new_fields[field_name]
            # Check if required (proto3 doesn't have required, but proto2 does)
            is_required = (
                hasattr(new_field, "label") and new_field.label == 2  # LABEL_REQUIRED
            )
            severity = EvolutionSeverity.ERROR if is_required else EvolutionSeverity.INFO
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.FIELD_ADDED,
                    severity=severity,
                    message=f"Field '{field_name}' added to '{name}'"
                    + (" (required)" if is_required else ""),
                    record_type=name,
                )
            )

        # Check changed fields
        for field_name in set(old_fields.keys()) & set(new_fields.keys()):
            old_field = old_fields[field_name]
            new_field = new_fields[field_name]

            # Check type change
            if old_field.type != new_field.type:
                issues.append(
                    EvolutionIssue(
                        change_type=EvolutionChange.FIELD_TYPE_CHANGED,
                        severity=EvolutionSeverity.ERROR,
                        message=f"Field '{field_name}' type changed in '{name}'",
                        old_value=old_field.type,
                        new_value=new_field.type,
                        record_type=name,
                    )
                )

            # Check label change (optional/required/repeated)
            if hasattr(old_field, "label") and hasattr(new_field, "label"):
                if old_field.label != new_field.label:
                    issues.append(
                        EvolutionIssue(
                            change_type=EvolutionChange.FIELD_LABEL_CHANGED,
                            severity=EvolutionSeverity.WARNING,
                            message=f"Field '{field_name}' label changed in '{name}'",
                            old_value=old_field.label,
                            new_value=new_field.label,
                            record_type=name,
                        )
                    )

        return issues

    def _validate_indexes(
        self, old: RecordMetaData, new: RecordMetaData
    ) -> tuple[list[EvolutionIssue], set[str]]:
        """Validate index changes."""
        issues = []
        requires_rebuild: set[str] = set()

        old_indexes = set(old.indexes.keys())
        new_indexes = set(new.indexes.keys())

        # Check removed indexes
        for name in old_indexes - new_indexes:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.INDEX_REMOVED,
                    severity=EvolutionSeverity.INFO,
                    message=f"Index '{name}' was removed",
                    index_name=name,
                )
            )

        # Check added indexes
        for name in new_indexes - old_indexes:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.INDEX_ADDED,
                    severity=EvolutionSeverity.REQUIRES_REBUILD,
                    message=f"Index '{name}' was added (requires build)",
                    index_name=name,
                )
            )
            requires_rebuild.add(name)

        # Check changed indexes
        for name in old_indexes & new_indexes:
            old_idx = old.indexes[name]
            new_idx = new.indexes[name]
            idx_issues, needs_rebuild = self._validate_index_change(old_idx, new_idx)
            issues.extend(idx_issues)
            if needs_rebuild:
                requires_rebuild.add(name)

        return issues, requires_rebuild

    def _validate_index_change(
        self, old_idx: Index, new_idx: Index
    ) -> tuple[list[EvolutionIssue], bool]:
        """Validate changes to a single index."""
        issues = []
        needs_rebuild = False
        name = old_idx.name

        # Check type change
        if old_idx.index_type != new_idx.index_type:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.INDEX_TYPE_CHANGED,
                    severity=EvolutionSeverity.REQUIRES_REBUILD,
                    message=f"Index '{name}' type changed",
                    old_value=old_idx.index_type.value,
                    new_value=new_idx.index_type.value,
                    index_name=name,
                )
            )
            needs_rebuild = True

        # Check expression change
        old_expr = repr(old_idx.root_expression)
        new_expr = repr(new_idx.root_expression)
        if old_expr != new_expr:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.INDEX_DEFINITION_CHANGED,
                    severity=EvolutionSeverity.REQUIRES_REBUILD,
                    message=f"Index '{name}' expression changed",
                    old_value=old_expr,
                    new_value=new_expr,
                    index_name=name,
                )
            )
            needs_rebuild = True

        # Check record types change
        old_types = set(old_idx.record_types or [])
        new_types = set(new_idx.record_types or [])
        if old_types != new_types:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.INDEX_DEFINITION_CHANGED,
                    severity=EvolutionSeverity.REQUIRES_REBUILD,
                    message=f"Index '{name}' record types changed",
                    old_value=old_types,
                    new_value=new_types,
                    index_name=name,
                )
            )
            needs_rebuild = True

        # Check options change (less critical)
        if old_idx.options != new_idx.options:
            issues.append(
                EvolutionIssue(
                    change_type=EvolutionChange.INDEX_OPTIONS_CHANGED,
                    severity=EvolutionSeverity.WARNING,
                    message=f"Index '{name}' options changed",
                    index_name=name,
                )
            )

        return issues, needs_rebuild


def validate_evolution(
    old_metadata: RecordMetaData,
    new_metadata: RecordMetaData,
    strict: bool = True,
) -> EvolutionResult:
    """Convenience function to validate schema evolution.

    Args:
        old_metadata: Current metadata.
        new_metadata: Proposed new metadata.
        strict: If True, use strict validation rules.

    Returns:
        EvolutionResult with validation status.
    """
    validator = MetaDataEvolutionValidator(
        allow_record_type_removal=not strict,
        allow_field_removal=True,
        allow_primary_key_change=False,
    )
    return validator.validate(old_metadata, new_metadata)
