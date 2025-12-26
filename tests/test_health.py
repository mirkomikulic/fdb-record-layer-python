"""Tests for health check utilities."""

import pytest

from fdb_record_layer.utils.health import (
    ComponentHealth,
    HealthChecker,
    HealthReport,
    HealthStatus,
    get_health_checker,
    reset_health_checker,
)


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_status_values(self):
        """Test status enum values exist."""
        assert HealthStatus.HEALTHY is not None
        assert HealthStatus.DEGRADED is not None
        assert HealthStatus.UNHEALTHY is not None
        assert HealthStatus.UNKNOWN is not None


class TestComponentHealth:
    """Tests for ComponentHealth."""

    def test_healthy_component(self):
        """Test healthy component creation."""
        health = ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            message="Connected",
        )
        assert health.name == "database"
        assert health.status == HealthStatus.HEALTHY
        assert health.message == "Connected"
        assert health.details == {}

    def test_unhealthy_component_with_details(self):
        """Test unhealthy component with details."""
        health = ComponentHealth(
            name="cache",
            status=HealthStatus.UNHEALTHY,
            message="Connection failed",
            details={"error": "Timeout", "retries": 3},
        )
        assert health.status == HealthStatus.UNHEALTHY
        assert health.details["error"] == "Timeout"
        assert health.details["retries"] == 3

    def test_to_dict(self):
        """Test ComponentHealth.to_dict()."""
        health = ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            message="OK",
        )
        result = health.to_dict()
        assert result["name"] == "database"
        assert result["status"] == "healthy"
        assert result["message"] == "OK"


class TestHealthReport:
    """Tests for HealthReport."""

    def test_empty_report(self):
        """Test empty health report."""
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            components=[],
        )
        assert report.status == HealthStatus.HEALTHY
        assert report.components == []
        assert report.timestamp is not None

    def test_report_with_components(self):
        """Test health report with components."""
        db_health = ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
        )
        cache_health = ComponentHealth(
            name="cache",
            status=HealthStatus.DEGRADED,
            message="High latency",
        )
        report = HealthReport(
            status=HealthStatus.DEGRADED,
            components=[db_health, cache_health],
        )
        assert report.status == HealthStatus.DEGRADED
        assert len(report.components) == 2

    def test_to_dict(self):
        """Test to_dict conversion."""
        db_health = ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            message="OK",
        )
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            components=[db_health],
        )
        result = report.to_dict()

        assert result["status"] == "healthy"
        assert "timestamp" in result
        assert len(result["components"]) == 1
        assert result["components"][0]["status"] == "healthy"

    def test_is_healthy_property(self):
        """Test is_healthy property."""
        report = HealthReport(status=HealthStatus.HEALTHY)
        assert report.is_healthy is True

        report = HealthReport(status=HealthStatus.DEGRADED)
        assert report.is_healthy is False

    def test_is_alive_property(self):
        """Test is_alive property."""
        report = HealthReport(status=HealthStatus.HEALTHY)
        assert report.is_alive is True

        report = HealthReport(status=HealthStatus.DEGRADED)
        assert report.is_alive is True

        report = HealthReport(status=HealthStatus.UNHEALTHY)
        assert report.is_alive is False


class TestHealthChecker:
    """Tests for HealthChecker."""

    @pytest.fixture
    def checker(self) -> HealthChecker:
        """Create a health checker for testing."""
        return HealthChecker()

    def test_initial_state(self, checker: HealthChecker):
        """Test initial checker state."""
        # Checker has internal lists for different check types
        assert checker._custom_checks == []
        assert checker._async_checks == []
        assert checker._databases == []
        assert checker._pools == []

    def test_register_check(self, checker: HealthChecker):
        """Test registering a custom health check."""

        def my_check() -> bool:
            return True

        checker.register_check("my_service", my_check)
        assert len(checker._custom_checks) == 1
        assert checker._custom_checks[0][0] == "my_service"

    def test_register_async_check(self, checker: HealthChecker):
        """Test registering an async health check."""

        async def my_async_check():
            return True

        checker.register_async_check("my_async_service", my_async_check)
        assert len(checker._async_checks) == 1
        assert checker._async_checks[0][0] == "my_async_service"

    @pytest.mark.asyncio
    async def test_check_health_empty(self, checker: HealthChecker):
        """Test check_health with no registered checks returns UNKNOWN."""
        report = await checker.check_health()
        # When no components, overall status is UNKNOWN
        assert report.status == HealthStatus.UNKNOWN
        assert len(report.components) == 0

    @pytest.mark.asyncio
    async def test_check_health_all_healthy(self, checker: HealthChecker):
        """Test check_health when all components healthy."""

        def healthy_check() -> bool:
            return True

        checker.register_check("service1", healthy_check)
        checker.register_check("service2", healthy_check)

        report = await checker.check_health()
        assert report.status == HealthStatus.HEALTHY
        assert len(report.components) == 2

    @pytest.mark.asyncio
    async def test_check_health_with_unhealthy(self, checker: HealthChecker):
        """Test check_health with unhealthy component."""

        def healthy_check() -> bool:
            return True

        def unhealthy_check() -> bool:
            return False

        checker.register_check("healthy", healthy_check)
        checker.register_check("unhealthy", unhealthy_check)

        report = await checker.check_health()
        assert report.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_health_handles_exceptions(self, checker: HealthChecker):
        """Test check_health handles check exceptions."""

        def failing_check() -> bool:
            raise RuntimeError("Check failed")

        checker.register_check("failing", failing_check)

        report = await checker.check_health()
        assert report.status == HealthStatus.UNHEALTHY
        assert len(report.components) == 1
        assert "Check error" in report.components[0].message

    @pytest.mark.asyncio
    async def test_check_liveness(self, checker: HealthChecker):
        """Test liveness check."""
        result = await checker.check_liveness()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_readiness_healthy(self, checker: HealthChecker):
        """Test readiness check when healthy."""

        def healthy_check() -> bool:
            return True

        checker.register_check("service", healthy_check)
        result = await checker.check_readiness()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_readiness_unhealthy(self, checker: HealthChecker):
        """Test readiness check when unhealthy."""

        def unhealthy_check() -> bool:
            return False

        checker.register_check("service", unhealthy_check)
        result = await checker.check_readiness()
        # is_alive returns False only for UNHEALTHY status
        assert result is False

    @pytest.mark.asyncio
    async def test_async_check(self, checker: HealthChecker):
        """Test async health check."""

        async def async_healthy_check():
            return True

        checker.register_async_check("async_service", async_healthy_check)

        report = await checker.check_health()
        assert report.status == HealthStatus.HEALTHY
        assert len(report.components) == 1


class TestGlobalFunctions:
    """Tests for global functions."""

    def test_get_health_checker(self, reset_globals):
        """Test global checker accessor."""
        checker = get_health_checker()
        assert isinstance(checker, HealthChecker)

    def test_get_health_checker_returns_same_instance(self, reset_globals):
        """Test global checker returns same instance."""
        checker1 = get_health_checker()
        checker2 = get_health_checker()
        assert checker1 is checker2

    def test_reset_health_checker(self, reset_globals):
        """Test reset_health_checker."""
        checker1 = get_health_checker()
        reset_health_checker()
        checker2 = get_health_checker()
        assert checker1 is not checker2
