"""Integration tests for FDBRecordContext and FDBDatabase."""

import pytest

from fdb_record_layer.core.context import FDBDatabase, FDBRecordContext, RetryConfig
from fdb_record_layer.core.exceptions import TransactionRetryLimitExceeded

pytestmark = pytest.mark.integration


class TestFDBRecordContext:
    """Test FDBRecordContext with real FDB."""

    def test_context_creation(self, fdb_database):
        """Test creating a context."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            assert ctx.database == fdb_database
            assert not ctx.is_closed
            # Transaction is created lazily
            _ = ctx.transaction
            assert ctx._transaction is not None
        finally:
            ctx.close()

    def test_context_close(self, fdb_database):
        """Test closing a context."""
        ctx = FDBRecordContext(database=fdb_database)
        _ = ctx.transaction  # Create transaction

        ctx.close()
        assert ctx.is_closed

        with pytest.raises(RuntimeError, match="closed"):
            ctx.ensure_active()

    def test_context_manager(self, fdb_database):
        """Test context manager protocol."""
        with FDBRecordContext(database=fdb_database) as ctx:
            _ = ctx.transaction
            assert not ctx.is_closed

        assert ctx.is_closed

    @pytest.mark.asyncio
    async def test_get_read_version(self, fdb_database):
        """Test getting read version."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            version = await ctx.get_read_version()
            assert isinstance(version, int)
            assert version > 0

            # Should be cached
            version2 = await ctx.get_read_version()
            assert version2 == version
        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_commit(self, fdb_database, test_subspace):
        """Test committing a transaction."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            # Write some data
            key = test_subspace.pack(("commit_test",))
            ctx.transaction.set(key, b"test_value")

            # Commit
            committed_version = await ctx.commit()
            assert isinstance(committed_version, int)
            assert committed_version > 0
        finally:
            ctx.close()

        # Verify data persisted in new transaction
        ctx2 = FDBRecordContext(database=fdb_database)
        try:
            value = ctx2.transaction[key]
            assert value.present()
            assert bytes(value) == b"test_value"
        finally:
            ctx2.close()

    @pytest.mark.asyncio
    async def test_commit_hooks(self, fdb_database, test_subspace):
        """Test that commit hooks are called."""
        ctx = FDBRecordContext(database=fdb_database)
        hook_called = []

        def my_hook():
            hook_called.append(True)

        try:
            ctx.add_commit_hook(my_hook)

            key = test_subspace.pack(("hook_test",))
            ctx.transaction.set(key, b"hook_value")

            await ctx.commit()

            assert len(hook_called) == 1
        finally:
            ctx.close()

    def test_reset(self, fdb_database):
        """Test resetting a context."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            tr1 = ctx.transaction
            ctx.reset()
            tr2 = ctx.transaction

            # Should be different transaction instances
            assert tr1 is not tr2
        finally:
            ctx.close()


class TestFDBDatabase:
    """Test FDBDatabase with real FDB."""

    def test_database_creation(self, fdb_cluster_file):
        """Test creating a database connection."""
        db = FDBDatabase(fdb_cluster_file)
        assert db.database is not None
        assert db.retry_config is not None

    def test_database_with_custom_retry_config(self, fdb_cluster_file):
        """Test creating database with custom retry config."""
        config = RetryConfig(
            max_retries=5,
            initial_delay_ms=50.0,
            max_delay_ms=500.0,
        )
        db = FDBDatabase(fdb_cluster_file, retry_config=config)
        assert db.retry_config.max_retries == 5
        assert db.retry_config.initial_delay_ms == 50.0

    def test_open_context(self, fdb_cluster_file):
        """Test opening a context."""
        db = FDBDatabase(fdb_cluster_file)
        ctx = db.open_context()
        try:
            assert isinstance(ctx, FDBRecordContext)
            assert not ctx.is_closed
        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_run_simple(self, fdb_cluster_file, test_subspace):
        """Test running a simple transactional function."""
        db = FDBDatabase(fdb_cluster_file)

        async def write_data(ctx: FDBRecordContext):
            key = test_subspace.pack(("run_test",))
            ctx.transaction.set(key, b"run_value")
            return "success"

        result = await db.run(write_data)
        assert result == "success"

        # Verify data persisted
        async def read_data(ctx: FDBRecordContext):
            key = test_subspace.pack(("run_test",))
            value = ctx.transaction[key]
            return bytes(value) if value.present() else None

        value = await db.run(read_data)
        assert value == b"run_value"

    @pytest.mark.asyncio
    async def test_run_sync_function(self, fdb_cluster_file, test_subspace):
        """Test running a sync function with db.run()."""
        db = FDBDatabase(fdb_cluster_file)

        def sync_write(ctx: FDBRecordContext):
            key = test_subspace.pack(("sync_test",))
            ctx.transaction.set(key, b"sync_value")
            return 42

        result = await db.run(sync_write)
        assert result == 42

    @pytest.mark.asyncio
    async def test_run_with_custom_config(self, fdb_cluster_file, test_subspace):
        """Test running with custom retry config."""
        db = FDBDatabase(fdb_cluster_file)
        config = RetryConfig(max_retries=3, timeout_seconds=30.0)

        async def quick_op(ctx: FDBRecordContext):
            key = test_subspace.pack(("config_test",))
            ctx.transaction.set(key, b"config_value")
            return True

        result = await db.run(quick_op, retry_config=config)
        assert result is True


class TestRetryConfig:
    """Test RetryConfig behavior."""

    def test_default_values(self):
        """Test default retry config values."""
        config = RetryConfig()
        assert config.max_retries == 10
        assert config.initial_delay_ms == 10.0
        assert config.max_delay_ms == 1000.0
        assert config.backoff_multiplier == 2.0
        assert config.timeout_seconds == 0.0

    def test_calculate_delay(self):
        """Test exponential backoff delay calculation."""
        config = RetryConfig(
            initial_delay_ms=100.0,
            max_delay_ms=1000.0,
            backoff_multiplier=2.0,
        )

        # First attempt: 100ms
        assert config.calculate_delay(0) == 0.1

        # Second attempt: 200ms
        assert config.calculate_delay(1) == 0.2

        # Third attempt: 400ms
        assert config.calculate_delay(2) == 0.4

        # Fourth attempt: 800ms
        assert config.calculate_delay(3) == 0.8

        # Fifth attempt: capped at 1000ms
        assert config.calculate_delay(4) == 1.0
        assert config.calculate_delay(5) == 1.0


class TestTransactionIsolation:
    """Test transaction isolation and consistency."""

    @pytest.mark.asyncio
    async def test_transaction_isolation(self, fdb_database, test_subspace):
        """Test that uncommitted changes are not visible to other transactions."""
        key = test_subspace.pack(("isolation_test",))

        # First transaction writes but doesn't commit
        ctx1 = FDBRecordContext(database=fdb_database)
        ctx1.transaction.set(key, b"ctx1_value")

        # Second transaction should not see the uncommitted value
        ctx2 = FDBRecordContext(database=fdb_database)
        value = ctx2.transaction[key]
        assert not value.present()

        ctx1.close()
        ctx2.close()

    @pytest.mark.asyncio
    async def test_read_your_writes(self, fdb_database, test_subspace):
        """Test that a transaction can read its own writes."""
        ctx = FDBRecordContext(database=fdb_database)
        try:
            key = test_subspace.pack(("ryw_test",))

            # Write
            ctx.transaction.set(key, b"ryw_value")

            # Read back (should see our own write)
            value = ctx.transaction[key]
            assert value.present()
            assert bytes(value) == b"ryw_value"

            await ctx.commit()
        finally:
            ctx.close()

    @pytest.mark.asyncio
    async def test_snapshot_read(self, fdb_database, test_subspace):
        """Test snapshot reads."""
        key = test_subspace.pack(("snapshot_test",))

        # First, write some data
        ctx1 = FDBRecordContext(database=fdb_database)
        ctx1.transaction.set(key, b"initial")
        await ctx1.commit()
        ctx1.close()

        # Now read with snapshot
        ctx2 = FDBRecordContext(database=fdb_database)
        try:
            snapshot = ctx2.transaction.snapshot
            value = snapshot[key]
            assert value.present()
            assert bytes(value) == b"initial"
        finally:
            ctx2.close()


class TestConcurrentOperations:
    """Test concurrent transaction operations."""

    @pytest.mark.asyncio
    async def test_parallel_reads(self, fdb_database, test_subspace):
        """Test parallel read operations."""
        import asyncio

        # Write some test data first
        ctx = FDBRecordContext(database=fdb_database)
        for i in range(5):
            key = test_subspace.pack((f"parallel_{i}",))
            ctx.transaction.set(key, f"value_{i}".encode())
        await ctx.commit()
        ctx.close()

        # Read in parallel
        async def read_key(db, idx):
            ctx = FDBRecordContext(database=db)
            try:
                key = test_subspace.pack((f"parallel_{idx}",))
                value = ctx.transaction[key]
                return bytes(value) if value.present() else None
            finally:
                ctx.close()

        results = await asyncio.gather(*[
            read_key(fdb_database, i) for i in range(5)
        ])

        for i, result in enumerate(results):
            assert result == f"value_{i}".encode()

    @pytest.mark.asyncio
    async def test_range_read(self, fdb_database, test_subspace):
        """Test range read operations."""
        # Write test data
        ctx = FDBRecordContext(database=fdb_database)
        for i in range(10):
            key = test_subspace.pack(("range", i))
            ctx.transaction.set(key, f"range_value_{i}".encode())
        await ctx.commit()
        ctx.close()

        # Read range
        ctx2 = FDBRecordContext(database=fdb_database)
        try:
            start = test_subspace.pack(("range",))
            end = test_subspace.pack(("range", 1000))
            items = list(ctx2.transaction.get_range(start, end))
            assert len(items) == 10
        finally:
            ctx2.close()
