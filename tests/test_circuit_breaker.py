"""Tests for circuit breaker pattern."""

import asyncio

import pytest

from fdb_record_layer.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    get_circuit_breaker_registry,
    reset_circuit_breakers,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout_seconds == 30.0
        assert config.excluded_exceptions == ()

    def test_custom_values(self):
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout_seconds=10.0,
            excluded_exceptions=(ValueError,),
        )
        assert config.failure_threshold == 3
        assert config.success_threshold == 1
        assert config.timeout_seconds == 10.0
        assert config.excluded_exceptions == (ValueError,)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    @pytest.fixture
    def config(self) -> CircuitBreakerConfig:
        """Create a config with low thresholds for testing."""
        return CircuitBreakerConfig(
            failure_threshold=2,
            success_threshold=1,
            timeout_seconds=0.1,
        )

    @pytest.fixture
    def breaker(self, config: CircuitBreakerConfig) -> CircuitBreaker:
        """Create a circuit breaker for testing."""
        return CircuitBreaker("test", config)

    def test_initial_state(self, breaker: CircuitBreaker):
        """Test initial circuit state is CLOSED."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open
        assert breaker.name == "test"

    @pytest.mark.asyncio
    async def test_successful_request(self, breaker: CircuitBreaker):
        """Test successful request doesn't change state."""
        async with breaker:
            pass  # Success

        assert breaker.state == CircuitState.CLOSED
        assert breaker.stats.successful_requests == 1
        assert breaker.stats.failed_requests == 0

    @pytest.mark.asyncio
    async def test_failed_request_below_threshold(self, breaker: CircuitBreaker):
        """Test single failure doesn't open circuit."""
        try:
            async with breaker:
                raise ValueError("Test error")
        except ValueError:
            pass

        assert breaker.state == CircuitState.CLOSED
        assert breaker.stats.failed_requests == 1

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, breaker: CircuitBreaker):
        """Test circuit opens after threshold failures."""
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open
        assert breaker.stats.failed_requests == 2

    @pytest.mark.asyncio
    async def test_rejects_when_open(self, breaker: CircuitBreaker):
        """Test requests are rejected when circuit is open."""
        # Open the circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        # Try another request - should be rejected
        with pytest.raises(CircuitOpenError) as exc_info:
            async with breaker:
                pass

        assert "test" in str(exc_info.value)
        assert breaker.stats.rejected_requests == 1

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self, breaker: CircuitBreaker):
        """Test circuit transitions to HALF_OPEN after timeout."""
        # Open the circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Next request should be allowed (HALF_OPEN)
        async with breaker:
            pass  # Success

        # Should close after success
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reopens_on_failure_in_half_open(self, breaker: CircuitBreaker):
        """Test circuit reopens if request fails in HALF_OPEN state."""
        # Open the circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Fail in half-open state
        try:
            async with breaker:
                raise ValueError("Still failing")
        except ValueError:
            pass

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_excluded_exceptions(self):
        """Test excluded exceptions don't count as failures."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            excluded_exceptions=(ValueError,),
        )
        breaker = CircuitBreaker("test", config)

        # ValueError is excluded
        for _ in range(5):
            try:
                async with breaker:
                    raise ValueError("Excluded error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.CLOSED

        # RuntimeError is not excluded
        for _ in range(2):
            try:
                async with breaker:
                    raise RuntimeError("Not excluded")
            except RuntimeError:
                pass

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_execute_method(self, breaker: CircuitBreaker):
        """Test execute method with async function."""

        async def my_func(x: int, y: int) -> int:
            return x + y

        result = await breaker.execute(my_func, 1, 2)
        assert result == 3

    @pytest.mark.asyncio
    async def test_execute_with_sync_function(self, breaker: CircuitBreaker):
        """Test execute method with sync function."""

        def my_func(x: int, y: int) -> int:
            return x + y

        result = await breaker.execute(my_func, 1, 2)
        assert result == 3

    def test_reset(self, breaker: CircuitBreaker):
        """Test reset method."""
        breaker._state = CircuitState.OPEN
        breaker._failure_count = 5
        breaker._success_count = 3

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0
        assert breaker._success_count == 0

    @pytest.mark.asyncio
    async def test_stats_tracking(self, breaker: CircuitBreaker):
        """Test statistics are tracked correctly."""
        # Successful request
        async with breaker:
            pass

        # Failed request
        try:
            async with breaker:
                raise ValueError("Error")
        except ValueError:
            pass

        stats = breaker.stats
        assert stats.total_requests == 2
        assert stats.successful_requests == 1
        assert stats.failed_requests == 1
        assert stats.last_success_time is not None
        assert stats.last_failure_time is not None


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry."""

    def test_get_creates_new_breaker(self):
        """Test get creates a new breaker if not exists."""
        registry = CircuitBreakerRegistry()
        breaker = registry.get("test")
        assert breaker.name == "test"

    def test_get_returns_same_breaker(self):
        """Test get returns the same breaker on subsequent calls."""
        registry = CircuitBreakerRegistry()
        breaker1 = registry.get("test")
        breaker2 = registry.get("test")
        assert breaker1 is breaker2

    def test_get_with_config(self):
        """Test get with custom config."""
        registry = CircuitBreakerRegistry()
        config = CircuitBreakerConfig(failure_threshold=10)
        breaker = registry.get("test", config)
        assert breaker._config.failure_threshold == 10

    def test_remove(self):
        """Test remove method."""
        registry = CircuitBreakerRegistry()
        breaker1 = registry.get("test")
        registry.remove("test")
        breaker2 = registry.get("test")
        assert breaker1 is not breaker2

    def test_reset_all(self):
        """Test reset_all method."""
        registry = CircuitBreakerRegistry()
        breaker1 = registry.get("test1")
        breaker2 = registry.get("test2")
        breaker1._state = CircuitState.OPEN
        breaker2._state = CircuitState.OPEN

        registry.reset_all()

        assert breaker1.state == CircuitState.CLOSED
        assert breaker2.state == CircuitState.CLOSED

    def test_get_all_stats(self):
        """Test get_all_stats method."""
        registry = CircuitBreakerRegistry()
        registry.get("test1")
        registry.get("test2")

        stats = registry.get_all_stats()
        assert "test1" in stats
        assert "test2" in stats


class TestGlobalFunctions:
    """Tests for global functions."""

    def test_get_circuit_breaker_registry(self, reset_globals):
        """Test global registry accessor."""
        registry = get_circuit_breaker_registry()
        assert isinstance(registry, CircuitBreakerRegistry)

    def test_get_circuit_breaker(self, reset_globals):
        """Test global breaker accessor."""
        breaker = get_circuit_breaker("test")
        assert isinstance(breaker, CircuitBreaker)
        assert breaker.name == "test"

    def test_reset_circuit_breakers(self, reset_globals):
        """Test reset_circuit_breakers."""
        breaker1 = get_circuit_breaker("test1")
        reset_circuit_breakers()
        breaker2 = get_circuit_breaker("test1")
        assert breaker1 is not breaker2
