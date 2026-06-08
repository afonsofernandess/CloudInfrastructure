# Cloud Infrastructure Architecture & Flowcharts

This document provides a comprehensive architectural breakdown of the **My Own Cloud for Large Scale Data Science** platform, a custom Infrastructure-as-a-Service (IaaS) and Platform-as-a-Service (PaaS) cloud manager built on top of **OpenNebula 7.2.0**.

---

## 1. High-Level System Architecture

The platform follows a decoupled, stateless design. Local state and user metadata are stored in a SQLite database (`cloud.db`), while physical and container resources are queried dynamically from the virtual machines and OpenNebula controller.

The architecture comprises the following key components:

1.  **Frontend Dashboard (React/Vite):** The user-facing management dashboard.
2.  **API Gateway (FastAPI):** A high-performance REST API handling user requests, token validation, scheduling, and orchestrating downstream services.
3.  **Metadata Store (SQLite + SQLAlchemy):** Tracks tenant accounts, VM ownership mappings, custom disk definitions, and database cluster credentials.
4.  **OpenNebula Controller (`oned` XML-RPC daemon):** Manages hypervisor resources, KVM guest instances, virtual networks, and block storage datablocks.
5.  **SSH Gateway (`PonchaLaptop`):** Bridges local dev environments to the private VM networks and proxies WebSocket terminal sessions.
6.  **Object Storage (MinIO):** Provides tenant-isolated S3-compatible bucket storage.
7.  **Container & DBaaS Layer (Docker + PostgreSQL):** Exposes on-demand application container groups and replication-enabled PostgreSQL database clusters.

### High-Level System Architecture Diagram

```mermaid
graph TD
    subgraph "Client Layer"
        UI[React Dashboard / Vite]
    end

    subgraph "API & Gateway Layer"
        API[FastAPI Backend]
        DB[(Metadata SQLite: cloud.db)]
        MinIO[MinIO S3 Server]
    end

    subgraph "Network SSH Tunneling Gateway"
        SSH[SSH Gateway: PonchaLaptop]
    end

    subgraph "Physical Hypervisor / OpenNebula Node"
        ON[OpenNebula Daemon: oned]
        KVM[KVM / QEMU Hypervisor]
    end

    subgraph "Private VM Network (172.16.100.*)"
        VM1[VM 1: Alpine Node]
        VM2[VM 2: Alpine Node]
        
        subgraph "VM 1 Containers"
            Docker1[Docker Engine]
            Cont1[App Container]
            PostgresP[PostgreSQL Primary]
            HAP[HAProxy TCP Proxy]
        end

        subgraph "VM 2 Containers"
            Docker2[Docker Engine]
            Cont2[App Container]
            PostgresR[PostgreSQL Replica]
        end
    end

    UI -->|HTTP Requests / WebSockets| API
    API -->|Read/Write Metadata| DB
    API -->|S3 API / port 9002| MinIO
    API -->|XML-RPC / pyone / port 2633| SSH
    API -->|SSH / Docker SDK / Paramiko| SSH
    
    SSH -->|Port Forwarding| ON
    SSH -->|Direct TCP/IP Tunneling| VM1
    SSH -->|Direct TCP/IP Tunneling| VM2
    
    ON -->|Orchestrates| KVM
    KVM -->|Hosts| VM1
    KVM -->|Hosts| VM2
    
    Docker1 -->|Manages| Cont1
    Docker1 -->|Manages| PostgresP
    Docker1 -->|Manages| HAP
    Docker2 -->|Manages| Cont2
    Docker2 -->|Manages| PostgresR
    
    PostgresP -->|WAL Streaming Sync| PostgresR
    HAP -->|Port 5432: Writes| PostgresP
    HAP -->|Port 5433: Reads Pool| PostgresP
    HAP -->|Port 5433: Reads Pool| PostgresR
```

---

## 2. Core Subsystems

### 2.1 Authentication & User Management
*   **Decoupled Syncing:** User accounts are registered in the local SQLite database (storing bcrypt-hashed passwords). Simultaneously, the API invokes OpenNebula's RPC to allocate a mirroring user (`client.user.allocate`).
*   **JWT & Transparent Activity Tracker:** When a user invokes any protected endpoint, the `get_current_user` FastAPI dependency intercepts the request, verifies the JWT token, and updates `user.last_active_at` in the SQLite database. This timestamp is used by the autoscaler to determine VM idle states.

### 2.2 Elastic Compute (VM Management)
*   **Pre-Warmed Standby Pool:** Cold booting a KVM/QEMU VM takes 85–110 seconds. To bypass this, the `AutoScaler` maintains a standby pool containing pre-booted, context-configured VMs (`prewarmed-vm-`) owned by the system admin. When a scale-up is triggered, the system claims a standby VM, renames it, and changes its ownership via the RPC API (`chown`), provisioning a working VM in **under 1 second**.
*   **Power-Saving / Scale-to-Zero:** To save hypervisor energy, the `AutoScaler` monitors user activity. If `last_active_at` exceeds 2 hours, all VMs belonging to that user are automatically suspended (`poweroff-hard`). When the user logs back in or calls any API endpoint, the request updates their activity status, prompting the API to resume their suspended VMs transparently.
*   **SSH Terminal WebSocket Bridge:** Users can access a VM shell directly from the web dashboard. The API opens a WebSocket, initializes a Paramiko SSH client, connects to the SSH Gateway, creates a `direct-tcpip` channel to the VM's internal port `22`, invokes an interactive shell, and pipes standard input/output bi-directionally.

### 2.3 Storage (Block & S3 Object Storage)
*   **Block Storage:** Users can provision custom empty datablocks in OpenNebula. These datablocks can be hot-plug attached to running VMs. The backend connects to the VM via SSH, formats the new disk (`mkfs.ext4 /dev/vdb`), mounts it, and adds an entry to `/etc/fstab` for boot persistence.
*   **Object Storage:** A local MinIO service acts as an S3-compatible backend. Each tenant gets a separate bucket named `user-{username}` created automatically on their first upload, ensuring physical namespace isolation.

### 2.4 Container Orchestration & Scaling
*   **Stateless Label-Based Isolation:** Rather than tracking containers in SQLite, the API queries active Docker engines dynamically. Containers are tagged with metadata: `cloud_user=<username>` and `scale_group=<group_name>`. The API filters list and control operations using these labels, enforcing multi-tenant security.
*   **Placement Scheduler:** When a container scale-up is requested, the scheduler queries container densities across all active user VMs and deploys the container on the VM hosting the fewest containers.
*   **Dynamic Load Balancing (Nginx):** When a container group scales, the manager resolves all backend VM IPs and dynamic host ports, generates an Nginx configuration file (`nginx.conf`) with the upstream endpoints, SFTP-uploads it to the designated Load Balancer VM, and boots/reloads an Nginx proxy container.

### 2.5 Database-as-a-Service (DBaaS)
*   **Clustered Architecture:** PostgreSQL instances are provisioned inside Docker containers on separate VMs. The cluster consists of one Primary node (Read/Write) and one or more Read-only replicas.
*   **Synchronization (WAL Streaming):** Standby replicas are initialized by executing `pg_basebackup` inside a temporary container, cloning the Primary data directory over the network. Once initialized, the replica maintains a TCP connection to stream Write-Ahead Logs (WAL) in real-time.
*   **Layer 4 TCP Load Balancing (HAProxy):** An HAProxy container is deployed on the Primary VM. It listens on two ports:
    *   **Port 5432 (Write Frontend):** Forwards queries exclusively to the Primary.
    *   **Port 5433 (Read Frontend):** Balances queries round-robin across the Primary and all Standby replicas.
*   **Zero-Downtime Hot Reloads:** When a database replica scales, HAProxy's config is regenerated, uploaded, and hot-reloaded by sending a `SIGHUP` signal (`docker kill -s HUP <haproxy_container>`), ensuring active connections are not interrupted.

---

## 3. Detailed Architectural Flowcharts

### 3.1 User Request Auth & "Wake-on-API" VM Resume

This flowchart illustrates how standard API requests trigger the transparent wake-up of suspended user VMs.

```mermaid
sequenceDiagram
    autonumber
    actor User as React Web Client
    participant API as FastAPI Gateway
    participant DB as SQLite Metadata
    participant AS as AutoScaler Thread
    participant ON as OpenNebula (oned)

    User->>API: API Request (e.g. GET /compute/vms) with JWT Token
    activate API
    API->>API: Decode JWT & Validate User
    
    alt Token is valid
        API->>DB: Update user.last_active_at = NOW
        DB-->>API: Confirm Update
        API-->>User: Return VM List Response (FastAPI response completes)
    else Token is invalid/expired
        API-->>User: Return 401 Unauthorized
    end
    deactivate API

    Note over AS: AutoScaler checks user inactivity every 30s
    AS->>DB: Query users where last_active_at is fresh
    DB-->>AS: Returns active users
    
    loop For each active user
        AS->>ON: List all user VMs
        ON-->>AS: Returns VM statuses (finds SUSPENDED VMs)
        
        loop For each SUSPENDED VM marked "suspended_by_system"
            AS->>ON: Resume VM (client.vm.resume)
            ON-->>AS: VM booting (LCM_STATE -> RUNNING)
            AS->>DB: Set suspended_by_system = False
            DB-->>AS: Saved
            Note over AS: VM is transparently restored!
        end
    end
```

---

### 3.2 VM Provisioning: Standby Pool vs. Cold Boot

This flowchart shows the difference between provisioning a VM from scratch (Cold Boot) and claiming a pre-warmed standby VM.

```mermaid
graph TD
    Start[User Requests VM Provisioning] --> Auth[Authenticate Tenant Request]
    Auth --> CheckStandby{Is a pre-warmed VM available in the pool?}

    %% Pre-warmed Path
    CheckStandby -->|Yes: Sub-second Provisioning| Claim[1. Identify pre-warmed-vm-XXXX in ACTIVE state]
    Claim --> Rename[2. Rename VM to tenant-requested name]
    Rename --> Chown[3. Change owner in OpenNebula to user_id]
    Chown --> RecordDB[4. Save VMInstance in local SQLite database]
    RecordDB --> TriggerReplenish[5. Trigger background thread to replenish Standby Pool]
    TriggerReplenish --> ReturnPre[Return VM Info to User < 1s]

    %% Cold Boot Path
    CheckStandby -->|No: Standard Allocation| Allocate[1. Call client.vm.allocate in OpenNebula]
    Allocate --> CloneDisk[2. Clone Base Image Datablock]
    CloneDisk --> BootVM[3. Hypervisor Boots VM]
    BootVM --> Context[4. Mount Context ISO for networking]
    Context --> PollState[5. Poll LCM_STATE until RUNNING ~90s]
    PollState --> RecordDB
    RecordDB --> ReturnCold[Return VM Info to User ~90-110s]

    %% Replenishment Sub-process
    subgraph "Standby Pool Replenishment (Background)"
        TriggerReplenish -.-> CheckCount{Total VMs < MAX_VMS?}
        CheckCount -->|Yes| CreatePre[Create new prewarmed-vm under oneadmin]
        CreatePre -.-> BootPre[Pre-boots and waits in ACTIVE state for next request]
        CheckCount -->|No| Idle[Do nothing]
    end
```

---

### 3.3 Container Scaling & Dynamic Nginx Load Balancing

This flowchart illustrates the scheduling of new container replicas and the hot reloading of the upstream Nginx load balancer configuration.

```mermaid
sequenceDiagram
    autonumber
    actor Tenant as React UI Developer
    participant API as Scale Manager (FastAPI)
    participant Dock as Docker Engines (VM Nodes)
    participant SFTP as SFTP File Client
    participant LB as Load Balancer VM (Nginx)

    Tenant->>API: Scale Container Group (e.g. scale 'web-app' to 3 replicas)
    activate API
    
    API->>Dock: Query running container densities across all active user VMs
    Dock-->>API: Returns VM container counts
    
    loop For each new replica needed
        API->>API: Select VM hosting the MIN number of containers
        API->>Dock: Launch Container (e.g. nginx:alpine, bind random host port)
        Dock-->>API: Container launched on VM IP, mapped to dynamic host port (e.g. 32768)
    end
    
    API->>API: Gather all active container IPs and mapped host ports for scale group
    API->>API: Generate dynamic 'nginx.conf' with upstream endpoints
    
    API->>SFTP: Upload nginx.conf to /var/lib/nginx-lb-webapp/nginx.conf on LB host VM
    SFTP-->>API: File uploaded successfully
    
    alt LB Container already exists
        API->>LB: Reload configuration (docker kill -s HUP nginx-lb-webapp)
    else LB Container does not exist
        API->>LB: Start new nginx:alpine container (Mount nginx.conf, bind public port)
        LB-->>API: Returns LB public host port (e.g. 32800)
    end
    
    API-->>Tenant: Returns Load Balancer URL: http://[LB_VM_IP]:[LB_PORT]
    deactivate API
```

---

### 3.4 Database Cluster Architecture & HAProxy Routing

This diagram shows how database transactions are isolated and routed via HAProxy, as well as how Standby replicas synchronize with the Primary database.

```mermaid
graph TD
    Client[Application Client Engine] -->|SQL Write Operations| WritePort[Port 5432: Write Port]
    Client -->|SQL Read-Only Operations| ReadPort[Port 5433: Read Port]

    subgraph "HAProxy Container (VM 1 - Primary Host)"
        direction TB
        WritePort -->|Mode TCP - No Balancer| PrimaryBackend[Backend: Primary Only]
        ReadPort -->|Mode TCP - Round-Robin| PoolBackend[Backend Pool: Primary & Standbys]
    end

    subgraph "PostgreSQL Database Cluster"
        direction LR
        PrimaryDB[PostgreSQL Primary VM 1]
        Replica1[PostgreSQL Replica VM 2]
        Replica2[PostgreSQL Replica VM 3]
    end

    PrimaryBackend -->|Direct SQL Writes| PrimaryDB
    
    PoolBackend -->|Round-Robin Read 1| PrimaryDB
    PoolBackend -->|Round-Robin Read 2| Replica1
    PoolBackend -->|Round-Robin Read 3| Replica2

    %% WAL Replication
    PrimaryDB -->|WAL Log Sync Connection| Replica1
    PrimaryDB -->|WAL Log Sync Connection| Replica2

    %% Health Checks
    HAProxyMonitor[HAProxy tcp-check probes] -.->|Port 5432| PrimaryDB
    HAProxyMonitor -.->|Port 5432| Replica1
    HAProxyMonitor -.->|Port 5432| Replica2

    style PrimaryDB fill:#1B4F72,stroke:#3498DB,stroke-width:2px,color:#fff
    style Replica1 fill:#1E8449,stroke:#2ECC71,stroke-width:2px,color:#fff
    style Replica2 fill:#1E8449,stroke:#2ECC71,stroke-width:2px,color:#fff
```

---

### 3.5 Database Replication Setup & Synchronization Flow

This sequence diagram depicts the initialization of a PostgreSQL Read Replica using a temporary `pg_basebackup` container.

```mermaid
sequenceDiagram
    autonumber
    participant API as DBaaS API (FastAPI)
    participant Primary as Primary DB VM
    participant Replica as Target Replica VM

    API->>Primary: Execute SQL: Create role 'replicator' (REPLICATION login)
    API->>Primary: Append rule to pg_hba.conf (allow replicator IP)
    API->>Primary: Reload Postgres (pg_ctl reload or SIGHUP)
    
    API->>Replica: Launch temporary pg_basebackup container
    activate Replica
    Replica->>Primary: Request backup stream (pg_basebackup -h PrimaryIP -U replicator)
    Primary-->>Replica: Stream physical binary files of database
    Note over Replica: Creates standby.signal & primary_conninfo configurations
    Replica-->>API: Backup stream finished, temp container exited
    deactivate Replica
    
    API->>Replica: Launch official PostgreSQL container (Mount data folder)
    activate Replica
    Note over Replica: Detects standby.signal -> Starts in standby read-only mode
    Replica->>Primary: Open WAL streaming connection
    Primary-->>Replica: Continuous replication logs streaming
    deactivate Replica
    
    Note over API,Replica: DB Replica is now fully synchronized and joins the HAProxy pool
```
