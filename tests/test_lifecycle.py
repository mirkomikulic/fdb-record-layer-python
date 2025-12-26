"""Tests for lifecycle management utilities."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from fdb_record_layer.utils.lifecycle import (
    InFlightContext,
    LifecycleManager,
    LifecycleState,
    ShutdownConfig,
    get_lifecycle,
    init_lifecycle,
    reset_lifecycle,
    shutdown,
)


class TestShutdownConfig:
    """Tests for ShutdownConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ShutdownConfig()
        assert config.timeout_seconds == 30.0
        assert config.drain_timeout_seconds == 10.0
        assert config.force_on_timeout is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ShutdownConfig(
            timeout_seconds=10.0,
            drain_timeout_seconds=5.0,
            force_on_timeout=False,
        )
        assert config.timeout_seconds == 10.0
        assert config.drain_timeout_seconds == 5.0
        assert config.force_on_timeout is False

    def test_default_signals(self):
        """Test default signals to handle."""
        config = ShutdownConfig()
        assert signal.SIGTERM in config.signals
        assert signal.SIGINT in config.signals


class TestLifecycleState:
    """Tests for LifecycleState enum."""

    def test_state_values(self):
        """Test state enum values exist."""
        assert LifecycleState.STARTING is not None
        assert LifecycleState.RUNNING is not None
        assert LifecycleState.SHUTTING_DOWN is not None
        assert LifecycleState.STOPPED is not None

    def test_state_string_values(self):
        """Test state string values."""
        assert LifecycleState.STARTING.value == "starting"
        assert LifecycleState.RUNNING.value == "running"
        assert LifecycleState.SHUTTING_DOWN.value == "shutting_down"
        assert LifecycleState.STOPPED.value == "stopped"


class TestLifecycleManager:
    """Tests for LifecycleManager."""

    @pytest.fixture
    def manager(self) -> LifecycleManager:
        """Create a lifecycle manager for testing."""
        return LifecycleManager()

    def test_initial_state(self, manager: LifecycleManager):
        """Test initial manager state."""
        assert manager.state == LifecycleState.STARTING
        assert manager._get_in_flight_count() == 0

    def test_start(self, manager: LifecycleManager):
        """Test start method."""
        with patch.object(signal, "signal"):
            manager.start()
        assert manager.state == LifecycleState.RUNNING

    def test_start_sets_start_time(self, manager: LifecycleManager):
        """Test start sets start time."""
        with patch.object(signal, "signal"):
            manager.start()
        assert manager._start_time is not None
        assert manager.uptime_seconds >= 0

    def test_cannot_start_twice(self, manager: LifecycleManager):
        """Test cannot start from non-STARTING state."""
        with patch.object(signal, "signal"):
            manager.start()
        with pytest.raises(RuntimeError, match="Cannot start from state"):
            manager.start()

    def test_is_running(self, manager: LifecycleManager):
        """Test is_running property."""
        assert not manager.is_running
        manager._state = LifecycleState.RUNNING
        assert manager.is_running

    def test_is_shutting_down(self, manager: LifecycleManager):
        """Test is_shutting_down property."""
        assert not manager.is_shutting_down
        manager._state = LifecycleState.SHUTTING_DOWN
        assert manager.is_shutting_down

    def test_request_shutdown_from_not_running(self, manager: LifecycleManager):
        """Test request_shutdown from non-running state does nothing."""
        # Should not raise, just warn
        manager.request_shutdown()
        # Still in STARTING state since we weren't RUNNING
        assert manager.state == LifecycleState.STARTING

    def test_register_shutdown_hook(self, manager: LifecycleManager):
        """Test registering shutdown hooks."""
        hook = MagicMock()
        manager.register_shutdown_hook(hook)
        assert hook in manager._shutdown_hooks

    def test_register_async_shutdown_hook(self, manager: LifecycleManager):
        """Test registering async shutdown hooks."""

        async def async_hook():
            pass

        manager.register_async_shutdown_hook(async_hook)
        assert async_hook in manager._async_shutdown_hooks

    @pytest.mark.asyncio
    async def test_track_in_flight(self, manager: LifecycleManager):
        """Test tracking in-flight operations."""
        manager._state = LifecycleState.RUNNING

        assert manager._get_in_flight_count() == 0

        async with manager.track_in_flight():
            assert manager._get_in_flight_count() == 1

        assert manager._get_in_flight_count() == 0

    @pytest.mark.asyncio
    async def test_track_in_flight_nested(self, manager: LifecycleManager):
        """Test nested in-flight tracking."""
        manager._state = LifecycleState.RUNNING

        async with manager.track_in_flight():
            assert manager._get_in_flight_count() == 1
            async with manager.track_in_flight():
                assert manager._get_in_flight_count() == 2
            assert manager._get_in_flight_count() == 1

        assert manager._get_in_flight_count() == 0

    def test_track_in_flight_sync(self, manager: LifecycleManager):
        """Test tracking in-flight operations synchronously."""
        manager._state = LifecycleState.RUNNING

        assert manager._get_in_flight_count() == 0

        with manager.track_in_flight():
            assert manager._get_in_flight_count() == 1

        assert manager._get_in_flight_count() == 0

    def test_uptime_before_start(self, manager: LifecycleManager):
        """Test uptime before start returns 0."""
        assert manager.uptime_seconds == 0.0


class TestInFlightContext:
    """Tests for InFlightContext."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Test InFlightContext as async context manager."""
        manager = LifecycleManager()
        manager._state = LifecycleState.RUNNING

        context = InFlightContext(manager)
        assert manager._get_in_flight_count() == 0

        async with context:
            assert manager._get_in_flight_count() == 1

        assert manager._get_in_flight_count() == 0

    def test_sync_context_manager(self):
        """Test InFlightContext as sync context manager."""
        manager = LifecycleManager()
        manager._state = LifecycleState.RUNNING

        context = InFlightContext(manager)
        assert manager._get_in_flight_count() == 0

        with context:
            assert manager._get_in_flight_count() == 1

        assert manager._get_in_flight_count() == 0


class TestGlobalFunctions:
    """Tests for global functions."""

    def test_get_lifecycle(self, reset_globals):
        """Test get_lifecycle."""
        manager = get_lifecycle()
        assert isinstance(manager, LifecycleManager)

    def test_get_lifecycle_returns_same_instance(self, reset_globals):
        """Test get_lifecycle returns same instance."""
        manager1 = get_lifecycle()
        manager2 = get_lifecycle()
        assert manager1 is manager2

    def test_reset_lifecycle(self, reset_globals):
        """Test reset_lifecycle."""
        manager1 = get_lifecycle()
        reset_lifecycle()
        manager2 = get_lifecycle()
        assert manager1 is not manager2

    def test_init_lifecycle(self, reset_globals):
        """Test init_lifecycle with config."""
        with patch.object(signal, "signal"):
            config = ShutdownConfig(timeout_seconds=5.0)
            manager = init_lifecycle(config)
            assert isinstance(manager, LifecycleManager)
            assert manager.is_running

    def test_init_lifecycle_already_running(self, reset_globals):
        """Test init_lifecycle when already running raises error."""
        with patch.object(signal, "signal"):
            init_lifecycle()
            with pytest.raises(RuntimeError, match="already initialized"):
                init_lifecycle()

    def test_shutdown_function(self, reset_globals):
        """Test shutdown function calls request_shutdown."""
        manager = get_lifecycle()
        manager._state = LifecycleState.RUNNING

        # shutdown() is synchronous and just requests shutdown
        shutdown()

        # Should transition to SHUTTING_DOWN or STOPPED (if shutdown completes quickly)
        assert manager.state in (LifecycleState.SHUTTING_DOWN, LifecycleState.STOPPED)
