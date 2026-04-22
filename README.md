# My Own Cloud for Large Scale Data Science

Cloud infrastructure project built on top of **OpenNebula**, implementing custom services with our own code.

## Infrastructure

- **OpenNebula server**: `[ipaddress]`
- **SSH tunnel**: `ssh -L 8080:localhost:80 -L 2633:localhost:2633 ubuntu@[ipaddress]
- **OpenNebula UI**: http://localhost:8080
- **OpenNebula XML-RPC**: `localhost:2633`
- **OpenNebula user**: `oneadmin`

---

## Services to Implement

| # | Service | Description |
|---|---------|-------------|
| 1 | **User Management** | Registration, secure login (JWT), account management |
| 2 | **Elastic Compute** | Auto-scaling VM provisioning via OpenNebula API |
| 3 | **Disk Storage** | User-facing object/block storage (MinIO or NFS) |
| 4 | **Container Service** | Spin up/down Docker containers on demand |
| 5 | **Database Service** | Provision PostgreSQL/MySQL instances on demand (DBaaS) |

Additional requirements:
- **SLA**: Jobs run in reasonable time with near-optimal number of VMs
- **Energy saving**: Scale to zero when idle

---

## Architecture

```
[Custom API (FastAPI)]
        |
   [pyone SDK]
        |
[OpenNebula XML-RPC :2633]
        |
[OpenNebula VMs / Storage]
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend API | Python + FastAPI |
| OpenNebula SDK | `pyone` |
| Auth | JWT tokens |
| Object Storage | MinIO (S3-compatible) |
| Containers | Docker on provisioned VMs |
| Database | PostgreSQL (deployed on demand) |

---

## Implementation Phases

### Phase 1 — OpenNebula Connection
- [ ] Install `pyone` and connect to OpenNebula XML-RPC
- [ ] Test basic operations: list VMs, create VM, destroy VM
- [ ] Scaffold project structure

### Phase 2 — User Management Service
- [ ] User registration endpoint
- [ ] Secure login with JWT tokens
- [ ] Account management (update, delete)
- [ ] Map platform users to OpenNebula users via API

### Phase 3 — Elastic Compute Service
- [ ] VM provisioning endpoint (create/destroy on request)
- [ ] Monitor VM CPU/memory load
- [ ] Auto-scaler: spin up VMs when load is high, tear down when idle
- [ ] SLA policy: job queue + scaling rules

### Phase 4 — Disk Storage Service
- [ ] Deploy MinIO on a dedicated VM
- [ ] Expose storage API (upload, download, list, delete)
- [ ] Per-user storage buckets

### Phase 5 — Container Service
- [ ] Deploy Docker on VMs provisioned via OpenNebula
- [ ] API to launch, list, stop containers
- [ ] Map containers to users

### Phase 6 — Database Service (DBaaS)
- [ ] API to provision a PostgreSQL instance per user/request
- [ ] Return connection credentials to the user
- [ ] API to deprovision/delete database instances

### Phase 7 — SLA + Energy Saving
- [ ] Define SLA policies (max wait time, min/max VMs)
- [ ] Implement scale-to-zero when all users are idle
- [ ] Metrics: job wait time, resource utilization, energy proxy metric

### Phase 8 — Testing + Report
- [ ] Write integration tests for each service
- [ ] Collect evaluation metrics
- [ ] Write report following the suggested structure:
  1. Background on OpenNebula and libraries
  2. Materials and methods (machines, software versions, setup guide)
  3. Discussion and conclusions

---

## Project Structure (target)

```
CloudInfrastructure/
├── api/                  # FastAPI application
│   ├── auth/             # User management & JWT
│   ├── compute/          # Elastic VM provisioning
│   ├── storage/          # Disk storage service
│   ├── containers/       # Container service
│   └── database/         # DBaaS
├── opennebula/           # pyone helpers and wrappers
├── scripts/              # Setup and deployment scripts
├── tests/                # Integration tests
└── README.md
```

---

## Deadline

**June 3rd, 2025**
