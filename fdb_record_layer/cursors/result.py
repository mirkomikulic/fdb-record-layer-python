"""Cursor result types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class NoNextReason(str, Enum):
    """Reason why a cursor has no more results.

    In-band reasons (data-related):
        SOURCE_EXHAUSTED: All records have been consumed.
        RETURN_LIMIT_REACHED: The requested limit was reached.

    Out-of-band reasons (environment-related):
        TIME_LIMIT_REACHED: Time limit for the transaction was reached.
        SCAN_LIMIT_REACHED: Scan limit was reached.
        BYTE_LIMIT_REACHED: Byte limit was reached.
    """

    # In-band reasons
    SOURCE_EXHAUSTED = "source_exhausted"
    RETURN_LIMIT_REACHED = "return_limit_reached"

    # Out-of-band reasons
    TIME_LIMIT_REACHED = "time_limit_reached"
    SCAN_LIMIT_REACHED = "scan_limit_reached"
    BYTE_LIMIT_REACHED = "byte_limit_reached"

    @property
    def is_in_band(self) -> bool:
        """Check if this is an in-band reason."""
        return self in (NoNextReason.SOURCE_EXHAUSTED, NoNextReason.RETURN_LIMIT_REACHED)

    @property
    def is_out_of_band(self) -> bool:
        """Check if this is an out-of-band reason."""
        return not self.is_in_band

    @property
    def is_source_exhausted(self) -> bool:
        """Check if the source is exhausted."""
        return self == NoNextReason.SOURCE_EXHAUSTED


@dataclass(frozen=True)
class RecordCursorContinuation:
    """Opaque continuation token for resuming a cursor.

    Continuations allow cursors to be resumed across transactions,
    enabling efficient pagination and handling of large result sets.

    Attributes:
        data: The serialized continuation data.
        is_end: Whether this represents the end of results.
    """

    data: bytes | None
    is_end: bool = False

    @classmethod
    def start(cls) -> RecordCursorContinuation:
        """Create a continuation representing the start."""
        return cls(data=None, is_end=False)

    @classmethod
    def end(cls) -> RecordCursorContinuation:
        """Create a continuation representing the end."""
        return cls(data=None, is_end=True)

    @classmethod
    def from_bytes(cls, data: bytes) -> RecordCursorContinuation:
        """Create a continuation from bytes."""
        return cls(data=data, is_end=False)

    def to_bytes(self) -> bytes | None:
        """Get the continuation as bytes."""
        return self.data

    def __bool__(self) -> bool:
        """True if this continuation can be used to resume."""
        return not self.is_end


# Singleton for start/end
_START = RecordCursorContinuation.start()
_END = RecordCursorContinuation.end()


@dataclass(frozen=True)
class RecordCursorResult(Generic[T]):
    """Result from a single cursor iteration.

    Each call to next() on a RecordCursor returns one of these,
    containing either a value or information about why iteration stopped.

    Attributes:
        value: The record value, or None if no more results.
        has_next: Whether there are more results after this one.
        continuation: Token for resuming the cursor.
        no_next_reason: Why there are no more results (if has_next is False).
    """

    value: T | None
    has_next: bool
    continuation: RecordCursorContinuation
    no_next_reason: NoNextReason | None = None

    @classmethod
    def with_value(
        cls,
        value: T,
        continuation: RecordCursorContinuation | None = None,
    ) -> RecordCursorResult[T]:
        """Create a result with a value.

        Args:
            value: The record value.
            continuation: Optional continuation for resuming.

        Returns:
            A result containing the value.
        """
        return cls(
            value=value,
            has_next=True,
            continuation=continuation or _START,
            no_next_reason=None,
        )

    @classmethod
    def with_next(
        cls,
        value: T,
        continuation: RecordCursorContinuation,
    ) -> RecordCursorResult[T]:
        """Create a result with a value and continuation.

        Args:
            value: The record value.
            continuation: The continuation for resuming.

        Returns:
            A result containing the value.
        """
        return cls(
            value=value,
            has_next=True,
            continuation=continuation,
            no_next_reason=None,
        )

    @classmethod
    def end(
        cls,
        continuation: RecordCursorContinuation | None = None,
        reason: NoNextReason = NoNextReason.SOURCE_EXHAUSTED,
    ) -> RecordCursorResult[T]:
        """Create a result indicating no more values.

        Args:
            continuation: Optional continuation for resuming (for out-of-band stops).
            reason: The reason for stopping.

        Returns:
            A result indicating no more values.
        """
        return cls(
            value=None,
            has_next=False,
            continuation=continuation or _END,
            no_next_reason=reason,
        )

    @property
    def is_end(self) -> bool:
        """Check if this is the end of results."""
        return not self.has_next and self.value is None

    @property
    def can_continue(self) -> bool:
        """Check if the cursor can be continued from this point."""
        return bool(self.continuation)
