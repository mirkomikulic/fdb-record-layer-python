#!/bin/bash
# Setup script for FoundationDB test environment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Setting up FoundationDB test environment ==="

# Create cluster file
CLUSTER_FILE="$PROJECT_DIR/fdb.cluster"
echo "docker:docker@127.0.0.1:4500" > "$CLUSTER_FILE"
echo "Created cluster file: $CLUSTER_FILE"

# Start FDB container
echo "Starting FoundationDB container..."
cd "$PROJECT_DIR"
docker-compose up -d

# Wait for FDB to be healthy
echo "Waiting for FoundationDB to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if docker exec fdb-test fdbcli --exec "status" 2>/dev/null | grep -q "Healthy"; then
        echo "FoundationDB is ready!"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Waiting... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Warning: FoundationDB may not be fully ready, but continuing..."
fi

# Configure database (only needed first time)
echo "Configuring database..."
docker exec fdb-test fdbcli --exec "configure new single memory" 2>/dev/null || true

echo ""
echo "=== FoundationDB is ready ==="
echo "Cluster file: $CLUSTER_FILE"
echo "Connection: 127.0.0.1:4500"
echo ""
echo "Run integration tests with:"
echo "  FDB_CLUSTER_FILE=$CLUSTER_FILE pytest tests/integration/ -v"
