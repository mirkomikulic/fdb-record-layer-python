"""Custom exceptions for the FDB Record Layer."""

from __future__ import annotations


class RecordLayerException(Exception):
    """Base exception for all Record Layer errors."""

    pass


class RecordNotFoundException(RecordLayerException):
    """Raised when a record is not found."""

    def __init__(self, record_type: str, primary_key: tuple) -> None:
        self.record_type = record_type
        self.primary_key = primary_key
        super().__init__(f"Record not found: {record_type} with key {primary_key}")


class RecordTypeNotFoundException(RecordLayerException):
    """Raised when a record type is not found in metadata."""

    def __init__(self, record_type: str) -> None:
        self.record_type = record_type
        super().__init__(f"Unknown record type: {record_type}")


class IndexNotFoundException(RecordLayerException):
    """Raised when an index is not found."""

    def __init__(self, index_name: str) -> None:
        self.index_name = index_name
        super().__init__(f"Unknown index: {index_name}")


class InvalidPrimaryKeyException(RecordLayerException):
    """Raised when a primary key expression evaluates incorrectly."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class MetaDataException(RecordLayerException):
    """Raised for metadata-related errors."""

    pass


class MetaDataVersionMismatchError(MetaDataException):
    """Raised when metadata version doesn't match expected version."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Metadata version mismatch: expected {expected}, got {actual}")


class SchemaEvolutionException(MetaDataException):
    """Raised when a schema evolution is invalid."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Invalid schema evolution: {'; '.join(errors)}")


class IndexStateException(RecordLayerException):
    """Raised for index state-related errors."""

    def __init__(self, index_name: str, current_state: str, expected_state: str) -> None:
        self.index_name = index_name
        self.current_state = current_state
        self.expected_state = expected_state
        super().__init__(
            f"Index {index_name} is in state {current_state}, expected {expected_state}"
        )


class QueryException(RecordLayerException):
    """Raised for query-related errors."""

    pass


class QueryPlanException(QueryException):
    """Raised when query planning fails."""

    pass


class SerializationException(RecordLayerException):
    """Raised for serialization/deserialization errors."""

    pass


class ContinuationException(RecordLayerException):
    """Raised for continuation-related errors."""

    pass


class TransactionException(RecordLayerException):
    """Base exception for transaction-related errors."""

    pass


class TransactionConflictError(TransactionException):
    """Raised when a transaction conflicts with another transaction.

    This error is retryable - the operation should be retried with a new transaction.
    """

    def __init__(self, message: str = "Transaction conflict") -> None:
        super().__init__(message)


class TransactionRetryLimitExceeded(TransactionException):
    """Raised when transaction retry limit is exceeded.

    This indicates that after multiple retry attempts, the transaction
    still could not be committed successfully.
    """

    def __init__(self, attempts: int, last_error: Exception | None = None) -> None:
        self.attempts = attempts
        self.last_error = last_error
        msg = f"Transaction failed after {attempts} attempts"
        if last_error:
            msg += f": {last_error}"
        super().__init__(msg)


class TransactionTimeoutError(TransactionException):
    """Raised when a transaction times out."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Transaction timed out after {timeout_seconds}s")
