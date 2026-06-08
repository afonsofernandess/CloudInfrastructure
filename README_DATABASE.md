# Database-on-Demand (DBaaS) Service Guide

This guide describes the architecture, configurations, security mechanisms, and testing procedures for the **Phase 6 Database-on-Demand (DBaaS)** service. This service allows users to provision, manage, deprovision, and monitor PostgreSQL instances running inside isolated Docker containers across their active OpenNebula virtual machines.

---

## 1. Architecture Overview

Rather than running databases on a static server, the DBaaS service dynamically provisions lightweight, isolated database instances directly inside the user's VM host network.

```mermaid
graph TD
    Client[React Dashboard / API Client] -->|HTTP Requests| API[FastAPI Backend]
    
    subgraph Local Metadata Store
        API -->|1. Lookup Active VMs & DB States| SQLite[(SQLite DB: cloud.db)]
    end
    
    subgraph SSH Gateway Tunneling
        API -->|2. SSH Connect to Host Daemon| SSH[SSH Tunnel / Proxy]
        SSH -->|3. Docker Exec Command| DockerEngine[Docker Daemon on VM]
    end

    subgraph isolated Postgres Instance
        DockerEngine -->|4. Launch Container| PG[Postgres Container: 16-alpine]
        PG -->|5. Persistent Volume Map| HostDisk[/var/lib/postgresql/data-instance_name]
        PG -->|6. Expose Port 5432| HostPort[Auto-assigned Host Port e.g., 32768]
    end
```

### Key Architectural Concepts
1. **Dynamic Target Selection:** Users can choose which of their active VMs will host the database container. If no VM is specified, the system utilizes the load-balanced VM Selection algorithm to pick the host with the lowest density of containers.
2. **Containerized Database Isolation:** Database instances run as `postgres:16-alpine` Docker containers. Isolation is enforced using labels (`cloud_db_user=<username>`), ensuring users only see and manage their own databases.
3. **Auto-Port Mapping:** The host port is automatically and randomly assigned by the Docker engine on the host VM (mapping container port `5432/tcp -> None` on host). This prevents port conflicts and allows launching multiple database instances on the same VM.
4. **Volume Persistence:** To ensure database data is not lost when containers are restarted or recreated, the host volume `/var/lib/postgresql/data-{instance_name}` is mounted into the container's data directory `/var/lib/postgresql/data`.

---

## 2. Detailed Step-by-Step Flows

### A. Database Provisioning (`POST /databases`)

When a user requests to provision a database instance:
1. **VM Verification:** The API invokes `ensure_user_has_running_vm` to ensure that the target VM is fully booted (`LCM_STATE=3`) and accepting Docker commands over SSH.
2. **Leftover Cleanup:** If a container with the same name exists but is stopped, it is forcefully removed to avoid naming collisions.
3. **Password Generation:** The API generates a secure, 24-character random password using Python's `secrets` module.
4. **Container Launch:** Instructs the Docker Engine on the VM to create and start a container with:
   * **Image:** `postgres:16-alpine`
   * **Label:** `cloud_db_user=<username>`
   * **Environment Variables:** `POSTGRES_DB`, `POSTGRES_USER` (set to `username`), and the generated `POSTGRES_PASSWORD`.
   * **Volume Mounting:** `/var/lib/postgresql/data-{instance_name}` mapping to `/var/lib/postgresql/data` (read-write mode).
5. **Port Binding Polling:** The system polls the container ports for up to 60 seconds to detect the dynamically mapped host port.
6. **SQLite Registry:** Inserts a new `DBInstance` record to store the plaintext credentials, port mapping, and host VM association.

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI Backend
    participant DB as SQLite DB
    participant VM as Remote VM (Docker)
    autonumber

    Client->>API: POST /databases {name, db_name, vm_id}
    API->>VM: Ensure VM is running and Docker is reachable
    VM-->>API: Ready
    API->>API: Generate secure 24-char password
    API->>VM: Docker Create (Image: postgres:16-alpine, Vol: data-name)
    API->>VM: Docker Start Container
    loop Poll Port Mapping (up to 60s)
        API->>VM: Inspect container ports
        VM-->>API: returns HostPort (e.g. 32768)
    end
    API->>DB: Save DBInstance record (credentials, HostPort, vm_id)
    DB-->>API: Success (Commit)
    API-->>Client: HTTP 201 Created (Connection DSN & Credentials)
```

### B. Live Metrics Queries (`GET /databases/{id}/metrics`)

Since database instances are deployed inside private cloud networks (`172.16.100.*`), the backend cannot execute SQL queries directly against the exposed host port. Instead, metrics are gathered by routing SQL queries over SSH directly into the running Docker container:

1. **Active Connections Query:**
   ```bash
   ssh -o StrictHostKeyChecking=no {ssh_user}@{ip} \
     "docker exec -e PGPASSWORD={password} {container_name} \
      psql -U {db_user} -d {db_name} -t -c \
      \"SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';\""
   ```
2. **Database Size Query:**
   ```bash
   ssh -o StrictHostKeyChecking=no {ssh_user}@{ip} \
     "docker exec -e PGPASSWORD={password} {container_name} \
      psql -U {db_user} -d {db_name} -t -c \
      \"SELECT pg_size_pretty(pg_database_size('{db_name}'));\""
   ```

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI Backend
    participant DB as SQLite DB
    participant VM as Remote VM (Docker)
    autonumber

    Client->>API: GET /databases/{id}/metrics
    API->>DB: Fetch DB credentials and VM IP
    DB-->>API: DBInstance credentials & VM IP
    API->>VM: SSH command: 'docker exec psql' (Get Connection Count)
    VM-->>API: stdout: Connection count (e.g. "4")
    API->>VM: SSH command: 'docker exec psql' (Get Database Size)
    VM-->>API: stdout: Pretty size (e.g. "23 MB")
    API-->>Client: HTTP 200 OK {active_connections, db_size, timestamp}
```

### C. Database Deprovisioning (`DELETE /databases/{id}`)

Deprovisioning completely tears down the database container but keeps data files on the VM disk (due to the persistent volume mount):
1. **Verification:** The API checks that the target database container is labeled with the matching `cloud_db_user=<username>` to prevent unauthorized deletion.
2. **Teardown:** Docker issues a force removal command (`container.remove(force=True)`), stopping and deleting the container.
3. **Database Registry Update:** Deletes the metadata record from SQLite.

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI Backend
    participant DB as SQLite DB
    participant VM as Remote VM (Docker)
    autonumber

    Client->>API: DELETE /databases/{id}
    API->>DB: Fetch DBInstance record
    DB-->>API: DBInstance info (container_id)
    API->>VM: Find container & verify owner label == username
    API->>VM: Docker Remove Container (force=True)
    VM-->>API: OK
    API->>DB: Delete DBInstance record
    DB-->>API: Success (Commit)
    API-->>Client: HTTP 204 No Content
```

---

## 3. Database Schema

The SQLite database stores metadata for all provisioned instances inside the `db_instances` table defined in [api/database_service/models.py](file:///Users/angiebras/Library/CloudStorage/OneDrive-Pessoal/Ambiente%20de%20Trabalho/Mestrado/2-SEMESTRE/CLOUD/CloudInfra/CloudInfrastructure/api/database_service/models.py):

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Index | Unique identifier |
| `user_id` | `Integer` | ForeignKey(`users.id`) | Owner of the database instance |
| `container_id` | `String` | Unique, Not Null | Full Docker container ID |
| `instance_name`| `String` | Not Null | User-visible identifier (e.g., `prod-db`) |
| `db_name` | `String` | Not Null | Name of the default database created (`POSTGRES_DB`) |
| `db_user` | `String` | Not Null | Username of the database administrator (`POSTGRES_USER`) |
| `db_password` | `String` | Not Null | Plaintext database password |
| `host_port` | `Integer` | Not Null | The randomly assigned VM port mapped to port 5432 |
| `role` | `String` | Default: `"primary"` | DB replication role: `"primary"`, `"replica"`, or `"load_balancer"` |
| `parent_id` | `Integer` | ForeignKey(`db_instances.id`) | Identifies primary node for replication setups |
| `cluster_name` | `String` | Nullable | Grouping name for clustered replication systems |
| `read_host_port`| `Integer`| Nullable | Mapped host port for read-only HAProxy endpoints |
| `created_at` | `DateTime`| Server Default: `now()` | Local provisioning timestamp |

---

## 4. API Endpoints Reference

All DBaaS routes are mounted under the `/databases` prefix in [api/database_service/router.py](file:///Users/angiebras/Library/CloudStorage/OneDrive-Pessoal/Ambiente%20de%20Trabalho/Mestrado/2-SEMESTRE/CLOUD/CloudInfra/CloudInfrastructure/api/database_service/router.py).

| Method | Endpoint | Auth | Request Body | Response Schema | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **POST** | `/databases` | JWT | `DBProvisionRequest` | `DBInstanceResponse` | Provision a new PostgreSQL container. Automatically allocates a host VM if the user has none running |
| **GET** | `/databases` | JWT | *None* | `list[DBInstanceResponse]` | List all databases belonging to the user (polls live container statuses in parallel) |
| **GET** | `/databases/{id}` | JWT | *None* | `DBInstanceResponse` | Get credentials, connection DSN, and live status of a single database |
| **DELETE**| `/databases/{id}` | JWT | *None* | *None (204)* | Deprovision (stop & remove container, delete SQLite record) |
| **POST** | `/databases/{id}/restart`| JWT | *None* | *None (204)* | Restart the PostgreSQL container (re-fetches port bindings if they change) |
| **GET** | `/databases/{id}/metrics`| JWT | *None* | `DBMetricsResponse` | Execute remote checks inside the container to fetch active connections and database size |

---

## 5. How to Connect to Your Database

Because database containers run on VMs inside a private network, your local laptop cannot access the database port directly. Use one of the following methods:

### Method A: Direct Command-line (via VM Terminal)
1. Go to the **Virtual Machines** page in the web dashboard.
2. Click the **Terminal** icon next to the active VM hosting your DB.
3. Run this command to connect using the container's internal `psql` client:
   ```bash
   docker exec -it db-username-instancename psql -U username -d dbname
   ```

### Method B: From your Local Laptop (via SSH Tunnel)
To connect using GUI clients (like **DBeaver**, **pgAdmin**, or a local script):
1. Establish an SSH tunnel through the gateway:
   ```bash
   # Syntax: ssh -L [local-port]:[VM-IP]:[Host-Port] gateway-user@gateway-ip
   ssh -L 5433:172.16.100.25:32768 angelo@ponchalaptop
   ```
2. Connect your local application using these parameters:
   * **Host:** `localhost`
   * **Port:** `5433`
   * **Username:** `username`
   * **Password:** *Plaintext password returned in credentials*
   * **Database:** `dbname`
   * **Connection DSN:** `postgresql://username:password@localhost:5433/dbname`

---

## 6. Query Splitting & Routing in Application Code

Because HAProxy is configured as a **Layer 4 TCP proxy** (mode `tcp`), it cannot read, parse, or evaluate SQL commands. Consequently, the load balancer cannot automatically separate read queries (`SELECT`) from write queries (`INSERT`/`UPDATE`). 

The application developer must explicitly handle this routing logic in their codebase by configuring two distinct database connection sessions:

1. **Write Session (Primary Node):** Connects to the host IP and the `host_port` (linked to container port `5432`).
2. **Read Session (Balanced Node Pool):** Connects to the host IP and the `read_host_port` (linked to container port `5433`).

### Implementation Example (Python + SQLAlchemy)

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configured using the primary connection port (e.g., 32768)
write_engine = create_engine("postgresql://user:password@localhost:32768/dbname")
WriteSession = sessionmaker(bind=write_engine)

# Configured using the HAProxy load-balanced read port (e.g., 32769)
read_engine = create_engine("postgresql://user:password@localhost:32769/dbname")
ReadSession = sessionmaker(bind=read_engine)

# --- Usage in Application ---

def create_item(name: str, description: str):
    # Route data creation to the Write Engine (goes directly to the Primary Node)
    with WriteSession() as session:
        session.execute(
            "INSERT INTO items (name, description) VALUES (:name, :description)",
            {"name": name, "description": description}
        )
        session.commit()

def fetch_items():
    # Route query requests to the Read Engine (balances traffic round-robin between Primary & Replicas)
    with ReadSession() as session:
        result = session.execute("SELECT id, name, description FROM items")
        return result.fetchall()
```

> [!CAUTION]
> If a query modifying state (e.g., `INSERT` or `UPDATE`) is sent to the read port (`5433`), the replica VM handling the connection will reject it, throwing: `ERROR: cannot execute INSERT in a read-only transaction`.

---

## 7. Clustered PostgreSQL with Streaming Replication

Beyond standalone databases, the platform supports provisioning a multi-node PostgreSQL cluster with high availability and read-scaling.

### A. Cluster Replication Provisioning Flow
When a user requests a cluster via the API:
1. **Primary Node:** Instantiates a database container acting as the primary read/write node.
2. **Replication Permissions:** Adds a replication user (`replicator`) and appends authorization rules to `pg_hba.conf` on the primary, followed by a configuration reload.
3. **Standby Replica Cloning:** Launches a temporary `pg_basebackup` container on each replica host to clone the primary's data directory over the network. This process automatically generates `standby.signal` and `primary_conninfo` files in the database directory.
4. **Hot-Standby Startup:** Starts the replica PostgreSQL container, mounting the cloned directory. Detecting `standby.signal`, it starts in read-only streaming standby mode.
5. **Load Balancer (HAProxy) deployment:** Deploys an HAProxy container on the primary VM configured as a Layer 4 TCP proxy to route database requests.

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI Backend
    participant Primary as Primary VM (Docker)
    participant Replica as Replica VM (Docker)
    autonumber

    API->>Primary: Create role 'replicator' & update pg_hba.conf
    API->>Primary: Reload Postgres Configuration
    API->>Replica: Run temporary pg_basebackup container
    Replica->>Primary: Pull physical data files over network
    Primary-->>Replica: Transfer completed
    Note over Replica: Creates standby.signal & primary_conninfo
    API->>Replica: Launch official replica container (Mount data folder)
    Replica->>Primary: Establish replication stream
    Primary-->>Replica: Continuous WAL Log Streaming
```

### B. Dual-Port Query Splitting (HAProxy Routing)
HAProxy is configured in Layer 4 TCP mode to route binary database connections based on two dedicated frontends:
* **Port 5432 (Write Frontend):** Directly forwards TCP traffic to the Primary node (Write-active).
* **Port 5433 (Read Frontend):** Distributes TCP traffic in a round-robin pool across the Primary and all Standby replicas.

```mermaid
graph TD
    Client[Application Client] -->|Writes: Port 5432| WritePort[HAProxy Write Port]
    Client -->|Reads: Port 5433| ReadPort[HAProxy Read Port]

    subgraph "HAProxy L4 TCP Proxy (Primary Host VM)"
        WritePort -->|Direct Forward| PrimaryBackend[Primary DB Node]
        ReadPort -->|Round-Robin Balance| ReadPool[Read Node Pool]
    end

    subgraph "PostgreSQL Cluster Nodes"
        PrimaryBackend -->|SQL writes| PrimaryDB[(Primary Postgres VM 1)]
        ReadPool -->|SQL SELECT| PrimaryDB
        ReadPool -->|SQL SELECT| Replica1[(Replica 1 Postgres VM 2)]
        ReadPool -->|SQL SELECT| Replica2[(Replica 2 Postgres VM 3)]
        
        PrimaryDB -->|WAL Log Sync| Replica1
        PrimaryDB -->|WAL Log Sync| Replica2
    end
```


