# FDB Record Layer Examples

## Quick Start

Run the comprehensive example that demonstrates all features:

```bash
python examples/comprehensive_example.py
```

## Comprehensive Example

The `comprehensive_example.py` file demonstrates all major features in a realistic e-commerce scenario:

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

## Legacy Phase Examples

The `test_phase*.py` files are development test scripts from the original implementation:

| File | Focus |
|------|-------|
| test_phase1.py | Basic record store and index scanning |
| test_phase2.py | Query builder and heuristic planner |
| test_phase3.py | Advanced indexes (COUNT, RANK, TEXT) |
| test_phase4.py | Cascades cost-based optimizer |
| test_phase5.py | Schema evolution and metadata persistence |
| test_phase6.py | SQL layer (lexer, parser, translator) |
| test_phase7.py | Production utilities (batch, cache, metrics) |

## Proto Definition

The `sample.proto` file defines the test schema. To regenerate Python bindings:

```bash
protoc --python_out=. examples/sample.proto
```

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

### Not Yet Implemented (from Java)

| Feature | Description | Priority |
|---------|-------------|----------|
| Vector Indexes | ML embedding similarity search (16/32/64-bit) | High |
| Bitmap Indexes | Efficient for low-cardinality fields | Medium |
| Geospatial Indexes | R-tree based location queries | Medium |
| Synthetic Records | Virtual records joining multiple types | Medium |
| Record Versioning | Optimistic locking with version tracking | Low |
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
