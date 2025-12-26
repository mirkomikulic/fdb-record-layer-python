"""Pytest configuration and shared fixtures."""

import asyncio
import sys
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

# Only mock FDB if it's not available (either not installed or missing native library)
# This allows unit tests to run without FDB client while
# integration tests use the real FDB when available


def _check_fdb_available() -> bool:
    """Check if FDB is truly available (package installed AND native library present)."""
    import traceback

    try:
        import fdb

        # This will raise if the native library is missing
        fdb.api_version(730)
        return True
    except Exception as e:
        print(f"FDB not available: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return False


_fdb_available = _check_fdb_available()
print(f"FDB available: {_fdb_available}", flush=True)

if not _fdb_available:
    # Mock FDB so unit tests can run without it installed
    _mock_fdb = MagicMock()
    _mock_fdb.api_version = MagicMock()
    _mock_fdb.open = MagicMock()
    sys.modules["fdb"] = _mock_fdb
    sys.modules["fdb.subspace_impl"] = MagicMock()
    print("FDB mocked")


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
