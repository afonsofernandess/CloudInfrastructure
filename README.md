# My Own Cloud for Large Scale Data Science

Custom cloud infrastructure built on top of **OpenNebula**, re-implementing cloud services with our own code.

---

## Table of Contents

1. [Infrastructure & Prerequisites](#1-infrastructure--prerequisites)
2. [Project Structure](#2-project-structure)
3. [Installation](#3-installation)
4. [Starting the API Server](#4-starting-the-api-server)
5. [Phase 1 — OpenNebula Connection](#5-phase-1--opennebula-connection)
6. [Phase 2 — User Management](#6-phase-2--user-management)
7. [Phase 3 — Elastic Compute](#7-phase-3--elastic-compute)
8. [Phase 4 — Disk Storage](#8-phase-4--disk-storage)
9. [Phase 5 — Container Service](#9-phase-5--container-service)
10. [Phase 6 — Database Service (DBaaS)](#10-phase-6--database-service-dbaas)
11. [Dashboard — Web UI](#11-dashboard--web-ui)
12. [Implemented Services Roadmap](#12-implemented-services-roadmap)

---

## 1. Infrastructure & Prerequisites

| Item | Value |
|------|-------|
| OpenNebula server | `192.168.1.177` |
| OpenNebula version | `7.2.0` |
| OpenNebula UI | http://localhost:8080 (via tunnel) |
| OpenNebula XML-RPC | `localhost:2633` (via tunnel) |
| OpenNebula admin user | `oneadmin` |

**The SSH tunnel must be active before running anything:**

```bash
ssh -L 8080:localhost:80 -L 2633:localhost:2633 ubuntu@[server-ip]
```

This forwards:
- Port `8080` → OpenNebula web UI
- Port `2633` → OpenNebula XML-RPC API (used by our backend)

---

## 2. Project Structure

```
CloudInfrastructure/
├── api/
│   ├── main.py                    # FastAPI app entry point + autoscaler lifespan
│   ├── database.py                # SQLite setup and DB session dependency
│   ├── auth/
│   │   ├── models.py              # User table (SQLAlchemy)
│   │   ├── schemas.py             # Request/response shapes (Pydantic)
│   │   ├── jwt.py                 # JWT token creation and verification
│   │   ├── router.py              # Auth endpoints (register, login, me, update, delete)
│   │   └── opennebula_sync.py     # Mirrors user actions to OpenNebula
│   ├── compute/
│   │   ├── models.py              # VMInstance table (tracks user → VM ownership)
│   │   ├── schemas.py             # VMCreate, VMResponse, ClusterStatus
│   │   ├── sla.py                 # SLA constants (min/max VMs, CPU thresholds)
│   │   ├── monitor.py             # Collects avg CPU/memory from active VMs
│   │   ├── autoscaler.py          # Background thread: scales VMs up/down per SLA
│   │   └── router.py              # Compute endpoints (provision, list, detail, destroy, status)
│   ├── storage/
│   │   ├── minio_client.py        # MinIO wrapper — bucket management, upload, download, list, delete
│   │   ├── schemas.py             # FileInfo, UploadResponse shapes
│   │   └── router.py              # Storage endpoints (upload, list, download, delete)
│   └── containers/
│       ├── docker_client.py       # Docker SDK wrapper — launch, list, get, start, stop, remove
│       ├── schemas.py             # ContainerCreate, ContainerResponse shapes
│       └── router.py              # Container endpoints (launch, list, detail, start, stop, remove)
├── opennebula/
│   ├── connection.py              # OpenNebula client factory (pyone)
│   └── vm_manager.py             # Low-level VM operations: create, destroy, get, list
├── scripts/
│   ├── start_minio.sh             # Starts the MinIO object storage server
│   ├── test_connection.py         # Phase 1 connection test script
│   └── test_autoscaler.py         # Autoscaler test with real OpenNebula VMs
├── minio_data/                    # MinIO data directory (auto-created, git-ignored)
├── cloud.db                       # SQLite database (auto-created on first run)
├── GUIDELINES.md                  # Implementation plan and phases
└── README.md                      # This file
```

### File Descriptions

**`opennebula/connection.py`**
Single place that holds the OpenNebula endpoint and credentials. Exports `get_client()` which returns an authenticated `pyone.OneServer`. Every other file imports from here instead of repeating credentials.

**`api/database.py`**
Sets up a local SQLite database (`cloud.db`). Exports `get_db()`, a FastAPI dependency that opens and closes a DB session per request.

**`api/auth/models.py`**
Defines the `users` table with: `id`, `username`, `email`, `hashed_password`, `is_active`, `is_admin`, `one_user_id` (the corresponding OpenNebula user ID), `created_at`.

**`api/auth/schemas.py`**
Pydantic models for API input/output: `UserRegister`, `UserLogin`, `UserUpdate`, `UserResponse`, `TokenResponse`.

**`api/auth/jwt.py`**
Creates JWT tokens (HS256, 24h expiry). Exports `get_current_user`, a FastAPI dependency that decodes the token from the `Authorization` header and returns the user.

**`api/auth/opennebula_sync.py`**
Three functions that mirror user operations to OpenNebula via `pyone`:
- `create_one_user(username, password)` → returns the OpenNebula user ID
- `update_one_user_password(one_user_id, new_password)`
- `delete_one_user(one_user_id)`

**`api/auth/router.py`**
All 5 auth endpoints (see Phase 2 below).

**`api/main.py`**
Creates all DB tables on startup, mounts both routers, starts the autoscaler background thread on startup and stops it on shutdown via FastAPI's lifespan.

**`opennebula/vm_manager.py`**
Low-level pyone VM operations: `create_vm`, `destroy_vm`, `get_vm`, `list_all_vms`. Converts raw pyone objects into plain dicts with human-readable state names and metrics.

**`api/compute/models.py`**
Defines the `vm_instances` table: `id`, `user_id` (FK to users), `one_vm_id` (OpenNebula VM ID), `name`, `template_id`, `created_at`.

**`api/compute/schemas.py`**
Pydantic shapes: `VMCreate` (name, template_id), `VMResponse` (includes live CPU/memory from OpenNebula), `ClusterStatus` (aggregate metrics + SLA config).

**`api/compute/sla.py`**
All SLA constants in one place: `MIN_VMS=1`, `MAX_VMS=5`, `SCALE_UP_CPU_PCT=70`, `SCALE_DOWN_CPU_PCT=20`, `SCALE_DOWN_WINDOW_SEC=120`, `CHECK_INTERVAL_SEC=30`.

**`api/compute/monitor.py`**
Calls `list_all_vms()`, filters to ACTIVE state, and returns aggregate `avg_cpu_pct`, `avg_memory_mb`, `total_vms`, `active_vms`.

**`api/compute/autoscaler.py`**
Background `threading.Thread` that runs every 30 seconds. If avg CPU > 70% and VM count < 5 → creates a new VM. If avg CPU < 20% and VM count > 1 → destroys the idle VM (only after it has been idle for 2 minutes to avoid flapping). Exposed as a singleton `autoscaler` imported by `main.py`.

**`api/compute/router.py`**
5 endpoints mounted at `/compute`: provision VM, list VMs, get VM detail, destroy VM, cluster status. Only shows the calling user's own VMs. Auto-cleans DB records for VMs already terminated in OpenNebula (state DONE).

**`scripts/test_autoscaler.py`**
Real VM autoscaler test — temporarily overrides SLA thresholds in memory, triggers a real scale up (creates a VM in OpenNebula), waits for it to fully boot (LCM_STATE=RUNNING), then forces a scale down (destroys it). Always restores original SLA values at the end via a `finally` block.

**`scripts/start_minio.sh`**
Downloads and starts the MinIO object storage server. Exposes the API on port `9002` and the web console on port `9003`. Data is persisted in `./minio_data/`. Must be running before starting the API server.

**`api/storage/minio_client.py`**
MinIO Python client wrapper. Each user gets a dedicated bucket named `user-{username}`, created automatically on first upload. Exports: `upload_file`, `list_files`, `download_file`, `delete_file`, `ensure_bucket`.

**`api/storage/schemas.py`**
Pydantic shapes: `FileInfo` (filename, size_bytes, last_modified) and `UploadResponse` (filename, bucket, size_bytes, message).

**`api/storage/router.py`**
4 endpoints mounted at `/storage`: upload file (multipart form), list files, download file, delete file. All endpoints are per-user isolated — users can only see and access their own bucket.

**`api/containers/docker_client.py`**
Docker SDK wrapper. Every container launched gets a Docker label `cloud_user=<username>` applied automatically. All list/start/stop/remove operations filter by this label so users can never access each other's containers. Container names are prefixed with the username (`afonso-webserver`) to avoid naming conflicts. Uses `create()` + `start()` separately so that if start fails (e.g. image error), the stuck container is automatically removed before raising the error.

**`api/containers/schemas.py`**
Pydantic shapes: `ContainerCreate` (image, name, optional env dict, optional list of container ports to expose) and `ContainerResponse` (container_id, name, image, status, ports, created).

**`api/containers/router.py`**
6 endpoints mounted at `/containers`: launch container, list containers, get container detail, start container, stop container, remove container.

---

## 3. Installation

**Python dependencies:**

```bash
pip install pyone fastapi uvicorn "python-jose[cryptography]" "passlib[bcrypt]" sqlalchemy "pydantic[email]" "bcrypt==4.0.1" minio python-multipart docker
```

> Note: `bcrypt` must be pinned to `4.0.1` — newer versions are incompatible with `passlib`.

**MinIO server binary (Phase 4):**

```bash
curl -s https://dl.min.io/server/minio/release/linux-amd64/minio -o ~/minio && chmod +x ~/minio
```

---

## 4. Starting the API Server

Make sure the SSH tunnel is active first (see Section 1), then:

```bash
uvicorn api.main:app --reload --port 8000
```

- API base URL: http://localhost:8000
- Interactive docs (Swagger UI): **http://localhost:8000/docs**
- Health check: `GET http://localhost:8000/`

---

## 5. Phase 1 — OpenNebula Connection

Tests that the tunnel is up and the credentials are valid. Lists VMs, templates, datastores, and hosts.

```bash
python scripts/test_connection.py
```

**Expected output:**
```
[OK] Connected! OpenNebula version: 7.2.0
[OK] Users in OpenNebula: oneadmin, serveradmin
[OK] Virtual Machines (0 found)
[OK] VM Templates: Alpine Linux 3.20
[OK] Datastores: system, default, files
[OK] Hosts: localhost  state=2 (MONITORED = healthy)
```

If you see `[FAIL] Could not connect` → the SSH tunnel is not running.

---

## 6. Phase 2 — User Management

The API server must be running (`uvicorn api.main:app --reload --port 8000`).

### Register a new user

```bash
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","email":"test@cloud.com","password":"secret123"}' \
  | python3 -m json.tool
```

**Expected response:**
```json
{
    "id": 1,
    "username": "testuser",
    "email": "test@cloud.com",
    "is_active": true,
    "is_admin": false,
    "one_user_id": 2,
    "created_at": "2026-04-22T11:23:17"
}
```

`one_user_id` is the ID assigned by OpenNebula — confirms the user was created there too.

### Verify the user exists in OpenNebula

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from opennebula.connection import get_client
client = get_client()
for u in client.userpool.info().USER:
    print(f'[{u.ID}] {u.NAME}')
"
```

You should see your new user listed alongside `oneadmin` and `serveradmin`.

### Login and get a JWT token

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"secret123"}' \
  | python3 -m json.tool
```

**Expected response:**
```json
{
    "access_token": "eyJhbGci...",
    "token_type": "bearer"
}
```

The token is valid for **24 hours**. Copy it for the next steps.

### Get your profile (requires token)

```bash
curl -s http://localhost:8000/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  | python3 -m json.tool
```

### Update email or password (requires token)

```bash
curl -s -X PUT http://localhost:8000/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"email":"newemail@cloud.com","password":"newpassword"}' \
  | python3 -m json.tool
```

Password changes are automatically mirrored to OpenNebula.

### Delete your account (requires token)

```bash
curl -s -X DELETE http://localhost:8000/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

This removes the user from both the local database and OpenNebula.

### Test with a wrong token (should fail)

```bash
curl -s http://localhost:8000/auth/me \
  -H "Authorization: Bearer invalidtoken" \
  | python3 -m json.tool
# Expected: {"detail": "Invalid or expired token"}
```

---

## 7. Phase 3 — Elastic Compute

The API server must be running and the SSH tunnel must be active.

### Provision a VM

```bash
curl -s -X POST http://localhost:8000/compute/vms \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-first-vm"}' | python3 -m json.tool
```

**Expected response:**
```json
{
    "id": 1,
    "one_vm_id": 3,
    "name": "my-first-vm",
    "template_id": 0,
    "state": "PENDING",
    "cpu_usage_pct": 0.0,
    "memory_mb": 0.0,
    "created_at": "2026-04-22T14:22:21"
}
```

`one_vm_id` is the VM's ID in OpenNebula. State starts as `PENDING` and transitions to `ACTIVE` once the hypervisor boots it.

### List your VMs

```bash
curl -s http://localhost:8000/compute/vms \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

### Get a single VM with live metrics

```bash
curl -s http://localhost:8000/compute/vms/1 \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

Once the VM is running you will see `cpu_usage_pct` and `memory_mb` populated with live values from OpenNebula.

### Destroy a VM

```bash
curl -s -X DELETE http://localhost:8000/compute/vms/1 \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

Returns `204 No Content` on success. The VM is terminated in OpenNebula and removed from the local DB.

### Check cluster status and autoscaler

```bash
curl -s http://localhost:8000/compute/status \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

**Expected response:**
```json
{
    "total_vms": 1,
    "active_vms": 1,
    "avg_cpu_pct": 12.5,
    "autoscaler_enabled": true,
    "min_vms": 1,
    "max_vms": 5,
    "scale_up_threshold_pct": 70.0,
    "scale_down_threshold_pct": 20.0
}
```

### Verify the VM exists in OpenNebula

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from opennebula.connection import get_client
client = get_client()
pool = client.vmpool.info(-2, -1, -1, -1)
for vm in pool.VM:
    print(f'[{vm.ID}] {vm.NAME}  state={vm.STATE}')
"
```

State `3` = ACTIVE (running).

### Watch the autoscaler in the server logs

The autoscaler logs its decisions every 30 seconds in the uvicorn terminal:

```
INFO:autoscaler:AutoScaler started (interval=30s)
INFO:autoscaler:AutoScaler check — active=1 total=1 avg_cpu=12.5%
INFO:autoscaler:Scaled UP — created VM 'autoscale-vm-1745330000' (one_vm_id=4)
INFO:autoscaler:Scaled DOWN — destroyed VM one_vm_id=4 (idle >120s)
```

### SLA rules (defined in `api/compute/sla.py`)

| Rule | Value |
|------|-------|
| Minimum VMs always running | 1 |
| Maximum VMs allowed | 5 |
| Scale up when avg CPU exceeds | 70% |
| Scale down when avg CPU drops below | 20% |
| Idle window before scale down | 120 seconds |
| Autoscaler check interval | 30 seconds |

---

## 8. Phase 4 — Disk Storage

MinIO must be running and the API server must be running.

### Start MinIO (required before the API)

Open a dedicated terminal and run:

```bash
bash scripts/start_minio.sh
```

Expected output:
```
Starting MinIO...
  API  → http://localhost:9002
  UI   → http://localhost:9003
  Data → ./minio_data
```

Keep this terminal open — MinIO must stay running.

### Verify MinIO is up

```bash
curl -s http://localhost:9002/minio/health/live && echo "MinIO is up"
```

You can also open the **web console** at http://localhost:9003 and log in with `minioadmin` / `minioadmin123` to browse buckets and files visually.

### Upload a file

```bash
curl -s -X POST http://localhost:8000/storage/upload \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -F "file=@/path/to/your/file.txt" | python3 -m json.tool
```

**Expected response:**
```json
{
    "filename": "file.txt",
    "bucket": "user-afonso",
    "size_bytes": 35,
    "message": "File uploaded successfully"
}
```

`bucket` shows which MinIO bucket the file was stored in — one bucket per user, created automatically on first upload.

### List your files

```bash
curl -s http://localhost:8000/storage/files \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

**Expected response:**
```json
[
    {
        "filename": "file.txt",
        "size_bytes": 35,
        "last_modified": "2026-04-22T17:14:23.296000Z"
    }
]
```

### Download a file

```bash
curl -s http://localhost:8000/storage/download/file.txt \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  --output downloaded_file.txt
```

The file is returned as a binary download with `Content-Disposition: attachment`.

### Delete a file

```bash
curl -s -X DELETE http://localhost:8000/storage/files/file.txt \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" -w "HTTP %{http_code}"
# Expected: HTTP 204
```

### Verify per-user bucket isolation

Each user has a completely separate bucket. Log in as a different user and list their files — they will never see each other's uploads:

```bash
# Bucket names follow the pattern: user-{username}
# afonso   → bucket: user-afonso
# testuser → bucket: user-testuser
```

You can confirm this in the MinIO console at http://localhost:9003 — each user has their own bucket listed separately.

### Verify from MinIO directly (Python)

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from api.storage.minio_client import get_client
client = get_client()
for bucket in client.list_buckets():
    print(f'Bucket: {bucket.name}  created={bucket.creation_date}')
"
```

---

## 9. Phase 5 — Container Service

Docker must be installed and running on the machine. The API server must be running.

### Verify Docker is running

```bash
docker --version
docker info --format '{{.ServerVersion}}'
```

Expected: prints the Docker version (e.g. `29.4.0`). If Docker is not running, start it first.

### Launch a container

The `ports` field is a **list of container ports to expose** — Docker automatically assigns a free host port for each. This avoids port conflicts between users entirely.

```bash
curl -s -X POST http://localhost:8000/containers -H "Authorization: Bearer YOUR_TOKEN_HERE" -H "Content-Type: application/json" -d '{"image":"nginx:alpine","name":"webserver","ports":["80/tcp"]}' | python3 -m json.tool
```

**Expected response:**
```json
{
    "container_id": "d44c8ae1ffae",
    "name": "afonso-webserver",
    "image": "nginx:alpine",
    "status": "running",
    "ports": {
        "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32768"}]
    },
    "created": "2026-04-23T00:55:56Z"
}
```

The container name is automatically prefixed with the username (`afonso-webserver`). The `HostPort` in the response tells you which port Docker assigned — use that to reach the service. Two different users can both expose `80/tcp` with no conflict — Docker picks a different free host port for each.

You can also launch containers with environment variables and multiple ports:

```bash
curl -s -X POST http://localhost:8000/containers -H "Authorization: Bearer YOUR_TOKEN_HERE" -H "Content-Type: application/json" -d '{"image":"python:3.12-alpine","name":"myapp","env":{"MY_VAR":"hello","DEBUG":"true"},"ports":["8080/tcp"]}' | python3 -m json.tool
```

### Verify the container is actually running

Use the `HostPort` from the launch response to reach the service directly:

```bash
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:32768
# Expected: HTTP 200
```

Or verify from Docker directly:

```bash
docker ps --filter "label=cloud_user=afonso"
```

Every container launched through our API has the label `cloud_user=<username>` — this is how user isolation is enforced at the Docker level.

### List your containers

```bash
curl -s http://localhost:8000/containers \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

Shows all containers (running and stopped) belonging to the logged-in user. Other users' containers are never returned.

### Get a single container's details

```bash
curl -s http://localhost:8000/containers/CONTAINER_ID \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

### Stop a running container

```bash
curl -s -X POST http://localhost:8000/containers/CONTAINER_ID/stop \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

**Expected response:** same as detail but `"status": "exited"`. The container is stopped but not deleted — you can still see it in the list and start it again.

### Start a stopped container

```bash
curl -s -X POST http://localhost:8000/containers/CONTAINER_ID/start \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

Docker reassigns a free host port when the container starts again (the port may differ from the original). The response includes the new `HostPort`.

> **Note:** if the port is unavailable (e.g. another container took it), you will get a clear error: `"Port already in use — stop the other container using that port first"`. Since ports are auto-assigned this should be rare.

### Remove a container

```bash
curl -s -X DELETE http://localhost:8000/containers/CONTAINER_ID \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" -w "HTTP %{http_code}"
# Expected: HTTP 204
```

Force-removes the container even if still running. After this it no longer appears in the list.

### Verify per-user isolation

Try to access another user's container — it will be rejected:

```bash
curl -s -X POST http://localhost:8000/containers/AFONSOS_CONTAINER_ID/stop \
  -H "Authorization: Bearer TESTUSER_TOKEN" | python3 -m json.tool
# Expected: {"detail": "Container does not belong to this user"}
```

### Endpoint summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/containers` | Launch a new container |
| `GET` | `/containers` | List your containers |
| `GET` | `/containers/{id}` | Get container details |
| `POST` | `/containers/{id}/start` | Start a stopped container |
| `POST` | `/containers/{id}/stop` | Stop a running container |
| `DELETE` | `/containers/{id}` | Remove a container |

---

## 10. Phase 6 — Database Service (DBaaS)

Docker must be installed and running. The API server must be running.

Each provisioned database is a `postgres:16-alpine` Docker container with:
- A randomly generated 24-character password
- An auto-assigned host port (mapped to PostgreSQL's `5432`)
- A Docker label `cloud_db_user=<username>` for per-user isolation

### Provision a PostgreSQL instance

```bash
curl -s -X POST http://localhost:8000/databases \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-db"}' | python3 -m json.tool
```

**Expected response:**
```json
{
    "id": 1,
    "instance_name": "my-db",
    "container_id": "a3f1b2c4d5e6",
    "status": "running",
    "credentials": {
        "host": "localhost",
        "port": 54321,
        "db_name": "afonso",
        "db_user": "afonso",
        "db_password": "Xk9mPqR2vLnYcZ7wJtHsAe3B",
        "connection_string": "postgresql://afonso:Xk9mPqR2vLnYcZ7wJtHsAe3B@localhost:54321/afonso"
    },
    "created_at": "2026-04-23T12:00:00"
}
```

You can optionally specify a custom database name:

```bash
curl -s -X POST http://localhost:8000/databases \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"name":"analytics","db_name":"analytics_db"}' | python3 -m json.tool
```

### Connect with psql

Use the `connection_string` from the response directly:

```bash
psql "postgresql://afonso:Xk9mPqR2vLnYcZ7wJtHsAe3B@localhost:54321/afonso"
```

Or verify from Python:

```bash
python3 -c "
import psycopg2
conn = psycopg2.connect('postgresql://afonso:PASSWORD@localhost:PORT/afonso')
print('Connected:', conn.server_version)
conn.close()
"
```

### List your database instances

```bash
curl -s http://localhost:8000/databases \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

Returns all instances belonging to the logged-in user with live status from Docker.

### Get a single instance (with credentials)

```bash
curl -s http://localhost:8000/databases/1 \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" | python3 -m json.tool
```

### Deprovision (delete) a database instance

```bash
curl -s -X DELETE http://localhost:8000/databases/1 \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" -w "HTTP %{http_code}"
# Expected: HTTP 204
```

Stops and removes the Docker container and deletes the record from the local database. All data stored in that PostgreSQL instance is permanently destroyed.

### Verify isolation

```bash
# Containers follow the naming pattern: db-{username}-{instance_name}
docker ps --filter "label=cloud_db_user=afonso"
```

### Endpoint summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/databases` | Provision a new PostgreSQL instance |
| `GET` | `/databases` | List your database instances |
| `GET` | `/databases/{id}` | Get instance details + credentials |
| `DELETE` | `/databases/{id}` | Deprovision and delete instance |

---

## 11. Dashboard — Web UI

A full React 18 + Vite management dashboard is included in the `dashboard/` directory.

### Quick start (all services with one command)

Make sure the **SSH tunnel is active** first, then from the project root:

```bash
bash scripts/start_all.sh
```

This starts all three services in the background and streams their logs to your terminal:

| Service | URL |
|---------|-----|
| Dashboard (React) | http://localhost:5173 |
| API (FastAPI) | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| MinIO UI | http://localhost:9003 |

Press `Ctrl+C` to stop everything cleanly.

> Individual logs are also written to `/tmp/cloud_minio.log`, `/tmp/cloud_api.log`, `/tmp/cloud_dashboard.log`.

### Manual start (separate terminals)

```bash
# Terminal 1 — MinIO
bash scripts/start_minio.sh

# Terminal 2 — API
uvicorn api.main:app --reload --port 8000

# Terminal 3 — Dashboard
cd dashboard && npm run dev
```

### Dashboard pages

| Page | Route | Description |
|------|-------|-------------|
| Overview | `/dashboard` | Summary cards, live CPU chart, autoscaler panel, quick actions |
| Virtual Machines | `/dashboard/vms` | Provision/destroy VMs, live metrics, SLA status |
| Containers | `/dashboard/containers` | Launch/start/stop/remove Docker containers, grid + table view |
| Storage | `/dashboard/storage` | Drag-and-drop upload, file browser, download/delete |
| Databases | `/dashboard/databases` | Provision PostgreSQL instances, reveal credentials |
| Settings | `/dashboard/settings` | Update profile, change password, delete account |

### Dashboard tech stack

- **React 18 + Vite** — fast dev server and build
- **Tailwind CSS** — dark mode by default (toggle in top bar)
- **TanStack React Query** — data fetching with 10s auto-refresh on live resources
- **Zustand** — auth state (JWT token persisted in `localStorage`)
- **Recharts** — live CPU usage area chart on the overview page
- **react-hot-toast** — toast notifications for every API action

### First-time setup

```bash
cd dashboard && npm install
```

The dashboard reads the API base URL from `dashboard/.env` (created from `.env.example`):

```bash
cp dashboard/.env.example dashboard/.env
# Edit VITE_API_URL if your backend runs on a different port
```

---

## 12. Implemented Services Roadmap

| Phase | Service | Status |
|-------|---------|--------|
| 1 | OpenNebula connection + test script | Done |
| 2 | User registration, login, JWT auth, account management | Done |
| 3 | Elastic compute — VM provisioning + auto-scaler | Done |
| 4 | Disk storage — MinIO object storage | Done |
| 5 | Container service — Docker on demand | Done |
| 6 | Database service — PostgreSQL on demand (DBaaS) | Done |
| 7 | SLA + energy saving (scale-to-zero) | Pending |
| 8 | Tests + evaluation metrics + report | Pending |

