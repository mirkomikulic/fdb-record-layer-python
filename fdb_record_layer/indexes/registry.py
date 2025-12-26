"""Index maintainer registry for managing index types."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from fdb_record_layer.indexes.maintainer import IndexMaintainer
from fdb_record_layer.metadata.index import IndexType

if TYPE_CHECKING:
    from fdb import Subspace

    from fdb_record_layer.metadata.index import Index
    from fdb_record_layer.metadata.record_metadata import RecordMetaData


# Type for index maintainer factory functions
MaintainerFactory = Callable[
    ["Index", "Subspace", "RecordMetaData"],
    IndexMaintainer,
]


class IndexMaintainerRegistry:
    """Registry for index maintainer types.

    Maps IndexType values to maintainer classes, allowing the
    record store to create the appropriate maintainer for each index.

    Example:
        >>> registry = IndexMaintainerRegistry.default()
        >>> maintainer = registry.create_maintainer(index, subspace, metadata)
    """

    def __init__(self) -> None:
        self._factories: dict[IndexType, MaintainerFactory] = {}

    def register(
        self,
        index_type: IndexType,
        factory: MaintainerFactory,
    ) -> None:
        """Register a maintainer factory for an index type.

        Args:
            index_type: The index type.
            factory: Factory function to create maintainers.
        """
        self._factories[index_type] = factory

    def register_class(
        self,
        index_type: IndexType,
        maintainer_class: type[IndexMaintainer],
    ) -> None:
        """Register a maintainer class for an index type.

        Args:
            index_type: The index type.
            maintainer_class: The maintainer class.
        """
        self._factories[index_type] = maintainer_class

    def get_factory(
        self,
        index_type: IndexType,
    ) -> MaintainerFactory | None:
        """Get the factory for an index type.

        Args:
            index_type: The index type.

        Returns:
            The factory, or None if not registered.
        """
        return self._factories.get(index_type)

    def create_maintainer(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
    ) -> IndexMaintainer:
        """Create a maintainer for an index.

        Args:
            index: The index definition.
            subspace: The subspace for index storage.
            meta_data: The record metadata.

        Returns:
            The created maintainer.

        Raises:
            ValueError: If no factory is registered for the index type.
        """
        factory = self._factories.get(index.index_type)
        if factory is None:
            raise ValueError(f"No maintainer registered for index type: {index.index_type}")
        return factory(index, subspace, meta_data)

    def has_type(self, index_type: IndexType) -> bool:
        """Check if a type is registered."""
        return index_type in self._factories

    @classmethod
    def default(cls) -> IndexMaintainerRegistry:
        """Create a registry with all built-in index types.

        Returns:
            A registry with VALUE, COUNT, SUM, RANK, and TEXT registered.
        """
        from fdb_record_layer.indexes.count_index import (
            CountIndexMaintainer,
            MinMaxIndexMaintainer,
            SumIndexMaintainer,
        )
        from fdb_record_layer.indexes.rank_index import RankIndexMaintainer
        from fdb_record_layer.indexes.text_index import TextIndexMaintainer
        from fdb_record_layer.indexes.value_index import ValueIndexMaintainer

        registry = cls()

        # Register built-in types
        registry.register_class(IndexType.VALUE, ValueIndexMaintainer)
        registry.register_class(IndexType.COUNT, CountIndexMaintainer)
        registry.register_class(IndexType.SUM, SumIndexMaintainer)
        registry.register_class(IndexType.RANK, RankIndexMaintainer)
        registry.register_class(IndexType.TEXT, TextIndexMaintainer)

        # MIN_EVER and MAX_EVER use MinMaxIndexMaintainer with different config
        registry.register(
            IndexType.MIN_EVER,
            lambda idx, sub, md: MinMaxIndexMaintainer(idx, sub, md, track_max=False),
        )
        registry.register(
            IndexType.MAX_EVER,
            lambda idx, sub, md: MinMaxIndexMaintainer(idx, sub, md, track_max=True),
        )

        return registry


# Global default registry
_default_registry: IndexMaintainerRegistry | None = None


def get_default_registry() -> IndexMaintainerRegistry:
    """Get the default index maintainer registry.

    Returns:
        The default registry with all built-in types.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = IndexMaintainerRegistry.default()
    return _default_registry


def register_index_type(
    index_type: IndexType,
    factory: MaintainerFactory,
) -> None:
    """Register a custom index type in the default registry.

    Args:
        index_type: The index type.
        factory: Factory function to create maintainers.
    """
    get_default_registry().register(index_type, factory)
