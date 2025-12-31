# FDB Record Layer Examples

## Quick Start

```bash
python examples/comprehensive_example.py
```

## Prerequisites

### 1. FoundationDB

Install FoundationDB server and client:

```bash
# macOS (Homebrew)
brew install foundationdb

# Ubuntu/Debian
wget https://github.com/apple/foundationdb/releases/download/7.3.27/foundationdb-clients_7.3.27-1_amd64.deb
wget https://github.com/apple/foundationdb/releases/download/7.3.27/foundationdb-server_7.3.27-1_amd64.deb
sudo dpkg -i foundationdb-clients_7.3.27-1_amd64.deb foundationdb-server_7.3.27-1_amd64.deb
```

### 2. Cluster File Configuration

The library looks for the FDB cluster file in this order:

1. **Environment variable** (recommended):
   ```bash
   export FDB_CLUSTER_FILE=/path/to/fdb.cluster
   ```

2. **Standard locations** (checked automatically):
   ```
   ./fdb.cluster                              # Local development (project root)
   /etc/foundationdb/fdb.cluster              # Linux package install
   /usr/local/etc/foundationdb/fdb.cluster    # macOS Homebrew
   ```

For local development, you can copy or symlink:
```bash
# Linux
ln -s /etc/foundationdb/fdb.cluster ./fdb.cluster

# macOS
ln -s /usr/local/etc/foundationdb/fdb.cluster ./fdb.cluster
```

### 3. Protocol Buffers

Install the protobuf compiler:

```bash
# macOS
brew install protobuf

# Ubuntu/Debian
sudo apt install protobuf-compiler

# pip (Python bindings)
pip install protobuf
```

---

## Working with Protocol Buffers

### Schema Definition

Define your schema in a `.proto` file:

```protobuf
// myapp.proto
syntax = "proto3";
package myapp;

message User {
    int64 id = 1;           // Primary key
    string email = 2;
    string name = 3;
    int32 age = 4;
}

message Product {
    int64 id = 1;
    string name = 2;
    int32 price_cents = 3;
}

// Required: Union of all record types
message RecordUnion {
    oneof record {
        User user = 1;
        Product product = 2;
    }
}
```

### Generate Python Bindings

```bash
# Generate from .proto file
protoc --python_out=. myapp.proto

# This creates myapp_pb2.py (auto-generated, don't edit)
```

The generated `*_pb2.py` file contains serialized descriptors. It looks "weird" because modern protobuf embeds the schema as a binary blob rather than generating readable Python classes. This is normal.

### Using Generated Classes

```python
from myapp_pb2 import User, Product, DESCRIPTOR
import fdb_record_layer as frl

# Build metadata from the descriptor
metadata = (
    frl.RecordMetaDataBuilder(DESCRIPTOR)
    .set_record_type("User", primary_key=frl.field("id"))
    .add_index("User", "user_email", frl.field("email"))
    .set_record_type("Product", primary_key=frl.field("id"))
    .build()
)

# Create and save records
user = User(id=1, email="alice@example.com", name="Alice", age=30)
await store.save_record(user)
```

### Regenerating After Schema Changes

When you modify your `.proto` file:

```bash
# Regenerate Python bindings
protoc --python_out=. myapp.proto

# If you added new fields, existing data is forward-compatible
# If you removed fields, ensure schema evolution validation passes
```

### Git Strategy for Generated Files

Option A: **Commit generated files** (simpler CI/CD)
```gitignore
# Don't ignore - commit the generated files
```

Option B: **Ignore and regenerate** (cleaner repo)
```gitignore
*_pb2.py
*_pb2_grpc.py
```

---

## Comprehensive Example

The `comprehensive_example.py` demonstrates all features in an e-commerce scenario:

| Section | Features |
|---------|----------|
| CRUD Operations | save_record, load_record, record_exists, delete_record |
| Index Scanning | VALUE indexes, equality/range/prefix scans, composite indexes |
| Query Builder | Field predicates, AND/OR, IN queries, query explain |
| COUNT Index | Pre-computed aggregations, O(1) count lookups |
| SQL Support | DDL, DML, aggregates, GROUP BY |
| Production Utils | Metrics, caching, circuit breakers, health checks |
| Pagination | Continuation-based cursors |
| Schema Evolution | Safe migration validation |

---

## Feature Comparison: Java vs Python Record Layer

### Fully Implemented

| Feature | Description |
|---------|-------------|
| Protobuf Records | Full Protocol Buffer message support |
| VALUE Indexes | Standard B-tree secondary indexes |
| COUNT/SUM Indexes | Aggregate indexes for fast analytics |
| RANK Indexes | Skip-list based leaderboard queries |
| TEXT Indexes | Full-text search with tokenization |
| Query Builder | Fluent API for query construction |
| Heuristic Planner | Rule-based query optimization |
| Cascades Planner | Cost-based query optimization |
| SQL Layer | Full parser, type system, translator |
| Schema Evolution | Safe migration validation |
| Online Index Build | Background index population |
| Continuations | Cursor-based pagination |
| Production Utils | Pooling, circuit breakers, metrics, health |

### Java Interoperability

Use `JavaCompatibleStore` to read/write data compatible with the Java Record Layer:

```python
from fdb_record_layer import JavaCompatibleStore, FDBRecordVersion

# Use Java-compatible storage format
store = JavaCompatibleStore(ctx, subspace, metadata)

# Save with version tracking (optimistic locking)
version = FDBRecordVersion.incomplete()
await store.save_record(person, version=version)

# Records can now be read by Java applications!
```

Key compatibility features:
- **Same subspace layout** (keyspace constants 0-9)
- **Record splitting** for large records (>100KB)
- **Record versioning** via FDB versionstamps
- **Store header** with format version

### Not Yet Implemented (from Java)

| Feature | Description | Priority |
|---------|-------------|----------|
| Vector Indexes | ML embedding similarity search (16/32/64-bit) | High |
| Bitmap Indexes | Efficient for low-cardinality fields | Medium |
| Geospatial Indexes | R-tree based location queries | Medium |
| Synthetic Records | Virtual records joining multiple types | Medium |
| Atomic Mutations | Increment/append operations | Low |
| Store State | Empty/readable state tracking | Low |
| Key Space Paths | Hierarchical key organization | Low |

### Vector Index Roadmap

The Java Record Layer recently added vector indexes for ML use cases:

```java
// Java example - not yet in Python
Index vectorIndex = new Index("embedding_idx",
    field("embedding").vectorIndex(VectorDimension.of(128)));

// Similarity search
store.executeQuery(
    Query.vectorSimilarity("embedding_idx", queryVector, limit=10));
```

This would be a high-value addition for AI/ML applications.
