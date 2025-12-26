"""Tests for query execution plans."""

from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure FDB is mocked before imports


class MockStoredRecord:
    """Mock FDBStoredRecord for testing."""

    def __init__(self, primary_key, record, record_type=None):
        self.primary_key = primary_key
        self.record = record
        self.record_type = record_type or MagicMock()


class MockRecord:
    """Mock protobuf record for testing."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockRecordType:
    """Mock record type."""

    def __init__(self, name="TestRecord"):
        self.name = name


class MockSubspace:
    """Mock FDB subspace."""

    def __init__(self, prefix=()):
        self._prefix = prefix

    def __getitem__(self, key):
        return MockSubspace(self._prefix + (key,))

    def pack(self, key):
        if isinstance(key, tuple):
            return str(self._prefix + (key,)).encode()
        return str(self._prefix + ((key,),)).encode()

    def unpack(self, key):
        return (1,)  # Simplified for testing

    def range(self):
        mock = MagicMock()
        mock.start = b"\x00"
        mock.stop = b"\xff"
        return mock


class MockMetaData:
    """Mock record metadata."""

    def __init__(self, record_types=None):
        self._record_types = record_types or {"TestRecord": MockRecordType()}

    def has_record_type(self, name):
        return name in self._record_types


class MockStore:
    """Mock FDBRecordStore for testing."""

    def __init__(self, records=None):
        self._records = records or []
        self._records_subspace = MockSubspace(("records",))
        self.meta_data = MockMetaData()
        self._transaction = MagicMock()
        self._transaction.get_range = MagicMock(return_value=[])

    @property
    def transaction(self):
        return self._transaction

    def _load_record_sync(self, record_type, pk):
        for r in self._records:
            if r.primary_key == pk:
                return r
        return None


class MockContext:
    """Mock ExecutionContext for testing."""

    def __init__(self, store=None):
        self.store = store or MockStore()
        self.bindings = None

    @property
    def transaction(self):
        return self.store.transaction


class TestPlanComplexity:
    """Tests for PlanComplexity."""

    def test_default_values(self):
        """Test default complexity values."""
        from fdb_record_layer.plans.base import PlanComplexity

        complexity = PlanComplexity()

        assert complexity.estimated_rows == 0
        assert complexity.index_scans == 0
        assert complexity.full_scans == 0
        assert complexity.filter_complexity == 0

    def test_total_cost_no_scans(self):
        """Test total cost with no scans."""
        from fdb_record_layer.plans.base import PlanComplexity

        complexity = PlanComplexity(estimated_rows=100)
        cost = complexity.total_cost()

        # 100 rows * 10 = 1000
        assert cost == 1000

    def test_total_cost_with_full_scan(self):
        """Test total cost with full scan."""
        from fdb_record_layer.plans.base import PlanComplexity

        complexity = PlanComplexity(estimated_rows=100, full_scans=1)
        cost = complexity.total_cost()

        # 1 full scan * 1000000 + 100 rows * 10 = 1001000
        assert cost == 1001000

    def test_total_cost_with_index_scan(self):
        """Test total cost with index scan."""
        from fdb_record_layer.plans.base import PlanComplexity

        complexity = PlanComplexity(estimated_rows=100, index_scans=1)
        cost = complexity.total_cost()

        # 1 index scan * 100 + 100 rows * 10 = 1100
        assert cost == 1100

    def test_total_cost_with_filter(self):
        """Test total cost with filter complexity."""
        from fdb_record_layer.plans.base import PlanComplexity

        complexity = PlanComplexity(estimated_rows=100, filter_complexity=5)
        cost = complexity.total_cost()

        # 100 rows * 10 + 100 rows * 5 = 1500
        assert cost == 1500

    def test_complexity_comparison(self):
        """Test comparing complexities."""
        from fdb_record_layer.plans.base import PlanComplexity

        simple = PlanComplexity(estimated_rows=100, index_scans=1)
        expensive = PlanComplexity(estimated_rows=100, full_scans=1)

        assert simple < expensive
        assert not expensive < simple


class TestEmptyPlan:
    """Tests for EmptyPlan."""

    @pytest.mark.asyncio
    async def test_execute_returns_empty_cursor(self):
        """Test that EmptyPlan returns an empty cursor."""
        from fdb_record_layer.plans.base import EmptyPlan

        plan = EmptyPlan()
        context = MockContext()

        cursor = await plan.execute(context)

        results = []
        async for item in cursor:
            results.append(item)

        assert results == []

    def test_explain(self):
        """Test EmptyPlan explanation."""
        from fdb_record_layer.plans.base import EmptyPlan

        plan = EmptyPlan()

        assert plan.explain() == "Empty()"
        assert plan.explain(indent=2) == "  Empty()"

    def test_complexity_is_zero(self):
        """Test EmptyPlan has zero complexity."""
        from fdb_record_layer.plans.base import EmptyPlan

        plan = EmptyPlan()
        complexity = plan.get_complexity()

        assert complexity.total_cost() == 0


class TestScanPlan:
    """Tests for ScanPlan."""

    def test_initialization(self):
        """Test ScanPlan initialization."""
        from fdb_record_layer.plans.scan_plan import ScanPlan

        plan = ScanPlan(record_types=["Person", "Company"])

        assert plan.record_types == ["Person", "Company"]

    def test_has_full_scan(self):
        """Test ScanPlan reports as full scan."""
        from fdb_record_layer.plans.scan_plan import ScanPlan

        plan = ScanPlan(record_types=["Person"])

        assert plan.has_full_scan() is True

    def test_explain(self):
        """Test ScanPlan explanation."""
        from fdb_record_layer.plans.scan_plan import ScanPlan

        plan = ScanPlan(record_types=["Person", "Order"])

        explanation = plan.explain()
        assert "Scan" in explanation
        assert "Person" in explanation
        assert "Order" in explanation

    def test_complexity(self):
        """Test ScanPlan complexity."""
        from fdb_record_layer.plans.scan_plan import ScanPlan

        plan = ScanPlan(record_types=["Person"])
        complexity = plan.get_complexity()

        assert complexity.full_scans == 1
        assert complexity.estimated_rows > 0


class TestTypeScanPlan:
    """Tests for TypeScanPlan."""

    def test_initialization(self):
        """Test TypeScanPlan initialization."""
        from fdb_record_layer.plans.scan_plan import TypeScanPlan

        plan = TypeScanPlan(record_type="Person")

        assert plan.record_type == "Person"

    def test_has_full_scan(self):
        """Test TypeScanPlan reports as full scan."""
        from fdb_record_layer.plans.scan_plan import TypeScanPlan

        plan = TypeScanPlan(record_type="Person")

        assert plan.has_full_scan() is True

    def test_explain(self):
        """Test TypeScanPlan explanation."""
        from fdb_record_layer.plans.scan_plan import TypeScanPlan

        plan = TypeScanPlan(record_type="Order")

        explanation = plan.explain()
        assert "TypeScan" in explanation
        assert "Order" in explanation


class TestFilterPlan:
    """Tests for FilterPlan."""

    def test_initialization(self):
        """Test FilterPlan initialization."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.filter_plan import FilterPlan

        child = EmptyPlan()
        filter_component = MagicMock()

        plan = FilterPlan(child=child, filter_component=filter_component)

        assert plan.child is child

    def test_has_full_scan_delegates(self):
        """Test FilterPlan delegates has_full_scan to child."""
        from fdb_record_layer.plans.filter_plan import FilterPlan
        from fdb_record_layer.plans.scan_plan import ScanPlan

        child = ScanPlan(record_types=["Person"])
        plan = FilterPlan(child=child, filter_component=MagicMock())

        assert plan.has_full_scan() is True

    def test_explain(self):
        """Test FilterPlan explanation."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.filter_plan import FilterPlan

        child = EmptyPlan()
        plan = FilterPlan(child=child, filter_component=MagicMock())

        explanation = plan.explain()
        assert "Filter" in explanation

    @pytest.mark.asyncio
    async def test_execute_filters_records(self):
        """Test FilterPlan filters records based on predicate."""
        from fdb_record_layer.cursors.base import ListCursor
        from fdb_record_layer.plans.filter_plan import FilterPlan

        # Create a child plan that returns records
        records = [
            MockStoredRecord((1,), MockRecord(age=25)),
            MockStoredRecord((2,), MockRecord(age=30)),
            MockStoredRecord((3,), MockRecord(age=20)),
        ]

        # Mock a child plan
        child = MagicMock()
        child.execute = AsyncMock(return_value=ListCursor(records))
        child.has_full_scan = MagicMock(return_value=False)
        child.uses_index = MagicMock(return_value=False)
        child.get_used_indexes = MagicMock(return_value=set())

        # Filter for age > 22
        # The evaluate receives the record (not stored record), so check r.age directly
        filter_component = MagicMock()
        filter_component.evaluate = lambda r, bindings=None: r.age > 22

        plan = FilterPlan(child=child, filter_component=filter_component)
        context = MockContext()

        cursor = await plan.execute(context)

        results = []
        async for item in cursor:
            results.append(item)

        assert len(results) == 2
        assert results[0].record.age == 25
        assert results[1].record.age == 30


class TestIndexScanPlan:
    """Tests for IndexScanPlan."""

    def test_initialization(self):
        """Test IndexScanPlan initialization."""
        from fdb_record_layer.plans.index_plan import IndexScanPlan

        plan = IndexScanPlan(
            index_name="Person$email",
            scan_comparisons=MagicMock(),
            reverse=False,
        )

        assert plan._index_name == "Person$email"
        assert plan._reverse is False

    def test_uses_index(self):
        """Test IndexScanPlan reports index usage."""
        from fdb_record_layer.plans.index_plan import IndexScanPlan

        plan = IndexScanPlan(
            index_name="Person$email",
            scan_comparisons=MagicMock(),
        )

        assert plan.uses_index("Person$email") is True
        assert plan.uses_index("Person$age") is False

    def test_get_used_indexes(self):
        """Test IndexScanPlan returns used indexes."""
        from fdb_record_layer.plans.index_plan import IndexScanPlan

        plan = IndexScanPlan(
            index_name="Order$customer_id",
            scan_comparisons=MagicMock(),
        )

        indexes = plan.get_used_indexes()
        assert "Order$customer_id" in indexes

    def test_has_full_scan_is_false(self):
        """Test IndexScanPlan is not a full scan."""
        from fdb_record_layer.plans.index_plan import IndexScanPlan

        plan = IndexScanPlan(
            index_name="Person$email",
            scan_comparisons=MagicMock(),
        )

        assert plan.has_full_scan() is False

    def test_explain(self):
        """Test IndexScanPlan explanation."""
        from fdb_record_layer.plans.index_plan import IndexScanPlan

        plan = IndexScanPlan(
            index_name="Person$email",
            scan_comparisons=MagicMock(),
            reverse=True,
        )

        explanation = plan.explain()
        assert "IndexScan" in explanation
        assert "Person$email" in explanation


class TestUnionPlan:
    """Tests for UnionPlan."""

    def test_initialization(self):
        """Test UnionPlan initialization."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.union_plan import UnionPlan

        child1 = EmptyPlan()
        child2 = EmptyPlan()

        plan = UnionPlan(children=[child1, child2])

        assert len(plan.children) == 2

    def test_has_full_scan_any_child(self):
        """Test UnionPlan has_full_scan if any child does."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.scan_plan import ScanPlan
        from fdb_record_layer.plans.union_plan import UnionPlan

        child1 = EmptyPlan()
        child2 = ScanPlan(record_types=["Person"])

        plan = UnionPlan(children=[child1, child2])

        assert plan.has_full_scan() is True

    def test_get_used_indexes_combines(self):
        """Test UnionPlan combines indexes from all children."""
        from fdb_record_layer.plans.index_plan import IndexScanPlan
        from fdb_record_layer.plans.union_plan import UnionPlan

        child1 = IndexScanPlan(index_name="idx1", scan_comparisons=MagicMock())
        child2 = IndexScanPlan(index_name="idx2", scan_comparisons=MagicMock())

        plan = UnionPlan(children=[child1, child2])

        indexes = plan.get_used_indexes()
        assert "idx1" in indexes
        assert "idx2" in indexes

    def test_explain(self):
        """Test UnionPlan explanation."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.union_plan import UnionPlan

        plan = UnionPlan(children=[EmptyPlan(), EmptyPlan()])

        explanation = plan.explain()
        assert "Union" in explanation

    @pytest.mark.asyncio
    async def test_execute_combines_results(self):
        """Test UnionPlan combines results from children."""
        from fdb_record_layer.cursors.base import ListCursor
        from fdb_record_layer.plans.union_plan import UnionPlan

        records1 = [MockStoredRecord((1,), MockRecord(name="Alice"))]
        records2 = [MockStoredRecord((2,), MockRecord(name="Bob"))]

        child1 = MagicMock()
        child1.execute = AsyncMock(return_value=ListCursor(records1))
        child1.has_full_scan = MagicMock(return_value=False)
        child1.uses_index = MagicMock(return_value=False)
        child1.get_used_indexes = MagicMock(return_value=set())

        child2 = MagicMock()
        child2.execute = AsyncMock(return_value=ListCursor(records2))
        child2.has_full_scan = MagicMock(return_value=False)
        child2.uses_index = MagicMock(return_value=False)
        child2.get_used_indexes = MagicMock(return_value=set())

        plan = UnionPlan(children=[child1, child2])
        context = MockContext()

        cursor = await plan.execute(context)

        results = []
        async for item in cursor:
            results.append(item)

        assert len(results) == 2


class TestIntersectionPlan:
    """Tests for IntersectionPlan."""

    def test_initialization(self):
        """Test IntersectionPlan initialization."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.intersection_plan import IntersectionPlan

        child1 = EmptyPlan()
        child2 = EmptyPlan()

        plan = IntersectionPlan(children=[child1, child2])

        assert len(plan.children) == 2

    def test_explain(self):
        """Test IntersectionPlan explanation."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.intersection_plan import IntersectionPlan

        plan = IntersectionPlan(children=[EmptyPlan(), EmptyPlan()])

        explanation = plan.explain()
        assert "Intersection" in explanation

    @pytest.mark.asyncio
    async def test_execute_intersects_results(self):
        """Test IntersectionPlan returns only records in all children."""
        from fdb_record_layer.cursors.base import ListCursor
        from fdb_record_layer.plans.intersection_plan import IntersectionPlan

        # Same primary key in both children
        records1 = [
            MockStoredRecord((1,), MockRecord(name="Alice")),
            MockStoredRecord((2,), MockRecord(name="Bob")),
        ]
        records2 = [
            MockStoredRecord((2,), MockRecord(name="Bob")),
            MockStoredRecord((3,), MockRecord(name="Charlie")),
        ]

        child1 = MagicMock()
        child1.execute = AsyncMock(return_value=ListCursor(records1))
        child1.has_full_scan = MagicMock(return_value=False)
        child1.uses_index = MagicMock(return_value=False)
        child1.get_used_indexes = MagicMock(return_value=set())

        child2 = MagicMock()
        child2.execute = AsyncMock(return_value=ListCursor(records2))
        child2.has_full_scan = MagicMock(return_value=False)
        child2.uses_index = MagicMock(return_value=False)
        child2.get_used_indexes = MagicMock(return_value=set())

        plan = IntersectionPlan(children=[child1, child2])
        context = MockContext()

        cursor = await plan.execute(context)

        results = []
        async for item in cursor:
            results.append(item)

        # Only (2,) is in both
        assert len(results) == 1
        assert results[0].primary_key == (2,)


class TestExecutionContext:
    """Tests for ExecutionContext."""

    def test_initialization(self):
        """Test ExecutionContext initialization."""
        from fdb_record_layer.plans.base import ExecutionContext

        store = MockStore()
        context = ExecutionContext(store=store, bindings={"param": "value"})

        assert context.store is store
        assert context.bindings == {"param": "value"}

    def test_transaction_property(self):
        """Test ExecutionContext transaction property."""
        from fdb_record_layer.plans.base import ExecutionContext

        store = MockStore()
        context = ExecutionContext(store=store)

        assert context.transaction is store.transaction


class TestRecordQueryPlanWithChildren:
    """Tests for RecordQueryPlanWithChildren."""

    def test_children_property(self):
        """Test children property."""
        from fdb_record_layer.plans.base import EmptyPlan
        from fdb_record_layer.plans.union_plan import UnionPlan

        child1 = EmptyPlan()
        child2 = EmptyPlan()
        plan = UnionPlan(children=[child1, child2])

        assert plan.children[0] is child1
        assert plan.children[1] is child2

    def test_uses_index_delegates(self):
        """Test uses_index checks all children."""
        from fdb_record_layer.plans.index_plan import IndexScanPlan
        from fdb_record_layer.plans.union_plan import UnionPlan

        child1 = IndexScanPlan(index_name="idx1", scan_comparisons=MagicMock())
        child2 = IndexScanPlan(index_name="idx2", scan_comparisons=MagicMock())

        plan = UnionPlan(children=[child1, child2])

        assert plan.uses_index("idx1") is True
        assert plan.uses_index("idx2") is True
        assert plan.uses_index("idx3") is False
