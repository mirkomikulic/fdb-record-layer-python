"""Pytest fixtures for FDB integration tests."""

import os
import uuid

import pytest

# Skip all integration tests if FDB is not available
pytestmark = pytest.mark.integration


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test requiring FDB")


@pytest.fixture(scope="session")
def fdb_cluster_file():
    """Get the FDB cluster file path."""
    cluster_file = os.environ.get("FDB_CLUSTER_FILE")
    if not cluster_file:
        # Try common locations
        common_paths = [
            "./fdb.cluster",
            "/etc/foundationdb/fdb.cluster",
            "/usr/local/etc/foundationdb/fdb.cluster",
        ]
        for path in common_paths:
            if os.path.exists(path):
                cluster_file = path
                break

    if not cluster_file or not os.path.exists(cluster_file):
        pytest.skip("FDB_CLUSTER_FILE not set and no cluster file found")

    return cluster_file


@pytest.fixture(scope="session")
def fdb_database(fdb_cluster_file):
    """Create an FDB database connection."""
    import fdb

    fdb.api_version(730)
    db = fdb.open(fdb_cluster_file)

    yield db

    # No explicit close needed for FDB


@pytest.fixture(scope="function")
def test_subspace(fdb_database):
    """Create a unique subspace for each test to avoid conflicts."""
    from fdb.subspace_impl import Subspace

    # Generate unique prefix for this test
    test_id = uuid.uuid4().hex[:8]
    prefix = ("test", test_id)

    subspace = Subspace(prefix)

    yield subspace

    # Cleanup: clear all data in this subspace
    @fdb_database.transact
    def cleanup(tr):
        r = subspace.range()
        tr.clear_range(r.start, r.stop)

    cleanup()


@pytest.fixture(scope="function")
def fdb_transaction(fdb_database):
    """Create a transaction for testing."""
    tr = fdb_database.create_transaction()
    yield tr
    tr.cancel()


@pytest.fixture
def sample_proto_descriptor():
    """Create a sample protobuf descriptor for testing."""
    from unittest.mock import MagicMock

    # Create a mock file descriptor
    file_desc = MagicMock()
    file_desc.message_types_by_name = {}

    # Create a Person message type
    person_desc = MagicMock()
    person_desc.name = "Person"
    person_desc.full_name = "test.Person"

    # Create fields
    id_field = MagicMock()
    id_field.name = "id"
    id_field.number = 1
    id_field.type = 3  # INT64
    id_field.label = 1  # OPTIONAL

    name_field = MagicMock()
    name_field.name = "name"
    name_field.number = 2
    name_field.type = 9  # STRING
    name_field.label = 1

    age_field = MagicMock()
    age_field.name = "age"
    age_field.number = 3
    age_field.type = 5  # INT32
    age_field.label = 1

    email_field = MagicMock()
    email_field.name = "email"
    email_field.number = 4
    email_field.type = 9  # STRING
    email_field.label = 1

    person_desc.fields = [id_field, name_field, age_field, email_field]
    person_desc.fields_by_name = {
        "id": id_field,
        "name": name_field,
        "age": age_field,
        "email": email_field,
    }

    file_desc.message_types_by_name["Person"] = person_desc

    return file_desc
