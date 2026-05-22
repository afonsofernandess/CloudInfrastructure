# Database Service (DBaaS) — Management & Testing Guide

This guide describes the architecture, configuration, operation, and testing procedures for the **Phase 6 Database-on-Demand (DBaaS)** service. This service allows cloud users to dynamically provision, manage, and deprovision PostgreSQL instances across their active OpenNebula virtual machines.

---

## 1. Architecture Overview

Rather than running databases locally or on a static server, the database service dynamically routes commands through SSH ProxyJump into Docker engines running on active OpenNebula VMs.

```mermaid
graph TD
    Client[React Dashboard / API Client] -->|HTTP Request| API[FastAPI Server]
    API -->|1. Lookup Active VMs| SQLite[(SQLite DB)]
    API -->|2. Connect via SSH Tunnel| DockerEngine[Docker Daemon on VM via SSH]
    DockerEngine -->|3. Run Database Container| PG[Postgres Container]
    PG -->|4. Bind Port| HostPort[Dynamic Host Port e.g. 32768]
```

### Key Architectural Concepts:
* **Dynamic Target Selection:** Users can choose which of their active VMs will host the database container.
* **Isolation:** PostgreSQL instances are ran as lightweight `postgres:16-alpine` Docker containers. Isolation is enforced using labels (`cloud_db_user=<username>`), ensuring users only see and manage their own databases.
* **Auto-Port Mapping:** The host port is automatically and randomly assigned by the Docker engine on the host VM (e.g. `32768:5432`). This prevents port conflicts and allows launching unlimited database instances on the same VM.

---

## 2. API Endpoints Reference

The DBaaS service exposes the following endpoints under the `/databases` prefix:

| Method | Endpoint | Request Body | Description |
| :--- | :--- | :--- | :--- |
| **POST** | `/databases` | `{ "name": "...", "db_name": "...", "vm_id": ... }` | Provision a new PostgreSQL instance on the target VM |
| **GET** | `/databases` | *None* | List all database instances belonging to the current user |
| **GET** | `/databases/{id}` | *None* | Retrieve live status and credentials (DSN) for a specific database |
| **DELETE**| `/databases/{id}` | *None* | Deprovision (stop & remove container, delete DB record) |

---

## 3. How to Connect to Your Database

Because the database containers run on VMs inside a private cloud network (`172.16.100.*`), your local machine cannot access the database port directly. Use one of the following methods to test and access your database:

### Method A: Direct Command-line (via VM Terminal)
If you want to quickly run SQL commands or inspect tables:
1. Open the dashboard and go to the **Virtual Machines** page.
2. Click the **Terminal** icon next to your active VM (e.g. `ola`).
3. Run the following command inside the terminal to connect via the container:
   ```bash
   docker exec -it db-angie-rurtrtyer psql -U angie -d hello
   ```
   *(Replace `db-angie-rurtrtyer` with your container name, `angie` with your username, and `hello` with your database name).*

### Method B: From your Local Laptop (via SSH Tunnel)
To connect using tools on your laptop (like **DBeaver**, **pgAdmin**, or a local python application):
1. In a local terminal, create an SSH tunnel through the gateway:
   ```bash
   # Syntax: ssh -L [local-port]:[VM-IP]:[Host-Port] angelo@ponchalaptop
   ssh -L 5433:172.16.100.2:32782 angelo@ponchalaptop
   ```
   *(Keep this terminal window running to maintain the port forwarding tunnel).*
2. Connect your local database GUI or application to the forwarded local port:
   * **Host:** `localhost`
   * **Port:** `5433`
   * **Username:** `angie`
   * **Password:** *(Use the password returned in the credentials drawer)*
   * **Database:** `hello`
   * **Connection DSN:** `postgresql://angie:password@localhost:5433/hello`

---

## 4. Testing & Lifecycle Verification

### Automated Verification Script
A Python script is provided in the codebase to automate the testing of the entire lifecycle (provisioning, status verification, DSN retrieval, connection test, and cleanup).

To execute the test:
1. Ensure the FastAPI backend server is running:
   ```bash
   .venv/bin/uvicorn api.main:app --port 8000 --reload
   ```
2. Run the test script in a separate terminal:
   ```bash
   .venv/bin/python scripts/test_databases.py
   ```

### Manual Testing (SQL Commands)
Once connected to the database via `psql` (Method A or B), you can run these SQL commands to test the table creation and querying:

```sql
-- 1. Create a table
CREATE TABLE test_table (
    id SERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. List tables to verify
\dt

-- 3. Insert test data
INSERT INTO test_table (title, description) 
VALUES ('First Entry', 'Testing database reads and writes.');

-- 4. Query the data
SELECT * FROM test_table;

-- 5. Disconnect
\q
```
