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
7. [Implemented Services Roadmap](#7-implemented-services-roadmap)

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
│   ├── main.py                    # FastAPI app entry point
│   ├── database.py                # SQLite setup and DB session dependency
│   └── auth/
│       ├── models.py              # User table (SQLAlchemy)
│       ├── schemas.py             # Request/response shapes (Pydantic)
│       ├── jwt.py                 # JWT token creation and verification
│       ├── router.py              # Auth endpoints (register, login, me, update, delete)
│       └── opennebula_sync.py     # Mirrors user actions to OpenNebula
├── opennebula/
│   └── connection.py              # OpenNebula client factory (pyone)
├── scripts/
│   └── test_connection.py         # Phase 1 connection test script
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
Creates all DB tables on startup, mounts the auth router, exposes `GET /` health check.

---

## 3. Installation

```bash
pip install pyone fastapi uvicorn "python-jose[cryptography]" "passlib[bcrypt]" sqlalchemy "pydantic[email]" "bcrypt==4.0.1"
```

> Note: `bcrypt` must be pinned to `4.0.1` — newer versions are incompatible with `passlib`.

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

## 7. Implemented Services Roadmap

| Phase | Service | Status |
|-------|---------|--------|
| 1 | OpenNebula connection + test script | Done |
| 2 | User registration, login, JWT auth, account management | Done |
| 3 | Elastic compute — VM provisioning + auto-scaler | Pending |
| 4 | Disk storage — MinIO object storage | Pending |
| 5 | Container service — Docker on demand | Pending |
| 6 | Database service — PostgreSQL on demand (DBaaS) | Pending |
| 7 | SLA + energy saving (scale-to-zero) | Pending |
| 8 | Tests + evaluation metrics + report | Pending |
