"""Scan comparisons for mapping query predicates to index scans."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fdb_record_layer.query.comparisons import Comparison, ComparisonType


class ScanBoundType(str, Enum):
    """Type of scan bound."""

    UNBOUNDED = "unbounded"
    INCLUSIVE = "inclusive"
    EXCLUSIVE = "exclusive"


@dataclass
class ScanBound:
    """A bound for a scan range.

    Attributes:
        bound_type: The type of bound (unbounded, inclusive, exclusive).
        value: The bound value (None for unbounded).
    """

    bound_type: ScanBoundType
    value: Any = None

    @staticmethod
    def unbounded() -> ScanBound:
        """Create an unbounded scan bound."""
        return ScanBound(ScanBoundType.UNBOUNDED)

    @staticmethod
    def inclusive(value: Any) -> ScanBound:
        """Create an inclusive scan bound."""
        return ScanBound(ScanBoundType.INCLUSIVE, value)

    @staticmethod
    def exclusive(value: Any) -> ScanBound:
        """Create an exclusive scan bound."""
        return ScanBound(ScanBoundType.EXCLUSIVE, value)

    def is_unbounded(self) -> bool:
        """Check if this is an unbounded bound."""
        return self.bound_type == ScanBoundType.UNBOUNDED


@dataclass
class TupleRange:
    """A range of tuple values for scanning.

    Defines a range from [low, high] or (low, high) depending on
    inclusive/exclusive bounds.

    Attributes:
        low: The lower bound.
        high: The upper bound.
    """

    low: ScanBound = field(default_factory=ScanBound.unbounded)
    high: ScanBound = field(default_factory=ScanBound.unbounded)

    @staticmethod
    def all() -> TupleRange:
        """Create a range covering all values."""
        return TupleRange()

    @staticmethod
    def equals(value: Any) -> TupleRange:
        """Create a range for exact equality."""
        return TupleRange(
            low=ScanBound.inclusive(value),
            high=ScanBound.inclusive(value),
        )

    @staticmethod
    def prefix(prefix: tuple[Any, ...]) -> TupleRange:
        """Create a range for a prefix scan."""
        return TupleRange(
            low=ScanBound.inclusive(prefix),
            high=ScanBound.inclusive(prefix),
        )

    def is_equality(self) -> bool:
        """Check if this is an equality range."""
        return (
            self.low.bound_type == ScanBoundType.INCLUSIVE
            and self.high.bound_type == ScanBoundType.INCLUSIVE
            and self.low.value == self.high.value
        )

    def is_empty(self) -> bool:
        """Check if this range is provably empty."""
        if self.low.is_unbounded() or self.high.is_unbounded():
            return False

        if self.low.value > self.high.value:
            return True

        if self.low.value == self.high.value:
            # Equal values - only empty if one bound is exclusive
            return (
                self.low.bound_type == ScanBoundType.EXCLUSIVE
                or self.high.bound_type == ScanBoundType.EXCLUSIVE
            )

        return False


@dataclass
class ScanComparisons:
    """A collection of comparisons that can be satisfied by an index scan.

    ScanComparisons groups predicates into:
    - Equality comparisons (form the prefix of the scan)
    - Inequality comparisons (define the range after the prefix)
    - IN comparisons (can be unioned or intersected)

    Attributes:
        equality_comparisons: List of equality comparisons in key order.
        inequality_comparisons: Inequality comparisons on the next field.
        in_comparisons: IN comparisons that require multiple scans.
    """

    equality_comparisons: list[Comparison] = field(default_factory=list)
    inequality_comparisons: list[Comparison] = field(default_factory=list)
    in_comparisons: list[Comparison] = field(default_factory=list)

    def get_equality_size(self) -> int:
        """Get the number of equality comparisons."""
        return len(self.equality_comparisons)

    def has_inequality(self) -> bool:
        """Check if there are inequality comparisons."""
        return len(self.inequality_comparisons) > 0

    def has_in_comparison(self) -> bool:
        """Check if there are IN comparisons."""
        return len(self.in_comparisons) > 0

    def is_equality_only(self) -> bool:
        """Check if this is an equality-only scan."""
        return not self.has_inequality() and not self.has_in_comparison()

    def to_tuple_range(self, bindings: dict[str, Any] | None = None) -> TupleRange:
        """Convert to a TupleRange for scanning.

        Args:
            bindings: Parameter bindings for parameterized comparisons.

        Returns:
            The equivalent TupleRange.
        """
        if not self.equality_comparisons and not self.inequality_comparisons:
            return TupleRange.all()

        # Build prefix from equality comparisons
        prefix_values: list[Any] = []
        for comp in self.equality_comparisons:
            prefix_values.append(comp.get_value(bindings))

        if not self.inequality_comparisons:
            # Pure equality scan
            if len(prefix_values) == 1:
                return TupleRange.equals(prefix_values[0])
            return TupleRange.prefix(tuple(prefix_values))

        # Handle inequality
        low = ScanBound.unbounded()
        high = ScanBound.unbounded()

        for comp in self.inequality_comparisons:
            value = comp.get_value(bindings)

            if comp.comparison_type == ComparisonType.GREATER_THAN:
                low = ScanBound.exclusive(value)
            elif comp.comparison_type == ComparisonType.GREATER_THAN_OR_EQUALS:
                low = ScanBound.inclusive(value)
            elif comp.comparison_type == ComparisonType.LESS_THAN:
                high = ScanBound.exclusive(value)
            elif comp.comparison_type == ComparisonType.LESS_THAN_OR_EQUALS:
                high = ScanBound.inclusive(value)
            elif comp.comparison_type == ComparisonType.STARTS_WITH:
                # For starts_with, scan from prefix to prefix + 0xFF
                low = ScanBound.inclusive(value)
                high = ScanBound.inclusive(value + "\xff")

        return TupleRange(low=low, high=high)

    def add_equality(self, comparison: Comparison) -> ScanComparisons:
        """Add an equality comparison.

        Returns:
            A new ScanComparisons with the comparison added.
        """
        return ScanComparisons(
            equality_comparisons=[*self.equality_comparisons, comparison],
            inequality_comparisons=self.inequality_comparisons,
            in_comparisons=self.in_comparisons,
        )

    def add_inequality(self, comparison: Comparison) -> ScanComparisons:
        """Add an inequality comparison.

        Returns:
            A new ScanComparisons with the comparison added.
        """
        return ScanComparisons(
            equality_comparisons=self.equality_comparisons,
            inequality_comparisons=[*self.inequality_comparisons, comparison],
            in_comparisons=self.in_comparisons,
        )

    def add_in(self, comparison: Comparison) -> ScanComparisons:
        """Add an IN comparison.

        Returns:
            A new ScanComparisons with the comparison added.
        """
        return ScanComparisons(
            equality_comparisons=self.equality_comparisons,
            inequality_comparisons=self.inequality_comparisons,
            in_comparisons=[*self.in_comparisons, comparison],
        )

    def is_empty(self) -> bool:
        """Check if there are no comparisons."""
        return (
            not self.equality_comparisons
            and not self.inequality_comparisons
            and not self.in_comparisons
        )

    @staticmethod
    def from_comparison(comparison: Comparison) -> ScanComparisons:
        """Create ScanComparisons from a single comparison.

        Args:
            comparison: The comparison to convert.

        Returns:
            ScanComparisons containing the comparison.
        """
        if comparison.comparison_type.is_equality:
            return ScanComparisons(equality_comparisons=[comparison])
        elif comparison.comparison_type == ComparisonType.IN:
            return ScanComparisons(in_comparisons=[comparison])
        elif comparison.comparison_type.is_inequality:
            return ScanComparisons(inequality_comparisons=[comparison])
        else:
            # Other types like CONTAINS don't translate to scans
            return ScanComparisons()


@dataclass
class IndexScanBounds:
    """Bounds for an index scan.

    Combines the prefix (from equality comparisons) with the
    range (from inequality comparisons).

    Attributes:
        prefix: The fixed prefix values.
        range: The range to scan after the prefix.
    """

    prefix: tuple[Any, ...] = ()
    range: TupleRange = field(default_factory=TupleRange.all)

    @staticmethod
    def from_scan_comparisons(
        scan_comparisons: ScanComparisons,
        bindings: dict[str, Any] | None = None,
    ) -> IndexScanBounds:
        """Create IndexScanBounds from ScanComparisons.

        Args:
            scan_comparisons: The scan comparisons.
            bindings: Parameter bindings.

        Returns:
            The equivalent IndexScanBounds.
        """
        prefix_values = []
        for comp in scan_comparisons.equality_comparisons:
            prefix_values.append(comp.get_value(bindings))

        if not scan_comparisons.inequality_comparisons:
            return IndexScanBounds(
                prefix=tuple(prefix_values),
                range=TupleRange.all(),
            )

        # Build range from inequalities
        low = ScanBound.unbounded()
        high = ScanBound.unbounded()

        for comp in scan_comparisons.inequality_comparisons:
            value = comp.get_value(bindings)

            if comp.comparison_type == ComparisonType.GREATER_THAN:
                if low.is_unbounded() or value > low.value:
                    low = ScanBound.exclusive(value)
            elif comp.comparison_type == ComparisonType.GREATER_THAN_OR_EQUALS:
                if low.is_unbounded() or value >= low.value:
                    low = ScanBound.inclusive(value)
            elif comp.comparison_type == ComparisonType.LESS_THAN:
                if high.is_unbounded() or value < high.value:
                    high = ScanBound.exclusive(value)
            elif comp.comparison_type == ComparisonType.LESS_THAN_OR_EQUALS:
                if high.is_unbounded() or value <= high.value:
                    high = ScanBound.inclusive(value)
            elif comp.comparison_type == ComparisonType.STARTS_WITH:
                low = ScanBound.inclusive(value)
                # For starts_with on strings
                high = ScanBound.inclusive(value + "\xff")

        return IndexScanBounds(
            prefix=tuple(prefix_values),
            range=TupleRange(low=low, high=high),
        )
