# Custom Elastic Cloud Infrastructure over OpenNebula: Architecture, Implementation, and Lifecycle Assessment Report

**Academic Report**  
*Course:* Cloud Infrastructure & Large-Scale Systems  
*Authors:* Mestrado em Segurança Informática 
*Date:* June 2026  
This md will be used as an reference to the actual latex report

---

## Abstract

This report details the design, implementation, and evaluation of a custom, highly elastic **Infrastructure-as-a-Service (IaaS)** and **Platform-as-a-Service (PaaS)** cloud manager built on top of **OpenNebula**. The platform exposes a RESTful API (developed in Python using FastAPI) and a React-based management dashboard. It implements multi-tenant user management, secure JWT session authorization, dynamic virtual machine provisioning with a pre-warmed standby pool, elastic block and S3-compatible object storage (MinIO), isolated container services, and automated PostgreSQL Database-on-Demand (DBaaS) clusters with Layer 4 TCP load balancing (HAProxy). We evaluate the platform's lifecycle metrics, demonstrating a reduction in VM provisioning latency from 90 seconds to under 1 second, a 3x throughput improvement via parallel client thread pooling, and significant hypervisor energy savings through an automated scale-to-zero inactivity policy.

---

## 1. Background on Chosen Software and Libraries

To implement a robust, decoupled cloud management framework, the following core software technologies and libraries were selected:

1.  **OpenNebula (v7.2.0):** An open-source cloud management platform used to orchestrate physical hypervisors, storage networks, and virtual machines. It exposes an XML-RPC interface (`oned`) that allows programmatic control over virtual resources.
2.  **FastAPI (Python):** A high-performance, asynchronous web framework used to construct the custom Cloud API backend. It provides automatic OpenAPI/Swagger documentation, fast execution speeds, and clean dependency-injection patterns.
3.  **pyone SDK:** The official Python bindings for OpenNebula's XML-RPC API. It translates Python method calls into XML-RPC payloads and parses the returned XML response structures into native Python objects.
4.  **Docker SDK for Python:** Used to remotely control container lifecycles on active virtual machines. By wrapping the Docker SDK over secure SSH client channels, the API backend administers container deployments on guest nodes dynamically.
5.  **MinIO:** A high-performance, S3-compatible object storage server. It is deployed as the block/file storage backend for multi-tenant data isolation.
6.  **HAProxy:** A high-performance Layer 4 (TCP) and Layer 7 (HTTP) load balancer. It is utilized in TCP mode to route database traffic in PostgreSQL clustering configurations.
7.  **Nginx:** A lightweight web server utilized as a reverse proxy load balancer to distribute HTTP requests across scaled container worker groups.
8.  **SQLAlchemy & SQLite:** SQLite acts as the local metadata store (`cloud.db`) to track user credentials, VM ownership mappings, custom disk records, and database cluster credentials, while SQLAlchemy serves as the Object-Relational Mapper (ORM).
9.  **Paramiko:** A pure-Python implementation of the SSHv2 protocol, used to establish SSH-forwarding tunnels and WebSocket terminal bridges to VMs located inside private virtual networks.

---

## 2. Materials and Methods

### 2.1 Machines Used and Their Characteristics

The implementation environment was structured across three physical and virtual layers:

1.  **OpenNebula Frontend & Hypervisor Host Server:**
    *   **OS:** Ubuntu Server 22.04 LTS
    *   **Virtualization Hypervisor:** KVM (Kernel-based Virtual Machine) / QEMU
    *   **CPU:** x86_64, 8 physical cores (Intel Xeon / Core i7 family)
    *   **RAM:** 32 GB DDR4
    *   **Storage:** 500 GB SSD Datastores
    *   **Network:** Private host-only network bridge (`172.16.100.*`) for VM-to-VM communication, mapped to physical VLANs.
2.  **Gateway Host Machine (`PonchaLaptop`):**
    *   An intermediate gateway machine exposing a public IP address.
    *   Facilitates secure SSH port forwarding tunnels to direct traffic from local development environments to OpenNebula's internal services (XML-RPC daemon on port `2633`, MinIO on ports `9002`/`9003`).
    *   Acts as the WebSocket terminal bridge target.
3.  **Guest Virtual Machines (Cloud Resource Nodes):**
    *   **Base Image Template:** Alpine Linux 3.20 (minimized footprint to reduce boot times and memory usage).
    *   **Resources:** 1 vCPU, 2048 MB RAM, 4 GB Disk size.
    *   **Networking:** Configured with `one-context` to automatically mount ISO contextualization data on boot to assign static IP addresses.

### 2.2 Software Used and Their Versions

| Component | Software | Version |
| :--- | :--- | :--- |
| **Cloud Orchestrator** | OpenNebula Frontend (`oned`) | `7.2.0` |
| **Backend Language** | Python | `3.12.3` |
| **Web Framework** | FastAPI | `0.111.0` |
| **ORM / Database** | SQLAlchemy / SQLite | `2.0.30` / `3.45` |
| **Container Engine** | Docker Engine (on Guest VMs) | `26.1.4` (Alpine package) |
| **Object Store** | MinIO Server | RELEASE.2024-05-10 |
| **TCP Proxy** | HAProxy | `2.8.5-alpine` |
| **HTTP Load Balancer** | Nginx | `1.25-alpine` |
| **Security Cryptography** | PyJWT / Passlib (Bcrypt) | `2.8.0` / `1.7.4` |

---

### 2.3 Detailed Guide of How the Cloud Was Developed

#### 2.3.1 Installation Steps

The cloud manager backend was developed by building a Python environment and routing connections through secure tunnels. The installation steps are as follows:

0.  **Remote OpenNebula & MiniOne Host Setup:**
    The remote hypervisor host must run a standard single-node deployment of **OpenNebula** using the official **MiniOne** tool.
    
    Log into the remote server as root (or a user with sudo privileges) and run:
    ```bash
    # Download the MiniOne bootstrap installer script
    wget https://raw.githubusercontent.com/OpenNebula/minione/master/minione
    
    # Execute MiniOne to deploy OpenNebula frontend + KVM node
    # Sets up OpenNebula version 7.2.0, sets core XML-RPC port to 2633, and creates the admin credentials
    sudo bash minione --version 7.2.0 --username oneadmin --password your_opennebula_password
    ```
    Once the installer completes:
    *   OpenNebula XML-RPC endpoint is active at `http://localhost:2633/RPC2`.
    *   Sunstone Web UI is exposed at `http://localhost:80` (or `8080`).
    *   An admin user `oneadmin` with the password `your_opennebula_password` is ready.

1.  **Establish the SSH Forwarding Tunnel:**
    From your local development machine, open an SSH tunnel to the gateway (or the OpenNebula host) to forward XML-RPC and MinIO ports locally:
    ```bash
    ssh -L 8080:localhost:80 -L 2633:localhost:2633 -L 9002:localhost:9002 -L 9003:localhost:9003 ubuntu@[gateway-ip]
    ```
2.  **Set Up Environment Variables:**
    Create a local `.env` file in the project root:
    ```env
    ONE_USER=oneadmin
    ONE_PASSWORD=your_opennebula_password
    MINIO_ENDPOINT=localhost:9002
    MINIO_ACCESS=minioadmin
    MINIO_SECRET=minioadmin123
    GATEWAY_IP=localhost
    GATEWAY_PORT=2222
    GATEWAY_USER=angelo
    GATEWAY_PASSWORD=your_gateway_password
    ```
3.  **Bootstrap python Virtual Environment & Dependencies:**
    Initialize a Python virtual environment and install dependencies listed in `requirements.txt`:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install pyone fastapi uvicorn "python-jose[cryptography]" "passlib[bcrypt]" sqlalchemy "pydantic[email]" "bcrypt==4.0.1" minio python-multipart docker paramiko
    ```
4.  **Boot Object Storage:**
    Run the provided bootstrap script to download the MinIO S3 binary and start the server:
    ```bash
    bash scripts/start_minio.sh
    ```
5.  **Launch the Cloud Manager API Server:**
    Run the FastAPI server using the Uvicorn ASGI server:
    ```bash
    python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
    ```

---

#### 2.3.2 Selected Tests

The following integration and lifecycle validation tests were implemented to verify cloud operations:

1.  **OpenNebula Basic Connectivity (`scripts/test_connection.py`):**
    Queries the OpenNebula RPC endpoint. Verifies that credentials are authenticated, lists the available VM templates, active VMs, datastores, and hypervisor hosts.
2.  **User Authentication & Security (`api/auth/router.py`):**
    Tests the complete user CRUD cycle. When registering a user, the backend allocates a corresponding user in OpenNebula (`client.user.allocate`). On login, credentials are verified locally via Bcrypt hashes, generating a 24-hour JWT token. Profiles updates (emails, passwords, SSH keys) are mirrored to OpenNebula's template structures.
3.  **Elastic Compute & Autoscaler (`scripts/test_autoscaler.py`):**
    Verifies that the `AutoScaler` background thread checks cluster load every 30 seconds.
    *   **Scale-Up:** Simulates heavy CPU load on worker VMs. The scaler detects avg CPU > 70%, claims a pre-warmed VM (or provisions a new one), and hooks it into the cluster.
    *   **Scale-Down:** Simulates load drops (avg CPU < 20%). The scaler performs a container drain check over SSH, waits for the 2-minute cooldown window, and destroys the idle VM (`terminate-hard`).
    *   **Scale-to-Zero:** Verifies that inactive user VMs are powered off (`poweroff-hard`) after 2 hours of API inactivity and automatically resumed when the user makes a profile query.
4.  **Dynamic Disk Allocation & Mounting (`scripts/test_disks.py` & `scripts/test_disk_actions.py`):**
    *   Allocates a raw empty datablock in OpenNebula.
    *   Performs a hot-plug attach to an active VM.
    *   Connects to the VM terminal, executes partition formatting (`mkfs.ext4 /dev/vdb`), mounts it to `/mnt/`, and configures boot mounts in `/etc/fstab`.
    *   Performs hot-unplug detachment.
5.  **Multi-Tenant S3 Object Storage (`api/storage/minio_client.py`):**
    Tests file uploads, directory listings, downloads, and deletions. Verifies that buckets named `user-{username}` are created dynamically and block cross-tenant file access.
6.  **Layer 4 Clustered Database Provisioning (`scripts/test_haproxy.py`):**
    Spins up a Primary Postgres container on VM 1 and Read-replicas on VM 2/3.
    *   Executes physical synchronization from the Primary using a temporary `pg_basebackup` container.
    *   Sets up streaming replication using Write-Ahead Logging (WAL) logs.
    *   Deploys an HAProxy container on the Primary host VM with dual-port routing: Write traffic is directed to port `5432` (Primary only), and Read traffic is balanced round-robin across port `5433` (Primary + all active Replicas).
    *   Executes write transactions through port 5432, verifies replication on standby nodes, and queries port 5433 to test round-robin load distribution.

---

#### 2.3.3 Evaluation/Assessment Metrics

##### Metric A: VM Provisioning Latency (Standby Pool Efficiency)
The platform evaluates the time elapsed from a provisioning request to a fully reachable VM state.
*   **Cold Boot Latency:** Provisioning a VM from scratch (cloning disk, allocating resources, booting OS, waiting for `one-context` network configurations) takes an average of **85 to 110 seconds**.
*   **Standby Pool Latency:** By keeping a standby VM (`prewarmed-vm-`) pre-booted under `oneadmin` ownership, scaling up simply requires renaming and changing VM ownership (`client.vm.chown`). This drops provisioning latency to **less than 1 second** ($0.8\text{s}$).

##### Metric B: API Throughput Speed (Parallel vs. Sequential Probing)
Because the API backend must connect to remote VM Docker Engines over SSH tunnels to check container states, sequential loops accumulate network round-trip delays:
*   **Sequential Latency:** Querying 3 VMs one by one takes around **3.42 seconds**.
*   **Parallel Latency:** Utilizing Python's `ThreadPoolExecutor` to run threads concurrently reduces the wait time to **1.15 seconds** ($\approx 3\text{x}$ performance speedup), maintaining a responsive REST API.

##### Metric C: Energy and Carbon Savings Proxy
The platform tracks cumulative active VM hours and computes energy saved against a static host baseline (which assumes the maximum capacity of `MAX_VMS = 5` is kept running continuously):
*   $$\text{Hours Saved} = \text{Baseline Capacity Hours} - \sum (\text{Active VM runtimes})$$
*   $$\text{Energy Saved (kWh)} = \frac{\text{Hours Saved} \times 50\text{W (Average VM power draw)}}{1000}$$
*   $$\text{CO2 Saved (kg)} = \text{Energy Saved (kWh)} \times 0.4\text{kg/kWh (grid emission factor)}$$

---

## 3. Discussion and Conclusions

### Achievements and Decoupling
The project successfully implemented a stateless, lightweight PaaS and IaaS cloud manager on top of OpenNebula. By storing local metadata in SQLite and querying live states dynamically from Docker and OpenNebula endpoints, we decoupled database states from physical reality. The integration of a pre-warmed standby pool solves a major KVM virtualization bottleneck: high provisioning latency.

### Design Trade-Offs: Container vs. Database Scaling
A major architectural decision was restricting database replica scaling to manual user requests while enabling native autoscaling for web containers:
*   **Web Containers:** Scaling web containers takes **3–5 seconds** and has zero impact on other active nodes.
*   **Database Replicas:** Scaling read-replicas requires streaming the entire database binary directory from the Primary database node using `pg_basebackup`. This operation is $O(\text{database size})$. In a high-traffic situation, an automated database scale-up would flood the network and disk I/O of the primary node, exacerbating the load spike and potentially causing system failure. Hence, database scaling remains a deliberate, manual developer action.

### Future Work
Future iterations of this platform will investigate:
1.  **Continuous WAL Archiving to MinIO:** Offloading database snapshots to S3 storage, enabling replicas to restore from backups rather than querying the primary database directly. This would make database autoscaling safe.
2.  **Shared Distributed Storage Layers:** Implementing shared cluster volumes (like Ceph or GlusterFS) so that adding read-replicas is a pure compute operations, eliminating data transfer latency.
3.  **Observability Daemons:** Deploying a read-only monitoring daemon (`db_monitor.py`) to track query latencies and replication lag, alerting operators without triggering dangerous scaling loops.
