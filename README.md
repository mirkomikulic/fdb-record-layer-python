> **⚠️ Disclaimer:** This is an AI-generated reimplementation of the original [Java FoundationDB Record Layer](https://github.com/FoundationDB/fdb-record-layer). It was created using Claude (Anthropic) and has not been officially endorsed by Apple or the FoundationDB team.

# FDB Record Layer for Python

A Python implementation of the [FoundationDB Record Layer](https://github.com/FoundationDB/fdb-record-layer), providing a structured record-oriented store with secondary indexes, query planning, and SQL support on top of FoundationDB.

## Features

- **Record Store**: Type-safe storage and retrieval of Protocol Buffer messages
- **Secondary Indexes**: Automatic index maintenance with VALUE, COUNT, RANK, and TEXT index types
- **Query System**: Declarative query API with cost-based optimization (Cascades planner)
- **SQL Support**: SQL parsing and execution with full DML/DDL support
- **Async/Await**: Native Python asyncio support throughout
- **Production Ready**: Connection pooling, circuit breakers, health checks, graceful shutdown

## Installation

```bash
pip install fdb-record-layer
```

For SQL support:
```bash
pip install fdb-record-layer[sql]
```

For all optional dependencies:
```bash
pip install fdb-record-layer[all]
```

## Requirements

- Python 3.10+
- FoundationDB 7.1+
- Protocol Buffers 3.20+

## Quick Start

### Define Your Schema

```python
from fdb_record_layer import RecordMetaDataBuilder, Index, IndexTypes
from your_proto_pb2 import Person  # Your protobuf message

# Build metadata with indexes
metadata = (
    RecordMetaDataBuilder()
    .add_record_type(Person)
    .add_index(Index("person_by_name", "name"))
    .add_index(Index("person_by_age", "age", index_type=IndexTypes.VALUE))
    .build()
)
```

### Store and Query Records

```python
from fdb_record_layer import FDBDatabase, FDBRecordStore

async def main():
    # Connect to FoundationDB
    db = FDBDatabase.open()

    async with db.transaction() as tr:
        # Open record store
        store = await FDBRecordStore.open(tr, metadata, key_space_path=("myapp",))

        # Save a record
        person = Person(id=1, name="Alice", age=30)
        await store.save_record(person)

        # Query by index
        async for record in store.scan_index("person_by_name", equals="Alice"):
            print(f"Found: {record.name}")
```

### Using the Query Builder

```python
from fdb_record_layer.query import Query, Field

# Build a query
query = (
    Query.from_type("Person")
    .where(Field("age").greater_than(25))
    .where(Field("name").starts_with("A"))
    .build()
)

# Execute
async for record in store.execute_query(query):
    print(record)
```

### SQL Queries

```python
from fdb_record_layer.relational import RelationalDatabase

async def main():
    db = RelationalDatabase.open()

    # Execute SQL
    result = await db.execute("""
        SELECT name, age FROM Person
        WHERE age > 25
        ORDER BY name
    """)

    async for row in result:
        print(f"{row['name']}: {row['age']}")
```

## Key Expressions

Key expressions define how to extract keys from records for indexing:

```python
from fdb_record_layer.expressions import field, concat, record_type

# Simple field
field("name")

# Composite key
concat(field("last_name"), field("first_name"))

# Nested field
field("address").nest("city")

# Include record type in key (for union indexes)
concat(record_type(), field("id"))
```

## Index Types

| Type | Description | Use Case |
|------|-------------|----------|
| VALUE | Standard B-tree index | Equality and range queries |
| COUNT | Aggregate count index | Fast COUNT(*) queries |
| SUM | Aggregate sum index | Fast SUM() queries |
| RANK | Skip-list based ranking | Leaderboards, percentiles |
| TEXT | Full-text search | Text search with tokenization |

## Production Features

### Connection Pooling

```python
from fdb_record_layer.utils import ConnectionPool

pool = ConnectionPool(min_size=5, max_size=20)
async with pool.acquire() as conn:
    # Use connection
    pass
```

### Circuit Breaker

```python
from fdb_record_layer.utils import get_circuit_breaker

breaker = get_circuit_breaker("fdb")
async with breaker:
    await store.save_record(record)
```

### Health Checks

```python
from fdb_record_layer.utils import get_health_checker

checker = get_health_checker()
report = await checker.check_health()
print(f"Status: {report.status}")
```

### Graceful Shutdown

```python
from fdb_record_layer.utils import init_lifecycle

lifecycle = init_lifecycle()
# Handles SIGTERM/SIGINT, drains connections, runs cleanup hooks
```

## Documentation

- [API Reference](https://github.com/mirkomikulic/fdb-record-layer-python#readme)
- [Java Record Layer Docs](https://foundationdb.github.io/fdb-record-layer/) (conceptual reference)

## Development

```bash
# Clone and install
git clone https://github.com/mirkomikulic/fdb-record-layer-python
cd fdb-record-layer-python
pip install -e .[dev]

# Run tests
pytest

# Type checking
mypy fdb_record_layer

# Linting
ruff check fdb_record_layer
```

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests.

## Acknowledgments

This project is a Python port of the [FoundationDB Record Layer](https://github.com/FoundationDB/fdb-record-layer), originally developed by Apple.
