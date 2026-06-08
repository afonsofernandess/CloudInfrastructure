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

To validate the reliability, performance, and functionality of the custom cloud management system, we implemented a comprehensive automated test suite inside the `scripts/` directory:

1.  **OpenNebula Connection Integrity (`scripts/test_connection.py`):**
    This test verifies connection and authentication with the OpenNebula XML-RPC endpoint (`oned`). It queries the cloud manager daemon to fetch active hypervisor hosts, system datastores, and VM template configurations to ensure credentials in the `.env` file are fully authorized.
2.  **User Authentication and Authorization Lifecycle (`api/auth/router.py`):**
    Validates user creation, secure login, and JWT access token issuance. Registration logic is verified to ensure user allocations are mirrored in OpenNebula (`client.user.allocate`). Profile update operations (changing email, password, or SSH public keys) are tested to ensure they are synchronized with the corresponding OpenNebula user templates.
3.  **Elastic Compute & Autoscaling Test (`scripts/test_autoscaler.py`):**
    Validates load-reactive scaling:
    *   **Scale-Up:** Deploys an Nginx web worker container group with high compression configured (`gzip_comp_level 9`) and starts a multi-threaded HTTP flood tool to hammer the endpoint. The autoscaler background thread monitors worker CPU load; once average CPU utilization exceeds $70\%$, the autoscaler claims a pre-warmed VM from the standby pool, configures it, and hooks it into the cluster to balance load.
    *   **Scale-Down:** Upon terminating the HTTP flood, average CPU utilization drops below $20\%$. The autoscaler waits for the 120-second cooldown period (to prevent scaling oscillations/flapping) before running a container drain sequence and hard-terminating the idle VM.
4.  **Scale-to-Zero & Wake-on-API Test (`scripts/test_scale_to_zero.py`):**
    Evaluates the energy-saving inactivity policy. The test temporarily overrides the inactivity timeout to 5 seconds. By modifying the user's `last_active_at` timestamp to simulate inactivity, it verifies that the autoscaler suspends or powers off the user's VM. It then simulates user activity (such as an API request) and verifies that the VM automatically resumes state (wake-on-API) before serving the request.
5.  **Block Storage Hot-Plugging Test (`scripts/test_disks.py` & `scripts/test_disk_actions.py`):**
    Validates block storage attachment:
    *   Creates a raw 1GB disk image in the OpenNebula datastore.
    *   Initiates a live hot-plug attach to an active tenant VM.
    *   Establishes an SSH connection to the guest VM to format the disk block (`mkfs.ext4 /dev/vdb`), creates a local mount directory, mounts the volume, and writes a test file.
    *   Verifies that the disk can be hot-unplugged and detached successfully without halting the VM.
6.  **Multi-Tenant S3 Object Storage Test (`api/storage/minio_client.py`):**
    Tests file uploads, downloads, listings, and deletions against the S3-compatible MinIO backend. It ensures that tenant-isolated buckets named `user-{username}` are dynamically generated and that cross-tenant access is strictly blocked.
7.  **Clustered Database & HAProxy L4 Balancing (`scripts/test_haproxy.py` & `scripts/test_db_cluster.py`):**
    Verifies the deployment of a clustered database with streaming replication and dual-port query routing:
    *   **Test 1 (Write Constraint):** Ensures write queries succeed when directed to HAProxy's write-port (5432) pointing to the primary database, and fail with a "read-only transaction" error when issued directly against replicas.
    *   **Test 2 (Replication Propagation):** Inserts a test row via the primary database and verifies that Write-Ahead Logging (WAL) replicates the record to all standby nodes immediately.
    *   **Test 3 (Read Load Balancing):** Executes concurrent `SELECT` queries through HAProxy's read-port (5433) and verifies that queries are distributed across the database nodes in a round-robin fashion by capturing the responding container IPs.

---

#### 2.3.3 Evaluation/Assessment Metrics

We evaluated the performance, resource efficiency, and carbon footprint of our implementation using three core metrics:

##### Metric A: VM Provisioning Latency (Cold Boot vs. Standby Pool)
This metric measures the time elapsed from the initial API provisioning request until the VM is booted, network-configured, and fully reachable via SSH.
*   **Cold Boot Latency:** Provisioning a VM from scratch (cloning the disk, allocating the host, booting the guest kernel, and running the `one-context` configuration) takes an average of **85 to 110 seconds**.
*   **Pre-Warmed Standby Pool Latency:** By keeping an idle VM pre-booted under `oneadmin` ownership, scaling up simply renames the VM and changes its owner (`client.vm.chown`) to the requesting tenant. This reduces provisioning latency to **less than 1 second** ($0.8\text{s}$).

| Provisioning Method | Average Latency (seconds) | Provisioning Behavior |
| :--- | :---: | :--- |
| **Cold Boot (Scratch)** | 97.5s | Disk clone + kernel boot + context initialization |
| **Pre-Warmed Standby** | 0.8s | Owner transfer (`chown`) + dynamic renaming |

##### Metric B: API Probing Latency (Sequential vs. Parallel Monitoring)
To collect CPU and memory load metrics from tenant container nodes, the API server must communicate with the Docker daemon running inside each active VM over SSH.
*   **Sequential Monitoring:** Iterating through active VMs sequentially accumulates network round-trip delays and SSH handshake overhead. For 3 VMs, this takes an average of **3.42 seconds**.
*   **Parallel Monitoring:** Utilizing Python's `ThreadPoolExecutor` to probe the active VMs concurrently reduces the monitoring loop duration to **1.15 seconds** (a $\approx 3\text{x}$ performance speedup), maintaining backend responsiveness.

##### Metric C: Energy and Carbon Savings Proxy
To measure the ecological impact of the scale-to-zero policy, we estimate the saved energy and carbon footprint compared to a baseline where all resources are kept active continuously:
*   **Active VM Run Hours:** Sum of runtime for all VMs belonging to active users.
*   **Baseline Capacity Hours:** Assumes the maximum capacity of VMs ($N_{\text{max}} = 5$) runs 24/7.
*   **Energy Savings Formula:**
    $$\text{Hours Saved} = (N_{\text{max}} \times \text{Elapsed Hours}) - \sum (\text{Active VM runtimes})$$
    $$\text{Energy Saved (kWh)} = \frac{\text{Hours Saved} \times P_{\text{avg}}}{1000}$$
    $$\text{CO}_2\text{ Saved (kg)} = \text{Energy Saved (kWh)} \times EF$$
    where $P_{\text{avg}} = 50\text{W}$ (estimated average physical host power allocation per active VM) and $EF = 0.4\text{ kg/kWh}$ (average electricity grid carbon emission factor). Under typical student workload patterns, scaling idle VMs to zero yields significant energy reductions.

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
