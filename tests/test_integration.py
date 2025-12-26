"""Integration tests for the FDB Record Layer.

These tests verify end-to-end functionality across multiple components.
They use mocked FDB to allow testing without a running database.
"""

from unittest.mock import MagicMock

import pytest

# Ensure FDB is mocked before imports


class MockValue:
    """Mock FDB value."""

    def __init__(self, data: bytes | None = None):
        self._data = data

    def present(self) -> bool:
        return self._data is not None

    def __bytes__(self) -> bytes:
        return self._data or b""


class MockTransaction:
    """Mock FDB transaction for integration testing."""

    def __init__(self):
        self._data: dict[bytes, bytes] = {}
        self._committed = False

    def __getitem__(self, key: bytes) -> MockValue:
        return MockValue(self._data.get(key))

    def set(self, key: bytes, value: bytes) -> None:
        self._data[key] = value

    def clear(self, key: bytes) -> None:
        self._data.pop(key, None)

    def get_range(self, start: bytes, end: bytes, limit: int = 0):
        items = [(k, v) for k, v in sorted(self._data.items()) if start <= k < end]
        if limit:
            items = items[:limit]
        return items

    def add(self, key: bytes, value: bytes) -> None:
        import struct

        existing = self._data.get(key, b"\x00\x00\x00\x00\x00\x00\x00\x00")
        existing_val = struct.unpack("<q", existing)[0]
        new_val = struct.unpack("<q", value)[0]
        self._data[key] = struct.pack("<q", existing_val + new_val)

    def commit(self):
        mock_future = MagicMock()
        mock_future.wait = MagicMock()
        self._committed = True
        return mock_future

    def get_committed_version(self):
        return 12345

    def cancel(self):
        pass


class MockDatabase:
    """Mock FDB database."""

    def __init__(self):
        self._transaction = MockTransaction()

    def create_transaction(self):
        return self._transaction


class MockSubspace:
    """Mock FDB subspace."""

    def __init__(self, prefix: tuple = ()):
        self._prefix = prefix

    def __getitem__(self, key):
        if isinstance(key, tuple):
            return MockSubspace(self._prefix + key)
        return MockSubspace(self._prefix + (key,))

    def pack(self, key):
        if isinstance(key, tuple):
            full = self._prefix + key
        else:
            full = self._prefix + (key,)
        return repr(full).encode()

    def unpack(self, key: bytes):
        full = eval(key.decode())
        return full[len(self._prefix) :]

    def range(self):
        mock = MagicMock()
        mock.start = repr(self._prefix).encode() + b"\x00"
        mock.stop = repr(self._prefix).encode() + b"\xff"
        return mock


class MockFieldDescriptor:
    """Mock protobuf field descriptor."""

    def __init__(self, name: str, label: int = 1):
        self.name = name
        # label: 1=OPTIONAL, 2=REQUIRED, 3=REPEATED
        self.label = label


class MockDescriptor:
    """Mock protobuf descriptor."""

    def __init__(self, name="TestRecord"):
        self.name = name
        # Provide empty fields list by default
        self.fields = []

    def add_field(self, name: str, label: int = 1):
        self.fields.append(MockFieldDescriptor(name, label))


class MockRecord:
    """Mock protobuf record."""

    def __init__(self, **kwargs):
        self.DESCRIPTOR = MockDescriptor(kwargs.pop("_type", "TestRecord"))
        for k, v in kwargs.items():
            setattr(self, k, v)

    def SerializeToString(self):  # noqa: N802
        import json

        data = {
            k: v for k, v in self.__dict__.items() if not k.startswith("_") and k != "DESCRIPTOR"
        }
        return json.dumps(data).encode()


class MockSerializer:
    """Mock record serializer."""

    def serialize(self, record):
        import json

        data = {
            k: v for k, v in record.__dict__.items() if not k.startswith("_") and k != "DESCRIPTOR"
        }
        return json.dumps(data).encode()

    def deserialize(self, data: bytes, descriptor):
        import json

        obj = json.loads(data.decode())
        record = MockRecord(**obj)
        record.DESCRIPTOR = descriptor
        return record


class MockKeyExpression:
    """Mock key expression."""

    def __init__(self, field_name="id"):
        self.field_name = field_name

    def evaluate(self, record):
        value = getattr(record, self.field_name, None)
        if value is None:
            return []
        return [(value,)]

    def get_column_size(self):
        return 1


class MockRecordType:
    """Mock record type."""

    def __init__(self, name="TestRecord", pk_field="id"):
        self.name = name
        self.primary_key = MockKeyExpression(pk_field)
        self.descriptor = MockDescriptor(name)


class MockIndex:
    """Mock index definition."""

    def __init__(self, name, field, record_types=None):
        self.name = name
        self.root_expression = MockKeyExpression(field)
        self.record_types = record_types
        self.options = MagicMock()
        self.options.__dict__ = {}


class MockMetaData:
    """Mock record metadata."""

    def __init__(self, record_types=None, indexes=None):
        self._record_types = record_types or {
            "Person": MockRecordType("Person"),
        }
        self.indexes = indexes or {}

    def has_record_type(self, name):
        return name in self._record_types

    def get_record_type(self, name):
        return self._record_types[name]

    def get_indexes_for_record_type(self, name):
        return [idx for idx in self.indexes.values() if name in (idx.record_types or [])]

    @property
    def record_types(self):
        return self._record_types


class TestQueryBuilderIntegration:
    """Integration tests for query builder."""

    def test_query_builder_creates_valid_query(self):
        """Test that Query builder creates executable queries."""
        from fdb_record_layer.query.query import RecordQuery

        query = RecordQuery(
            record_types=["Person"],
            filter=None,
            sort=None,
        )

        assert query.record_types == ["Person"]

    def test_query_with_filter(self):
        """Test creating a query with a filter."""
        from fdb_record_layer.query.comparisons import Comparison, ComparisonType
        from fdb_record_layer.query.components import FieldComponent
        from fdb_record_layer.query.query import RecordQuery

        filter_comp = FieldComponent("age", Comparison(ComparisonType.GREATER_THAN, 21))

        query = RecordQuery(
            record_types=["Person"],
            filter=filter_comp,
            sort=None,
        )

        assert query.filter is not None


class TestPlannerIntegration:
    """Integration tests for query planner."""

    def test_heuristic_planner_creates_scan_plan(self):
        """Test heuristic planner creates appropriate plan."""
        from fdb_record_layer.planner.heuristic import HeuristicPlanner
        from fdb_record_layer.query.query import RecordQuery

        metadata = MockMetaData()
        planner = HeuristicPlanner(metadata)

        query = RecordQuery(record_types=["Person"], filter=None, sort=None)
        plan = planner.plan(query)

        # Without a filter, should create a scan plan
        assert plan is not None
        assert plan.has_full_scan() is True

    def test_planner_explain(self):
        """Test planner explain output."""
        from fdb_record_layer.planner.heuristic import HeuristicPlanner
        from fdb_record_layer.query.query import RecordQuery

        metadata = MockMetaData()
        planner = HeuristicPlanner(metadata)

        query = RecordQuery(record_types=["Person"], filter=None, sort=None)
        explanation = planner.explain(query)

        assert isinstance(explanation, str)
        assert len(explanation) > 0


class TestCascadesPlannerIntegration:
    """Integration tests for Cascades planner."""

    def test_cascades_creates_plan(self):
        """Test Cascades planner creates valid plans."""
        from fdb_record_layer.planner.cascades.planner import CascadesPlanner
        from fdb_record_layer.query.query import RecordQuery

        metadata = MockMetaData()
        planner = CascadesPlanner(metadata)

        query = RecordQuery(record_types=["Person"], filter=None, sort=None)
        plan = planner.plan(query)

        assert plan is not None

    def test_cascades_explain(self):
        """Test Cascades planner explanation."""
        from fdb_record_layer.planner.cascades.planner import CascadesPlanner
        from fdb_record_layer.query.query import RecordQuery

        metadata = MockMetaData()
        planner = CascadesPlanner(metadata)

        query = RecordQuery(record_types=["Person"], filter=None, sort=None)
        explanation = planner.explain(query)

        assert "Cascades" in explanation


class TestRetryLogicIntegration:
    """Integration tests for retry logic."""

    def test_retry_config_in_context(self):
        """Test RetryConfig works with FDBRecordContext."""
        from fdb_record_layer.core.context import DEFAULT_RETRY_CONFIG, RetryConfig

        config = RetryConfig(
            max_retries=5,
            timeout_seconds=30.0,
        )

        assert config.max_retries == 5
        assert config.timeout_seconds == 30.0
        assert DEFAULT_RETRY_CONFIG.max_retries == 10

    def test_backoff_calculation(self):
        """Test exponential backoff calculation."""
        from fdb_record_layer.core.context import RetryConfig

        config = RetryConfig(
            initial_delay_ms=100,
            max_delay_ms=5000,
            backoff_multiplier=2.0,
        )

        # Check exponential growth
        delays = [config.calculate_delay(i) for i in range(10)]

        # First delay should be 100ms
        assert delays[0] == pytest.approx(0.1)

        # Should increase exponentially
        for i in range(1, len(delays) - 1):
            assert delays[i] >= delays[i - 1] or delays[i] == 5.0  # Capped at max


class TestCursorIntegration:
    """Integration tests for cursors."""

    @pytest.mark.asyncio
    async def test_list_cursor_iteration(self):
        """Test ListCursor iteration."""
        from fdb_record_layer.cursors.base import ListCursor

        items = [1, 2, 3, 4, 5]
        cursor = ListCursor(items)

        results = []
        async for item in cursor:
            results.append(item)

        assert results == items

    @pytest.mark.asyncio
    async def test_cursor_continuation(self):
        """Test cursor continuation handling."""
        from fdb_record_layer.cursors.base import ListCursor
        from fdb_record_layer.cursors.result import RecordCursorContinuation

        items = [1, 2, 3]
        continuation = RecordCursorContinuation.from_bytes(b"test_continuation")
        cursor = ListCursor(items, continuation)

        results = []
        async for item in cursor:
            results.append(item)

        assert results == items


class TestExpressionIntegration:
    """Integration tests for key expressions."""

    def test_field_expression_evaluation(self):
        """Test FieldKeyExpression evaluation."""
        from fdb_record_layer.expressions.field import FieldKeyExpression

        expr = FieldKeyExpression("name")

        # Test with mock record
        record = MockRecord(name="Alice", age=30)
        values = expr.evaluate(record)

        assert values == [("Alice",)]

    def test_concat_expression_evaluation(self):
        """Test ConcatenateKeyExpression evaluation."""
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression
        from fdb_record_layer.expressions.field import FieldKeyExpression

        expr1 = FieldKeyExpression("first_name")
        expr2 = FieldKeyExpression("last_name")
        concat = ConcatenateKeyExpression([expr1, expr2])

        record = MockRecord(first_name="Alice", last_name="Smith")
        values = concat.evaluate(record)

        # Should combine the values
        assert len(values) > 0


class TestMetaDataIntegration:
    """Integration tests for metadata operations."""

    def test_record_metadata_builder(self):
        """Test RecordMetaDataBuilder requires a file_descriptor."""
        from unittest.mock import MagicMock

        from fdb_record_layer.metadata.meta_data_builder import RecordMetaDataBuilder

        # RecordMetaDataBuilder requires a file_descriptor
        mock_file_descriptor = MagicMock()
        mock_file_descriptor.message_types_by_name = {}

        builder = RecordMetaDataBuilder(mock_file_descriptor)

        # Should be able to create metadata
        metadata = builder.build()
        assert metadata is not None

    def test_index_state_enum(self):
        """Test IndexState enum values."""
        from fdb_record_layer.metadata.index import IndexState

        assert IndexState.READABLE.value == "readable"
        assert IndexState.WRITE_ONLY.value == "write_only"
        assert IndexState.DISABLED.value == "disabled"


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""

    @pytest.mark.asyncio
    async def test_save_and_query_workflow(self):
        """Test complete save and query workflow with mocks."""
        # This test verifies the integration between components
        # without requiring a real FDB instance

        from fdb_record_layer.planner.heuristic import HeuristicPlanner
        from fdb_record_layer.query.query import RecordQuery

        # Set up metadata
        metadata = MockMetaData()

        # Create a query
        query = RecordQuery(record_types=["Person"], filter=None, sort=None)

        # Plan the query
        planner = HeuristicPlanner(metadata)
        plan = planner.plan(query)

        # Verify plan was created
        assert plan is not None
        assert plan.has_full_scan() is True

    def test_explain_plan_output(self):
        """Test that explain produces readable output."""
        from fdb_record_layer.planner.heuristic import HeuristicPlanner
        from fdb_record_layer.query.query import RecordQuery

        metadata = MockMetaData()
        planner = HeuristicPlanner(metadata)

        query = RecordQuery(record_types=["Person"], filter=None, sort=None)
        explanation = planner.explain(query)

        # Should contain plan information
        assert len(explanation) > 0
        assert "Scan" in explanation or "Plan" in explanation.lower()


class TestSQLIntegration:
    """Integration tests for SQL support."""

    def test_sql_lexer_tokenizes(self):
        """Test SQL lexer produces tokens."""
        from fdb_record_layer.relational.sql.lexer import Lexer

        lexer = Lexer("SELECT * FROM users")
        tokens = list(lexer.tokenize())

        assert len(tokens) > 0

    def test_sql_parser_parses_select(self):
        """Test SQL parser handles SELECT statements."""
        from fdb_record_layer.relational.sql.parser import Parser

        parser = Parser("SELECT * FROM users")
        ast = parser.parse()

        assert ast is not None


class TestExceptionHierarchy:
    """Tests for exception hierarchy."""

    def test_exception_inheritance(self):
        """Test exception classes inherit correctly."""
        from fdb_record_layer.core.exceptions import (
            RecordLayerException,
            RecordNotFoundException,
            TransactionConflictError,
            TransactionException,
            TransactionRetryLimitExceeded,
        )

        # All exceptions should inherit from RecordLayerException
        assert issubclass(RecordNotFoundException, RecordLayerException)
        assert issubclass(TransactionException, RecordLayerException)
        assert issubclass(TransactionConflictError, TransactionException)
        assert issubclass(TransactionRetryLimitExceeded, TransactionException)

    def test_exception_messages(self):
        """Test exception messages are informative."""
        from fdb_record_layer.core.exceptions import (
            RecordNotFoundException,
            TransactionRetryLimitExceeded,
            TransactionTimeoutError,
        )

        exc1 = RecordNotFoundException("Person", (123,))
        assert "Person" in str(exc1)
        assert "123" in str(exc1)

        exc2 = TransactionRetryLimitExceeded(5)
        assert "5" in str(exc2)

        exc3 = TransactionTimeoutError(30.0)
        assert "30.0" in str(exc3)


class TestComponentInteraction:
    """Tests for interactions between components."""

    def test_planner_uses_metadata(self):
        """Test that planner correctly uses metadata."""
        from fdb_record_layer.planner.heuristic import HeuristicPlanner
        from fdb_record_layer.query.query import RecordQuery

        # Create metadata with an index
        index = MockIndex("Person$age", "age", ["Person"])
        metadata = MockMetaData(indexes={"Person$age": index})

        planner = HeuristicPlanner(metadata)
        query = RecordQuery(record_types=["Person"], filter=None, sort=None)

        plan = planner.plan(query)
        assert plan is not None

    def test_context_transaction_lifecycle(self):
        """Test context transaction lifecycle."""
        from fdb_record_layer.core.context import FDBRecordContext

        mock_db = MockDatabase()
        ctx = FDBRecordContext(database=mock_db)

        # Should be able to get transaction
        tr = ctx.transaction
        assert tr is not None

        # Should be active
        ctx.ensure_active()

        # After close, should not be active
        ctx.close()
        assert ctx.is_closed

        with pytest.raises(RuntimeError):
            ctx.ensure_active()
