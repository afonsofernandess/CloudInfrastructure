#!/bin/bash
# Start MinIO object storage server.
#
# HOW TO RUN:
#   bash scripts/start_minio.sh
#
# MinIO API  → http://localhost:9000  (used by our FastAPI)
# MinIO UI   → http://localhost:9001  (browser console)
# Credentials: minioadmin / minioadmin123
# Data stored in: ./minio_data/

MINIO_BIN="$HOME/minio"
DATA_DIR="$(pwd)/minio_data"

mkdir -p "$DATA_DIR"

export MINIO_ROOT_USER=minioadmin
export MINIO_ROOT_PASSWORD=minioadmin123

echo "Starting MinIO..."
echo "  API  → http://localhost:9002"
echo "  UI   → http://localhost:9003"
echo "  Data → $DATA_DIR"

"$MINIO_BIN" server "$DATA_DIR" --address ":9002" --console-address ":9003"
