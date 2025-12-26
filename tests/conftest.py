"""Pytest configuration and shared fixtures."""

import asyncio
import importlib.util
import sys
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

# Only mock FDB if it's not installed
# This allows unit tests to run without FDB installed while
# integration tests use the real FDB when available

if importlib.util.find_spec("fdb") is None:
    # Mock FDB so unit tests can run without it installed
    _mock_fdb = MagicMock()
    _mock_fdb.api_version = MagicMock()
    _mock_fdb.open = MagicMock()
    sys.modules["fdb"] = _mock_fdb
    sys.modules["fdb.subspace_impl"] = MagicMock()


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def reset_globals():
    """Reset global state between tests."""
    # Reset circuit breakers
    from fdb_record_layer.utils.circuit_breaker import reset_circuit_breakers

    reset_circuit_breakers()

    # Reset health checker
    from fdb_record_layer.utils.health import reset_health_checker

    reset_health_checker()

    # Reset lifecycle
    from fdb_record_layer.utils.lifecycle import reset_lifecycle

    reset_lifecycle()

    # Reset metrics
    from fdb_record_layer.utils.metrics import reset_metrics

    reset_metrics()

    yield

    # Cleanup after test
    reset_circuit_breakers()
    reset_health_checker()
    reset_lifecycle()
    reset_metrics()
