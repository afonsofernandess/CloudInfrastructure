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
