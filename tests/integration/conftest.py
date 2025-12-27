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

    fdb.api_version(740)
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
    tr = fdb_database.create_transaction()
    r = subspace.range()
    tr.clear_range(r.start, r.stop)
    tr.commit().wait()


@pytest.fixture(scope="function")
def fdb_transaction(fdb_database):
    """Create a transaction for testing."""
    tr = fdb_database.create_transaction()
    yield tr
    tr.cancel()


@pytest.fixture(scope="session")
def proto_descriptor():
    """Get the test protobuf file descriptor."""
    from tests.integration.test_records_pb2 import DESCRIPTOR

    return DESCRIPTOR


@pytest.fixture(scope="session")
def person_class():
    """Get the Person protobuf class."""
    from tests.integration.test_records_pb2 import Person

    return Person


@pytest.fixture(scope="session")
def product_class():
    """Get the Product protobuf class."""
    from tests.integration.test_records_pb2 import Product

    return Product


@pytest.fixture(scope="function")
def record_metadata(proto_descriptor):
    """Create RecordMetaData for testing."""
    from fdb_record_layer.expressions.field import FieldKeyExpression
    from fdb_record_layer.metadata.index import Index, IndexType
    from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType

    # Create Person record type with primary key on 'id'
    person_type = RecordType(
        name="Person",
        descriptor=proto_descriptor.message_types_by_name["Person"],
        primary_key=FieldKeyExpression("id"),
    )

    # Create Product record type with primary key on 'id'
    product_type = RecordType(
        name="Product",
        descriptor=proto_descriptor.message_types_by_name["Product"],
        primary_key=FieldKeyExpression("id"),
    )

    # Create indexes
    person_name_index = Index(
        name="Person$name",
        root_expression=FieldKeyExpression("name"),
        index_type=IndexType.VALUE,
        record_types=["Person"],
    )

    person_age_index = Index(
        name="Person$age",
        root_expression=FieldKeyExpression("age"),
        index_type=IndexType.VALUE,
        record_types=["Person"],
    )

    person_city_index = Index(
        name="Person$city",
        root_expression=FieldKeyExpression("city"),
        index_type=IndexType.VALUE,
        record_types=["Person"],
    )

    product_name_index = Index(
        name="Product$name",
        root_expression=FieldKeyExpression("name"),
        index_type=IndexType.VALUE,
        record_types=["Product"],
    )

    product_category_index = Index(
        name="Product$category",
        root_expression=FieldKeyExpression("category"),
        index_type=IndexType.VALUE,
        record_types=["Product"],
    )

    # Create metadata
    metadata = RecordMetaData(
        record_types={
            "Person": person_type,
            "Product": product_type,
        },
        indexes={
            "Person$name": person_name_index,
            "Person$age": person_age_index,
            "Person$city": person_city_index,
            "Product$name": product_name_index,
            "Product$category": product_category_index,
        },
        file_descriptor=proto_descriptor,
    )

    return metadata
