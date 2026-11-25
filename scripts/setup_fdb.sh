#!/usr/bin/env bash
# Start a local single-node FoundationDB in Docker for development and tests.
# Usage: scripts/setup_fdb.sh            (FDB 8.0.1)
#        FDB_VERSION=7.4.10 scripts/setup_fdb.sh
#
# The FDB client library on your machine must have the same major.minor version
# as the server, and the `foundationdb` Python package must match it too
# (e.g. pip install "foundationdb~=7.4.0" for a 7.4 client).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CLUSTER_FILE="$PROJECT_DIR/fdb.cluster"
export FDB_VERSION="${FDB_VERSION:-8.0.1}"

echo "=== Starting FoundationDB $FDB_VERSION ==="
echo "docker:docker@127.0.0.1:4500" > "$CLUSTER_FILE"
cd "$PROJECT_DIR"
docker compose up -d

fdb_status() {
    docker exec fdb-test fdbcli --exec "status minimal" --timeout 3 2>/dev/null || true
}

echo "Waiting for fdbserver to respond..."
for _ in $(seq 1 30); do
    fdb_status | grep -q "database" && break
    sleep 2
done

# Creating the database is only needed once; it fails harmlessly if it exists.
docker exec fdb-test fdbcli --exec "configure new single memory" >/dev/null 2>&1 || true

echo "Waiting for the database to become available..."
for _ in $(seq 1 30); do
    if fdb_status | grep -q "database is available"; then
        echo "FoundationDB is ready."
        break
    fi
    sleep 2
done

echo
echo "Cluster file: $CLUSTER_FILE"
echo "Run integration tests with:"
echo "  FDB_CLUSTER_FILE=$CLUSTER_FILE pytest tests/integration/ -v"
