# FDB Record Layer for Python

[![CI](https://github.com/mirkomikulic/fdb-record-layer-python/actions/workflows/ci.yml/badge.svg)](https://github.com/mirkomikulic/fdb-record-layer-python/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/fdb-record-layer)](https://pypi.org/project/fdb-record-layer/)
[![Python](https://img.shields.io/pypi/pyversions/fdb-record-layer)](https://pypi.org/project/fdb-record-layer/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

> **⚠️ Disclaimer:** This is an AI-assisted reimplementation of the [Java FoundationDB Record Layer](https://github.com/FoundationDB/fdb-record-layer), written with Claude (Anthropic). It is not affiliated with or endorsed by Apple or the FoundationDB team.

> **Status: beta.** The API may still change between releases. Test it with your workload before using it in production.

A Python implementation of the FoundationDB Record Layer: a record-oriented store with Protocol Buffer schemas, secondary indexes and a query planner on top of [FoundationDB](https://www.foundationdb.org/).

## Features

- **Record store**: save, load, scan and delete Protocol Buffer messages, with transactional retries
- **Secondary indexes**: VALUE, COUNT, SUM, RANK and TEXT indexes, maintained on every write
- **Query API**: a declarative query builder with a heuristic planner (a Cascades cost-based planner is included and experimental)
- **Continuations**: cursor-based pagination across transactions
- **Java interoperability**: `JavaCompatibleStore` reads and writes the Java Record Layer's on-disk format
- **Schema evolution checks**: validate that a metadata change is safe before deploying it
- **SQL (experimental)**: SQL parser and executor. `SELECT` can run against a record store; `CREATE`/`INSERT`/`UPDATE`/`DELETE` currently work on an in-memory table only
- **Operational utilities**: circuit breakers, health checks, graceful shutdown, metrics, caching
- **async/await** throughout

## Requirements

| Component | Supported versions |
|---|---|
| Python | 3.11 – 3.15 |
| FoundationDB server and client library | 7.4 or 8.0 (tested in CI with 7.4.10 and 8.0.1) |
| `foundationdb` Python package | Same major.minor as your client library |
| `protobuf` | 6.33.2 or newer (including 7.x) |

The library uses FDB API version 740, which both 7.4 and 8.0 clients support.

## Installation

1. Install the FoundationDB client library for your platform from the [FoundationDB releases](https://github.com/apple/foundationdb/releases).

2. Install the package together with the matching Python binding:

   ```bash
   # FoundationDB 8.0 client
   pip install fdb-record-layer "foundationdb~=8.0.0"

   # FoundationDB 7.4 client
   pip install fdb-record-layer "foundationdb~=7.4.0"
   ```

   The `foundationdb` 8.x binding refuses to load a 7.4 client library, so pin it when you use 7.4.

3. For SQL support, add the `sql` extra: `pip install "fdb-record-layer[sql]"`.

To run a local FoundationDB in Docker, see [Local FoundationDB](#local-foundationdb).

## Quick start

The code below is taken from [`examples/quickstart.py`](examples/quickstart.py), which CI runs against FoundationDB 7.4 and 8.0 on every push.

### Define your schema

Records are Protocol Buffer messages. Given [`examples/sample.proto`](examples/sample.proto) compiled with `protoc --python_out=. sample.proto`:

```python
import fdb_record_layer as frl
from sample_pb2 import DESCRIPTOR, Person

metadata = (
    frl.RecordMetaDataBuilder(DESCRIPTOR)
    .set_record_type("Person", primary_key=frl.field("id"))
    .add_index("Person", "person_by_name", frl.field("name"))
    .add_index("Person", "person_by_city_age", frl.concat(frl.field("city"), frl.field("age")))
    .build()
)
```

### Save and load records

`FDBDatabase.run()` runs a function in a transaction and retries it on conflicts.

```python
from fdb.subspace_impl import Subspace

db = frl.FDBDatabase()  # uses FDB_CLUSTER_FILE or the default cluster file
subspace = Subspace(("quickstart",))

async def save_people(ctx):
    store = frl.FDBRecordStore(ctx, subspace, metadata)
    await store.save_record(Person(id=1, name="Alice", age=30, city="Zurich"))
    await store.save_record(Person(id=2, name="Bob", age=25, city="Zurich"))

async def load_alice(ctx):
    store = frl.FDBRecordStore(ctx, subspace, metadata)
    stored = await store.load_record("Person", (1,))
    return stored.record.name

await db.run(save_people)
print(await db.run(load_alice))  # Alice
```

### Scan an index

```python
async def people_in_zurich(ctx):
    store = frl.FDBRecordStore(ctx, subspace, metadata)
    cursor = await store.scan_index("person_by_city_age", frl.IndexScanRange.prefix("Zurich"))
    return [stored.record.name async for stored in cursor]
```

`IndexScanRange` also has `equals(...)`, `between(low, high)` and `greater_than(...)`.

### Query builder

```python
from fdb_record_layer.query import Field, Query

async def older_than_28(ctx):
    store = frl.FDBRecordStore(ctx, subspace, metadata)
    query = Query.from_type("Person").where(Field("age").greater_than(28)).build()
    cursor = await store.execute_query(query)
    return [stored.record.name async for stored in cursor]
```

Use `store.explain_query(query)` to see which plan was chosen.

### SQL (experimental)

```python
from fdb_record_layer.relational import connect

sql = connect("demo")
sql.execute_sql("CREATE TABLE users (id BIGINT PRIMARY KEY, name STRING, age INT)")
sql.execute_sql("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
for row in sql.query("SELECT name FROM users WHERE age > 25"):
    print(row["name"])
```

Without a record store, tables created this way live in memory and are not persisted.

## Key expressions

Key expressions describe how to build primary and index keys from a record:

```python
from fdb_record_layer.expressions import FanType, concat, field, nest, record_type

field("name")                                    # a single field
concat(field("last_name"), field("first_name"))  # composite key
nest("address", field("city"))                  # field of a nested message
field("tags", fan_type=FanType.FAN_OUT)          # one index entry per element of a repeated field
concat(record_type(), field("id"))               # prefix keys with the record type
```

## Index types

| Type | Builder method | Use case |
|---|---|---|
| VALUE | `add_index(type, name, expr)` | Equality, range and prefix scans |
| COUNT | `add_count_index(type, name, group_by)` | `store.get_count(index, *group)` without scanning |
| SUM | `add_sum_index(type, name, group_by)` | `store.get_sum(index, *group)` without scanning |
| RANK | `add_rank_index(type, name, score)` | Leaderboards: `get_rank`, `get_by_rank` |
| TEXT | `add_text_index(type, name, field)` | Full-text search with `store.text_search(...)` |

## Java interoperability

`JavaCompatibleStore` uses the same subspace layout, record splitting, versionstamp-based record versions and store header as the Java Record Layer, so both can work on the same data. See [`examples/README.md`](examples/README.md#java-interoperability).

## Operational utilities

```python
from fdb_record_layer.utils import get_circuit_breaker, get_health_checker, init_lifecycle

breaker = get_circuit_breaker("fdb")
async with breaker:                  # opens after repeated failures
    await db.run(save_people)

checker = get_health_checker()
checker.register_check("cache", lambda: True)
report = await checker.check_health()
print(report.status.value)           # "healthy"

lifecycle = init_lifecycle()         # handles SIGTERM/SIGINT and runs shutdown hooks
```

## More examples

- [`examples/quickstart.py`](examples/quickstart.py): the code from this README
- [`examples/comprehensive_example.py`](examples/comprehensive_example.py): an e-commerce walkthrough of CRUD, index scans, queries, COUNT indexes, SQL, pagination, schema evolution and the utilities
- [`examples/README.md`](examples/README.md): protobuf workflow, cluster file lookup and a feature comparison with the Java Record Layer

The [Java Record Layer documentation](https://foundationdb.github.io/fdb-record-layer/) explains the underlying concepts.

## Development

```bash
git clone https://github.com/mirkomikulic/fdb-record-layer-python
cd fdb-record-layer-python
pip install -e ".[dev,sql]"

pytest                                   # unit tests (no FoundationDB needed)
ruff check fdb_record_layer tests        # lint
ruff format fdb_record_layer tests       # format
mypy fdb_record_layer                    # type check
```

### Local FoundationDB

```bash
scripts/setup_fdb.sh                     # FoundationDB 8.0.1 in Docker
FDB_VERSION=7.4.10 scripts/setup_fdb.sh  # or another version

python -m grpc_tools.protoc --python_out=tests/integration \
    --proto_path=tests/integration tests/integration/test_records.proto
FDB_CLUSTER_FILE=./fdb.cluster pytest tests/integration
FDB_CLUSTER_FILE=./fdb.cluster python examples/quickstart.py
```

The FoundationDB client library on your machine must have the same major.minor version as the server.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues as described in [SECURITY.md](SECURITY.md). Changes are listed in the [CHANGELOG](CHANGELOG.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Acknowledgments

This project is a Python port of the [FoundationDB Record Layer](https://github.com/FoundationDB/fdb-record-layer), originally developed by Apple.
