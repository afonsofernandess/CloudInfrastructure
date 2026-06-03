#!/bin/bash
# Start all cloud platform services:
#   1. MinIO object storage
#   2. FastAPI backend (port 8000)
#   3. React dashboard (port 5173)
#
# HOW TO RUN (from project root):
#   bash scripts/start_all.sh
#
# Prerequisites:
#   - SSH tunnel active: ssh -L 8080:localhost:80 -L 2633:localhost:2633 ubuntu@[server-ip]
#   - ~/minio binary present (see README Section 4)
#   - Python deps installed
#   - Node deps installed (cd dashboard && npm install)

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Cleanup on exit ────────────────────────────────────────────────────────────
PIDS=()
cleanup() {
  echo ""
  echo "Stopping all services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null
  echo "All services stopped."
}
trap cleanup EXIT INT TERM

# ── 1. MinIO ───────────────────────────────────────────────────────────────────
# Check if MinIO is already running on port 9002 (e.g. via SSH tunnel)
if curl -sf http://localhost:9002/minio/health/live > /dev/null 2>&1; then
  echo "[1/3] MinIO is already running (detected via port 9002)."
  echo "      Using existing MinIO  →  API: http://localhost:9002"
else
  MINIO_BIN="$HOME/minio"
  if [ ! -f "$MINIO_BIN" ]; then
    echo "[ERROR] MinIO binary not found at $MINIO_BIN"
    echo "  Download it with:"
    echo "  curl -s https://dl.min.io/server/minio/release/linux-amd64/minio -o ~/minio && chmod +x ~/minio"
    exit 1
  fi

  DATA_DIR="$PROJECT_ROOT/minio_data"
  mkdir -p "$DATA_DIR"

  export MINIO_ROOT_USER=minioadmin
  export MINIO_ROOT_PASSWORD=minioadmin123

  echo "[1/3] Starting local MinIO..."
  "$MINIO_BIN" server "$DATA_DIR" --address ":9002" --console-address ":9003" \
    > /tmp/cloud_minio.log 2>&1 &
  PIDS+=($!)

  # Wait for MinIO to be ready
  for i in $(seq 1 15); do
    if curl -sf http://localhost:9002/minio/health/live > /dev/null 2>&1; then
      echo "      MinIO ready  →  API: http://localhost:9002  UI: http://localhost:9003"
      break
    fi
    sleep 0.5
  done
fi

# ── 2. FastAPI backend ─────────────────────────────────────────────────────────
# Clean up any stale process running on port 8000
STALE_PORT_8000_PIDS=$(lsof -t -i :8000 || true)
if [ ! -z "$STALE_PORT_8000_PIDS" ]; then
  echo "Found stale processes on port 8000. Killing them..."
  echo "$STALE_PORT_8000_PIDS" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

echo "[2/3] Starting FastAPI backend..."
UVICORN_BIN="uvicorn"
if [ -f "$PROJECT_ROOT/.venv/bin/uvicorn" ]; then
  UVICORN_BIN="$PROJECT_ROOT/.venv/bin/uvicorn"
elif [ -f "$PROJECT_ROOT/venv/bin/uvicorn" ]; then
  UVICORN_BIN="$PROJECT_ROOT/venv/bin/uvicorn"
fi

"$UVICORN_BIN" api.main:app --port 8000 --reload \
  > /tmp/cloud_api.log 2>&1 &
PIDS+=($!)


# Wait for API to be ready
for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/ > /dev/null 2>&1; then
    echo "      API ready     →  http://localhost:8000  (docs: http://localhost:8000/docs)"
    break
  fi
  sleep 0.5
done

# ── 3. React dashboard ─────────────────────────────────────────────────────────
# Clean up any stale process running on port 5173
STALE_PORT_5173_PIDS=$(lsof -t -i :5173 || true)
if [ ! -z "$STALE_PORT_5173_PIDS" ]; then
  echo "Found stale processes on port 5173. Killing them..."
  echo "$STALE_PORT_5173_PIDS" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

if [ ! -d "$PROJECT_ROOT/dashboard/node_modules" ]; then
  echo "[3/3] Installing dashboard dependencies..."
  cd "$PROJECT_ROOT/dashboard" && npm install --silent
  cd "$PROJECT_ROOT"
fi

echo "[3/3] Starting React dashboard..."
cd "$PROJECT_ROOT/dashboard"
npm run dev -- --host \
  > /tmp/cloud_dashboard.log 2>&1 &
PIDS+=($!)
cd "$PROJECT_ROOT"

sleep 2
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║        Cloud Platform — All services up      ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Dashboard  →  http://localhost:5173         ║"
echo "║  API        →  http://localhost:8000         ║"
echo "║  API docs   →  http://localhost:8000/docs    ║"
echo "║  MinIO UI   →  http://localhost:9003         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "Logs: /tmp/cloud_minio.log | /tmp/cloud_api.log | /tmp/cloud_dashboard.log"
echo "Press Ctrl+C to stop everything."
echo ""

# Keep script alive and tail all logs to stdout
tail -f /tmp/cloud_minio.log /tmp/cloud_api.log /tmp/cloud_dashboard.log &
PIDS+=($!)

wait "${PIDS[0]}"
