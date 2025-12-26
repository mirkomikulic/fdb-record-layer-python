"""RecordQuery and Query builder for declarative queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fdb_record_layer.query.components import (
    AndComponent,
    OrComponent,
    QueryComponent,
)
from fdb_record_layer.query.predicates import Field

if TYPE_CHECKING:
    from fdb_record_layer.expressions.base import KeyExpression


@dataclass
class SortDescriptor:
    """Describes a sort order for query results.

    Attributes:
        key_expression: The expression to sort by.
        reverse: If True, sort in descending order.
    """

    key_expression: KeyExpression
    reverse: bool = False


@dataclass
class RecordQuery:
    """A declarative query definition.

    RecordQuery represents a complete query specification including:
    - Record types to query
    - Filter predicates
    - Sort order
    - Limit and continuation

    This is an immutable query specification that can be passed to a
    planner to generate an execution plan.

    Attributes:
        record_types: The record types to query.
        filter: Optional filter component.
        sort: Optional sort specification.
        removes_duplicates: Whether to remove duplicate results.
        required_results: Fields that must be in results.
    """

    record_types: list[str] = field(default_factory=list)
    filter: QueryComponent | None = None
    sort: SortDescriptor | None = None
    removes_duplicates: bool = False
    required_results: list[str] = field(default_factory=list)

    def get_filter(self) -> QueryComponent | None:
        """Get the filter component."""
        return self.filter

    def get_record_types(self) -> list[str]:
        """Get the record types being queried."""
        return self.record_types

    def get_sort(self) -> SortDescriptor | None:
        """Get the sort descriptor."""
        return self.sort

    def has_record_type_filter(self) -> bool:
        """Check if the query filters by record type."""
        return len(self.record_types) > 0

    def get_all_fields(self) -> set[str]:
        """Get all fields referenced in the query."""
        fields: set[str] = set()
        if self.filter:
            fields.update(self.filter.get_fields())
        return fields

    def with_filter(self, new_filter: QueryComponent) -> RecordQuery:
        """Create a new query with an additional filter (AND'd with existing)."""
        if self.filter is None:
            combined = new_filter
        else:
            combined = self.filter.and_(new_filter)

        return RecordQuery(
            record_types=self.record_types,
            filter=combined,
            sort=self.sort,
            removes_duplicates=self.removes_duplicates,
            required_results=self.required_results,
        )

    def __repr__(self) -> str:
        parts = []
        if self.record_types:
            parts.append(f"types={self.record_types}")
        if self.filter:
            parts.append(f"filter={self.filter}")
        if self.sort:
            parts.append(f"sort={self.sort}")
        return f"RecordQuery({', '.join(parts)})"


class RecordQueryBuilder:
    """Builder for constructing RecordQuery instances.

    Example:
        >>> query = (RecordQueryBuilder()
        ...     .set_record_types("Person")
        ...     .set_filter(Field("age").greater_than(21))
        ...     .build())
    """

    def __init__(self) -> None:
        self._record_types: list[str] = []
        self._filter: QueryComponent | None = None
        self._sort: SortDescriptor | None = None
        self._removes_duplicates: bool = False
        self._required_results: list[str] = []

    def set_record_type(self, record_type: str) -> RecordQueryBuilder:
        """Set a single record type to query.

        Args:
            record_type: The record type name.

        Returns:
            This builder for chaining.
        """
        self._record_types = [record_type]
        return self

    def set_record_types(self, *record_types: str) -> RecordQueryBuilder:
        """Set multiple record types to query.

        Args:
            record_types: The record type names.

        Returns:
            This builder for chaining.
        """
        self._record_types = list(record_types)
        return self

    def set_filter(self, filter_component: QueryComponent) -> RecordQueryBuilder:
        """Set the filter predicate.

        Args:
            filter_component: The filter to apply.

        Returns:
            This builder for chaining.
        """
        self._filter = filter_component
        return self

    def set_sort(self, key_expression: KeyExpression, reverse: bool = False) -> RecordQueryBuilder:
        """Set the sort order.

        Args:
            key_expression: The expression to sort by.
            reverse: If True, sort descending.

        Returns:
            This builder for chaining.
        """
        self._sort = SortDescriptor(key_expression, reverse)
        return self

    def set_removes_duplicates(self, removes: bool = True) -> RecordQueryBuilder:
        """Set whether to remove duplicates.

        Args:
            removes: If True, remove duplicate results.

        Returns:
            This builder for chaining.
        """
        self._removes_duplicates = removes
        return self

    def set_required_results(self, *fields: str) -> RecordQueryBuilder:
        """Set fields that must be in results.

        Args:
            fields: Field names that must be returned.

        Returns:
            This builder for chaining.
        """
        self._required_results = list(fields)
        return self

    def build(self) -> RecordQuery:
        """Build the RecordQuery.

        Returns:
            The constructed query.
        """
        return RecordQuery(
            record_types=self._record_types,
            filter=self._filter,
            sort=self._sort,
            removes_duplicates=self._removes_duplicates,
            required_results=self._required_results,
        )


class Query:
    """Static factory for fluent query building.

    Provides a Java-like fluent API for building queries.

    Example:
        >>> # Simple query
        >>> query = Query.from_type("Person").where(
        ...     Query.field("name").equals("Alice")
        ... ).build()
        >>>
        >>> # Complex query with AND/OR
        >>> query = Query.from_type("Person").where(
        ...     Query.and_(
        ...         Query.field("age").greater_than(18),
        ...         Query.or_(
        ...             Query.field("city").equals("NYC"),
        ...             Query.field("city").equals("LA")
        ...         )
        ...     )
        ... ).build()
    """

    @staticmethod
    def from_type(record_type: str) -> QueryBuilder:
        """Start building a query for a record type.

        Args:
            record_type: The record type to query.

        Returns:
            A query builder.
        """
        return QueryBuilder().from_type(record_type)

    @staticmethod
    def from_types(*record_types: str) -> QueryBuilder:
        """Start building a query for multiple record types.

        Args:
            record_types: The record types to query.

        Returns:
            A query builder.
        """
        return QueryBuilder().from_types(*record_types)

    @staticmethod
    def field(name: str) -> Field:
        """Create a field predicate builder.

        Args:
            name: The field name.

        Returns:
            A Field builder for creating predicates.
        """
        return Field(name)

    @staticmethod
    def and_(*components: QueryComponent) -> QueryComponent:
        """Create an AND of multiple components.

        Args:
            components: The components to AND together.

        Returns:
            An AndComponent.
        """
        return AndComponent(children=list(components))

    @staticmethod
    def or_(*components: QueryComponent) -> QueryComponent:
        """Create an OR of multiple components.

        Args:
            components: The components to OR together.

        Returns:
            An OrComponent.
        """
        return OrComponent(children=list(components))


class QueryBuilder:
    """Fluent builder for queries.

    This provides a chainable API for building queries step by step.
    """

    def __init__(self) -> None:
        self._record_types: list[str] = []
        self._filter: QueryComponent | None = None
        self._sort: SortDescriptor | None = None
        self._removes_duplicates: bool = False

    def from_type(self, record_type: str) -> QueryBuilder:
        """Set the record type.

        Args:
            record_type: The record type to query.

        Returns:
            This builder for chaining.
        """
        self._record_types = [record_type]
        return self

    def from_types(self, *record_types: str) -> QueryBuilder:
        """Set multiple record types.

        Args:
            record_types: The record types to query.

        Returns:
            This builder for chaining.
        """
        self._record_types = list(record_types)
        return self

    def where(self, filter_component: QueryComponent) -> QueryBuilder:
        """Add a filter predicate.

        Args:
            filter_component: The filter to apply.

        Returns:
            This builder for chaining.
        """
        if self._filter is None:
            self._filter = filter_component
        else:
            self._filter = self._filter.and_(filter_component)
        return self

    def sort(self, key_expression: KeyExpression, reverse: bool = False) -> QueryBuilder:
        """Set the sort order.

        Args:
            key_expression: The expression to sort by.
            reverse: If True, sort descending.

        Returns:
            This builder for chaining.
        """
        self._sort = SortDescriptor(key_expression, reverse)
        return self

    def distinct(self) -> QueryBuilder:
        """Remove duplicates from results.

        Returns:
            This builder for chaining.
        """
        self._removes_duplicates = True
        return self

    def build(self) -> RecordQuery:
        """Build the query.

        Returns:
            The constructed RecordQuery.
        """
        return RecordQuery(
            record_types=self._record_types,
            filter=self._filter,
            sort=self._sort,
            removes_duplicates=self._removes_duplicates,
        )


class BoundRecordQuery:
    """A query bound to specific parameter values.

    BoundRecordQuery holds both the query definition and the
    parameter bindings needed to execute it.

    Attributes:
        query: The query definition.
        bindings: Parameter name to value mappings.
    """

    def __init__(
        self,
        query: RecordQuery,
        bindings: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with query and bindings.

        Args:
            query: The query definition.
            bindings: Parameter bindings.
        """
        self.query = query
        self.bindings = bindings or {}

    def bind(self, name: str, value: Any) -> BoundRecordQuery:
        """Add a parameter binding.

        Args:
            name: The parameter name.
            value: The parameter value.

        Returns:
            A new BoundRecordQuery with the binding added.
        """
        new_bindings = {**self.bindings, name: value}
        return BoundRecordQuery(self.query, new_bindings)

    def bind_all(self, bindings: dict[str, Any]) -> BoundRecordQuery:
        """Add multiple parameter bindings.

        Args:
            bindings: Parameter name to value mappings.

        Returns:
            A new BoundRecordQuery with bindings added.
        """
        new_bindings = {**self.bindings, **bindings}
        return BoundRecordQuery(self.query, new_bindings)

    def get_binding(self, name: str) -> Any:
        """Get a parameter binding.

        Args:
            name: The parameter name.

        Returns:
            The bound value.

        Raises:
            KeyError: If the parameter is not bound.
        """
        return self.bindings[name]

    def has_binding(self, name: str) -> bool:
        """Check if a parameter is bound.

        Args:
            name: The parameter name.

        Returns:
            True if the parameter is bound.
        """
        return name in self.bindings
