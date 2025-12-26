"""Base cursor classes and protocols."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import (
    TYPE_CHECKING,
    Generic,
    TypeVar,
)

from fdb_record_layer.cursors.result import (
    NoNextReason,
    RecordCursorContinuation,
    RecordCursorResult,
)

if TYPE_CHECKING:
    pass

T = TypeVar("T")
U = TypeVar("U")


class RecordCursor(Generic[T], ABC):
    """Abstract base for asynchronous cursors with continuation support.

    RecordCursor is the core abstraction for iterating over query results.
    Unlike standard Python iterators, RecordCursor:
    - Is asynchronous (uses async/await)
    - Supports continuations for resuming across transactions
    - Provides detailed stop reasons

    Subclasses must implement:
    - on_next(): Get the next result
    - get_continuation(): Get the current continuation
    """

    @abstractmethod
    async def on_next(self) -> RecordCursorResult[T]:
        """Get the next result from the cursor.

        Returns:
            A RecordCursorResult containing either a value or stop reason.
        """
        pass

    @abstractmethod
    def get_continuation(self) -> RecordCursorContinuation:
        """Get the current continuation for resuming.

        Returns:
            A continuation that can be used to resume this cursor.
        """
        pass

    async def __anext__(self) -> T:
        """Async iterator protocol."""
        result = await self.on_next()
        if result.value is None:
            raise StopAsyncIteration
        return result.value

    def __aiter__(self) -> AsyncIterator[T]:
        """Async iterator protocol."""
        return self

    async def to_list(self) -> list[T]:
        """Collect all results into a list.

        Warning: This loads all results into memory.

        Returns:
            List of all results.
        """
        results: list[T] = []
        async for item in self:
            results.append(item)
        return results

    async def first(self) -> T | None:
        """Get the first result.

        Returns:
            The first result, or None if empty.
        """
        result = await self.on_next()
        return result.value

    async def first_or_raise(self) -> T:
        """Get the first result or raise an exception.

        Returns:
            The first result.

        Raises:
            StopAsyncIteration: If no results.
        """
        result = await self.first()
        if result is None:
            raise StopAsyncIteration("Cursor is empty")
        return result

    def map(self, func: Callable[[T], U]) -> MapCursor[T, U]:
        """Transform results using a function.

        Args:
            func: Function to apply to each result.

        Returns:
            A new cursor with transformed results.
        """
        return MapCursor(self, func)

    def map_async(self, func: Callable[[T], Awaitable[U]]) -> AsyncMapCursor[T, U]:
        """Transform results using an async function.

        Args:
            func: Async function to apply to each result.

        Returns:
            A new cursor with transformed results.
        """
        return AsyncMapCursor(self, func)

    def filter(self, predicate: Callable[[T], bool]) -> FilterCursor[T]:
        """Filter results using a predicate.

        Args:
            predicate: Function returning True for items to keep.

        Returns:
            A new cursor with filtered results.
        """
        return FilterCursor(self, predicate)

    def filter_async(self, predicate: Callable[[T], Awaitable[bool]]) -> AsyncFilterCursor[T]:
        """Filter results using an async predicate.

        Args:
            predicate: Async function returning True for items to keep.

        Returns:
            A new cursor with filtered results.
        """
        return AsyncFilterCursor(self, predicate)

    def take(self, limit: int) -> LimitCursor[T]:
        """Limit the number of results.

        Args:
            limit: Maximum number of results to return.

        Returns:
            A new cursor with limited results.
        """
        return LimitCursor(self, limit)

    def skip(self, count: int) -> SkipCursor[T]:
        """Skip a number of results.

        Args:
            count: Number of results to skip.

        Returns:
            A new cursor with skipped results.
        """
        return SkipCursor(self, count)


class ListCursor(RecordCursor[T]):
    """A cursor over a pre-computed list of items."""

    def __init__(
        self,
        items: list[T],
        continuation: RecordCursorContinuation | None = None,
    ) -> None:
        self._items = items
        self._index = 0
        self._continuation = continuation or RecordCursorContinuation.start()
        self._done = False

    async def on_next(self) -> RecordCursorResult[T]:
        if self._index < len(self._items):
            value = self._items[self._index]
            self._index += 1

            if self._index >= len(self._items):
                # This is the last item
                return RecordCursorResult.with_next(
                    value,
                    self._continuation if self._continuation else RecordCursorContinuation.end(),
                )
            return RecordCursorResult.with_value(value)

        self._done = True
        return RecordCursorResult.end(
            continuation=self._continuation,
            reason=NoNextReason.SOURCE_EXHAUSTED,
        )

    def get_continuation(self) -> RecordCursorContinuation:
        if self._done:
            return RecordCursorContinuation.end()
        return self._continuation


class MapCursor(RecordCursor[U], Generic[T, U]):
    """A cursor that transforms results."""

    def __init__(self, inner: RecordCursor[T], func: Callable[[T], U]) -> None:
        self._inner = inner
        self._func = func

    async def on_next(self) -> RecordCursorResult[U]:
        result = await self._inner.on_next()
        if result.value is not None:
            transformed = self._func(result.value)
            return RecordCursorResult(
                value=transformed,
                has_next=result.has_next,
                continuation=result.continuation,
                no_next_reason=result.no_next_reason,
            )
        return RecordCursorResult.end(
            continuation=result.continuation,
            reason=result.no_next_reason or NoNextReason.SOURCE_EXHAUSTED,
        )

    def get_continuation(self) -> RecordCursorContinuation:
        return self._inner.get_continuation()


class AsyncMapCursor(RecordCursor[U], Generic[T, U]):
    """A cursor that transforms results asynchronously."""

    def __init__(self, inner: RecordCursor[T], func: Callable[[T], Awaitable[U]]) -> None:
        self._inner = inner
        self._func = func

    async def on_next(self) -> RecordCursorResult[U]:
        result = await self._inner.on_next()
        if result.value is not None:
            transformed = await self._func(result.value)
            return RecordCursorResult(
                value=transformed,
                has_next=result.has_next,
                continuation=result.continuation,
                no_next_reason=result.no_next_reason,
            )
        return RecordCursorResult.end(
            continuation=result.continuation,
            reason=result.no_next_reason or NoNextReason.SOURCE_EXHAUSTED,
        )

    def get_continuation(self) -> RecordCursorContinuation:
        return self._inner.get_continuation()


class FilterCursor(RecordCursor[T]):
    """A cursor that filters results."""

    def __init__(self, inner: RecordCursor[T], predicate: Callable[[T], bool]) -> None:
        self._inner = inner
        self._predicate = predicate

    async def on_next(self) -> RecordCursorResult[T]:
        while True:
            result = await self._inner.on_next()
            if result.value is None:
                return result
            if self._predicate(result.value):
                return result
            # Skip filtered items

    def get_continuation(self) -> RecordCursorContinuation:
        return self._inner.get_continuation()


class AsyncFilterCursor(RecordCursor[T]):
    """A cursor that filters results asynchronously."""

    def __init__(self, inner: RecordCursor[T], predicate: Callable[[T], Awaitable[bool]]) -> None:
        self._inner = inner
        self._predicate = predicate

    async def on_next(self) -> RecordCursorResult[T]:
        while True:
            result = await self._inner.on_next()
            if result.value is None:
                return result
            if await self._predicate(result.value):
                return result
            # Skip filtered items

    def get_continuation(self) -> RecordCursorContinuation:
        return self._inner.get_continuation()


class LimitCursor(RecordCursor[T]):
    """A cursor that limits the number of results."""

    def __init__(self, inner: RecordCursor[T], limit: int) -> None:
        self._inner = inner
        self._limit = limit
        self._count = 0

    async def on_next(self) -> RecordCursorResult[T]:
        if self._count >= self._limit:
            return RecordCursorResult.end(
                continuation=self._inner.get_continuation(),
                reason=NoNextReason.RETURN_LIMIT_REACHED,
            )

        result = await self._inner.on_next()
        if result.value is not None:
            self._count += 1
        return result

    def get_continuation(self) -> RecordCursorContinuation:
        return self._inner.get_continuation()


class SkipCursor(RecordCursor[T]):
    """A cursor that skips a number of results."""

    def __init__(self, inner: RecordCursor[T], count: int) -> None:
        self._inner = inner
        self._skip_count = count
        self._skipped = 0

    async def on_next(self) -> RecordCursorResult[T]:
        # Skip initial items
        while self._skipped < self._skip_count:
            result = await self._inner.on_next()
            if result.value is None:
                return result
            self._skipped += 1

        return await self._inner.on_next()

    def get_continuation(self) -> RecordCursorContinuation:
        return self._inner.get_continuation()


def from_list(items: list[T]) -> ListCursor[T]:
    """Create a cursor from a list.

    Args:
        items: The items to iterate over.

    Returns:
        A ListCursor over the items.
    """
    return ListCursor(items)


def empty_cursor() -> ListCursor[T]:
    """Create an empty cursor.

    Returns:
        An empty ListCursor.
    """
    return ListCursor([])
