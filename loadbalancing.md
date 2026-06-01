# Container Scaling & Load Balancing Architecture

This document provides a detailed breakdown of how the container scaling and dynamic HTTP load balancer features are implemented.

---

## 1. Core Concepts & Orchestration

The platform implements a stateless container orchestration layer over multiple OpenNebula Virtual Machines. Rather than tracking individual container lifecycles in an SQL database, the status is queried dynamically from Docker engines running on the VMs using Docker labels.

### Worker Containers
**Workers** are the active application containers running your code/image (e.g. `nginx:alpine`) that handle actual client workloads.

* **Identification & Isolation:** Workers are labeled with metadata for stateless tracking:
  * `cloud_user=<username>`: Restricts visibility/control to the owner.
  * `scale_group=<group_name>`: Groups multiple workers under a service name (e.g., `web-app`).
  * `role=worker`: Identifies it as a worker node instead of a proxy load balancer.
* **Auto-Placement:** When scaling up workers, the system invokes `ensure_user_has_running_vm()`, which automatically provisions or selects the active VM hosting the *fewest* total containers. This balances the workload across the VM cluster.
* **Auto-Port Mapping:** To avoid port conflicts on VM hosts (especially when multiple workers of the same service run on a single VM), the container port is mapped as:
  ```python
  ports={container_port: None}
  ```
  Docker dynamically binds it to a random free host port (e.g., `32768`). The load balancer resolves these ports dynamically and maps traffic accordingly.

---

## 2. Load Balancer Configuration (Nginx)

The load balancer directs external traffic round-robin to all worker instances.

### Nginx reverse proxy
1. **IP/Port Mapping Resolution:** The scale manager scans all active VMs, retrieves the host IP, and reads the random mapped host port of each worker container.
2. **Upstream Config Generation:** It dynamically writes a standard Nginx configuration (`nginx.conf`):
   ```nginx
   events { worker_connections 1024; }
   http {
       upstream backend_servers {
           server 172.16.100.2:32768;
           server 172.16.100.3:32815;
       }

       server {
           listen 80;
           location / {
               proxy_pass http://backend_servers;
               proxy_set_header Host $host;
               proxy_set_header X-Real-IP $remote_addr;
           }
       }
   }
   ```
3. **Configuration SFTP Upload:** The file is written to the VM hosting the load balancer at `/var/lib/nginx-lb-<group_name>/nginx.conf` via a tunneled SFTP client through the gateway.
4. **Deploying the Load Balancer Container:**
   * Stops/removes any existing load balancer container.
   * Runs an `nginx:alpine` container.
   * Mounts the configuration folder read-only.
   * Maps container port `80` to a random free host port.
   * Exposes the single load balancer address (e.g. `http://<VM_IP>:<LB_PORT>`) to the user.

---

## 3. Worker Scaling Lifecycle

* **Scale Up:** Spins up new workers, selects VM placements, handles image downloads, boots containers on dynamic ports, and regenerates the Nginx config.
* **Scale Down:** Stops and deletes excess containers starting from the newest instance, updates the Nginx upstream servers list, and reloads the proxy.
* **Scale to Zero (Cleanup):** If replicas target is set to `0`, all worker containers and the Nginx load balancer proxy are terminated.

---

## 4. Database Clustering & Replication (PostgreSQL + HAProxy)

Database clustering distributes database queries across multiple nodes while preserving data consistency:
* **Primary Instance:** Accepts both Read and Write SQL queries.
* **Replica Instances:** Accept Read-only queries (`SELECT`). They stream updates from the Primary in real-time.
* **TCP Load Balancer (HAProxy):** Exposes two ports to route queries automatically to the appropriate nodes.

### Replicas Synchronization via `pg_basebackup`
To spin up a read-replica container on a different VM, the system performs a network-based physical backup:
1. **Primary Credentials:** It connects to the Primary container and executes SQL commands to create a replication user (`replicator`) and registers replication permissions in `pg_hba.conf`, followed by a configuration reload.
2. **Dynamic Backup Container:** The system triggers a one-off backup container on the target Replica VM using a remote SSH command. This container runs `pg_basebackup` and streams all data files from the Primary IP/Port over the network directly into a local folder on the Replica VM (e.g. `/var/lib/postgresql/data-replica-i`).
3. **Replication Config generation:** The `-R` option in `pg_basebackup` creates `standby.signal` and configures the `primary_conninfo` connection string.
4. **Booting Standby:** The replica PostgreSQL container is launched, mounting the populated data directory. Since the backup created `standby.signal`, PostgreSQL automatically boots in read-only streaming replica mode.

### Real-Time Data Synchronization (WAL Streaming)
Once a replica is booted, it stays updated dynamically:
* **Write-Ahead Logging (WAL):** Every data-modifying operation on the Primary (`INSERT`, `UPDATE`, `DELETE`, table/schema changes) is written to a sequential log file known as the Write-Ahead Log (WAL).
* **Streaming Protocol:** Standby replicas maintain a persistent TCP connection to the Primary database using the `replicator` account.
* **Continuous Updates:** As WAL entries are written to disk on the Primary, they are immediately streamed to all connected standby replicas. The replicas read this stream and replay the changes in memory and on disk, mirroring data changes within milliseconds.


### Deep-Dive: HAProxy Layer 4 TCP Load Balancing
An HAProxy container (`haproxy:2.8-alpine`) is deployed on the same VM as the Primary database to route SQL connections.

#### A. Layer 4 TCP Proxying vs. Layer 7 HTTP
Unlike web traffic which is routed using HTTP headers (Layer 7), database traffic utilizes PostgreSQL's own proprietary binary protocol. Therefore, HAProxy is configured in **TCP mode (Layer 4)**. 
At Layer 4, the load balancer acts as a low-overhead stream forwarder: it establishes a TCP socket connection with the client, opens a corresponding socket to the backend database server, and pipes raw bytes back and forth without attempting to parse or validate the SQL queries.

#### B. Dual-Port Routing & Database Schema Strategy
To handle PostgreSQL operations safely, HAProxy exposes two frontends bound to different host ports. To track these two ports in the platform's metadata database:
* **Database Schema Extension:** The platform implements a self-healing schema migration on startup, adding a dedicated `read_host_port` column to the `db_instances` SQLite table.
* **Write Frontend (Port 5432):**
  * **Target Backend:** Bypasses load balancing and maps directly to the single **Primary Database** instance.
  * **Storage:** Tracked in the standard `host_port` column of the SQLite DB.
  * **Purpose:** Ensures all state-modifying actions (`INSERT`, `UPDATE`, `DELETE`, schema modifications) are only executed on the primary database, avoiding data divergence and split-brain issues.
* **Read Frontend (Port 5433):**
  * **Target Backend:** Distributes traffic round-robin across a pool containing **both the Primary database and all Standby replicas**.
  * **Storage:** Tracked in the dedicated `read_host_port` column of the SQLite DB.
  * **Purpose:** Distributes heavy-read workloads (`SELECT` operations, analytical reports) evenly across all active VMs, preventing any single VM from becoming a bottleneck.

#### C. Database Health Checking (`option tcp-check`)
To guarantee high availability, HAProxy monitors backend database health using active TCP probes:
* The configuration directive `option tcp-check` instructs HAProxy to open a TCP connection to each backend database port at regular intervals.
* If a database replica container crashes or its host VM is suspended by the autoscaler's energy-saving logic, HAProxy fails to open the TCP port.
* HAProxy immediately marks that replica as `DOWN` and dynamically stops routing incoming read requests to it.
* Once the replica wakes up and its PostgreSQL port becomes reachable, HAProxy automatically marks it as `UP` and resumes routing connections.

#### D. Dynamic Config Generator & Hot Reloading (SIGHUP)
When you scale the database cluster (via the `/databases/cluster/{cluster_name}/scale` endpoint), the platform performs a hot configuration reload:
1. **Config Generation:** The system regenerates the configuration file (`haproxy.cfg`) with the current active IPs and mapped host ports of all replicas in the cluster.
2. **Writing Configuration:** The system uploads the configuration file directly to `/var/lib/haproxy-{cluster_name}/haproxy.cfg` on the load balancer host.
3. **Signal Trigger (SIGHUP):** The backend triggers a hot reload of HAProxy using the following Docker signal:
   ```bash
   docker kill -s HUP <haproxy_container_name>
   ```
4. **Zero-Downtime Transition:** The `SIGHUP` signal tells the HAProxy master process to spawn new worker threads to handle fresh connections using the new configuration, while keeping the old threads alive to drain existing active queries. This ensures that scaling operations never drop active connections.

#### E. Sample Configuration File (`haproxy.cfg`)
```haproxy
global
    log stdout format raw local0

defaults
    log     global
    mode    tcp
    timeout connect 5s
    timeout client  50s
    timeout server  50s

frontend postgres_write_front
    bind *:5432
    default_backend postgres_primary

backend postgres_primary
    mode tcp
    option tcp-check
    server db-primary 172.16.100.2:32768 check

frontend postgres_read_front
    bind *:5433
    default_backend postgres_replicas

backend postgres_replicas
    mode tcp
    balance roundrobin
    option tcp-check
    server db-primary 172.16.100.2:32768 check
    server db-replica-1 172.16.100.3:32801 check
    server db-replica-2 172.16.100.4:32815 check
```


