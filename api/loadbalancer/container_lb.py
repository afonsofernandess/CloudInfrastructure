import logging
import time
from typing import Optional
import docker
from docker.errors import NotFound

from api.containers.docker_client import (
    ensure_user_has_running_vm, get_client, get_all_clients, _container_to_dict
)
from api.loadbalancer.ssh_utils import run_ssh_command, write_ssh_file
from api.database_service import db_manager
from api.loadbalancer.schemas import ContainerScaleRequest, ContainerScaleResponse, ContainerResponse

LABEL_KEY = "cloud_user"
log = logging.getLogger("loadbalancer.container_lb")


def scale_container_group(username: str, data: ContainerScaleRequest) -> ContainerScaleResponse:
    """
    Scale a container group and configure Nginx load balancing:
    1. Scan all active VMs for existing containers in this scale group.
    2. Spin up or tear down containers to match the target replicas count.
    3. Generate and deploy an Nginx configuration routing to all active worker ports.
    4. Start or update the Nginx load balancer container exposing a single entrypoint port.
    """
    group_name = data.name
    target_replicas = data.replicas
    image = data.image
    container_port = data.container_port
    
    if not container_port.endswith("/tcp") and not container_port.endswith("/udp"):
        container_port = f"{container_port}/tcp"

    clients = get_all_clients(username)
    
    workers = []
    load_balancer = None
    lb_vm_id = None
    
    # Step 1: Scan VMs for existing group containers
    for vm_id, client in clients:
        try:
            containers = client.containers.list(all=True)
            for c in containers:
                labels = c.labels
                if labels.get("scale_group") == group_name:
                    info = _container_to_dict(c)
                    info["vm_id"] = vm_id
                    
                    if labels.get("role") == "worker":
                        workers.append((vm_id, c, info))
                    elif labels.get("role") == "load_balancer":
                        load_balancer = (vm_id, c, info)
                        lb_vm_id = vm_id
        except Exception as e:
            log.error("Failed to list containers on VM %d: %s", vm_id, e)
        finally:
            client.close()

    current_count = len(workers)
    
    # Step 2: Scale Worker Containers
    if current_count < target_replicas:
        # Scale UP: spin up more workers using load balancing placement
        for i in range(current_count, target_replicas):
            log.info("Scaling UP container group '%s': provisioning worker #%d...", group_name, i + 1)
            vmid = ensure_user_has_running_vm(username)
            client = get_client(username, vmid)
            
            try:
                client.images.get(image)
            except docker.errors.ImageNotFound:
                client.images.pull(image)
                
            worker_name = f"{username}-{group_name}-worker-{int(time.time())}-{i}"
            c = client.containers.create(
                image,
                name=worker_name,
                labels={
                    LABEL_KEY: username,
                    "scale_group": group_name,
                    "role": "worker",
                    "container_port": container_port
                },
                environment=data.env or {},
                ports={container_port: None},  # Let Docker map a random free host port
                detach=True
            )
            c.start()
            c.reload()
            
            info = _container_to_dict(c)
            info["vm_id"] = vmid
            workers.append((vmid, c, info))
            client.close()
            
    elif current_count > target_replicas:
        # Scale DOWN: stop and remove excess workers
        for i in range(current_count - 1, target_replicas - 1, -1):
            vmid, c, info = workers[i]
            log.info("Scaling DOWN container group '%s': removing worker '%s'...", group_name, c.name)
            client = get_client(username, vmid)
            try:
                container = client.containers.get(c.id)
                container.remove(force=True)
            except Exception as e:
                log.error("Failed to remove container: %s", e)
            finally:
                client.close()
            workers.pop(i)

    # Clean up load balancer if scaled to 0
    if target_replicas == 0:
        if load_balancer:
            lb_vmid, lb_c, _ = load_balancer
            client = get_client(username, lb_vmid)
            try:
                lb_c.remove(force=True)
            except Exception:
                pass
            finally:
                client.close()
        return ContainerScaleResponse(
            scale_group=group_name,
            replicas_count=0,
            load_balancer_address="",
            workers=[],
            load_balancer=None
        )

    # Step 3: Map worker IP addresses and exposed ports
    upstream_servers = []
    workers_resp = []
    
    for vmid, c, info in workers:
        client = get_client(username, vmid)
        try:
            container = client.containers.get(c.id)
            container.reload()
            ports = container.ports
            mapping = ports.get(container_port)
            if mapping:
                host_port = int(mapping[0]["HostPort"])
                ip = db_manager.get_vm_ip_by_id(vmid)
                upstream_servers.append(f"        server {ip}:{host_port};")
                
                resp = ContainerResponse(
                    container_id=container.short_id,
                    name=container.name,
                    image=info["image"],
                    status=container.status,
                    ports=ports,
                    created=info["created"],
                    vm_id=vmid
                )
                workers_resp.append(resp)
        except Exception as e:
            log.error("Failed to query worker details for %s: %s", c.name, e)
        finally:
            client.close()

    # Step 4: Configure and start Nginx HTTP Load Balancer
    # Place Nginx on the VM hosting the first worker
    if not lb_vm_id:
        lb_vm_id = workers[0][0]
        
    lb_vm_ip = db_manager.get_vm_ip_by_id(lb_vm_id)
    
    servers_cfg = "\n".join(upstream_servers)
    nginx_conf = f"""events {{ worker_connections 1024; }}
http {{
    upstream backend_servers {{
{servers_cfg}
    }}

    server {{
        listen 80;
        location / {{
            proxy_pass http://backend_servers;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }}
    }}
}}"""

    # Write nginx config to VM disk
    local_cfg_dir = f"/var/lib/nginx-lb-{group_name}"
    write_ssh_file(lb_vm_ip, f"{local_cfg_dir}/nginx.conf", nginx_conf)

    # Launch or recreate Nginx Load Balancer container
    lb_client = get_client(username, lb_vm_id)
    lb_container_name = f"{username}-{group_name}-lb"
    
    try:
        existing_lb = lb_client.containers.get(lb_container_name)
        existing_lb.remove(force=True)
    except NotFound:
        pass
        
    nginx_container = lb_client.containers.create(
        "nginx:alpine",
        name=lb_container_name,
        labels={
            LABEL_KEY: username,
            "scale_group": group_name,
            "role": "load_balancer"
        },
        ports={"80/tcp": None},  # Bind Nginx port 80 to a random free host port
        volumes={
            local_cfg_dir: {
                "bind": "/etc/nginx",
                "mode": "ro"
            }
        },
        detach=True
    )
    nginx_container.start()
    nginx_container.reload()
    
    lb_port = int(nginx_container.ports["80/tcp"][0]["HostPort"])
    lb_client.close()

    lb_resp = ContainerResponse(
        container_id=nginx_container.short_id,
        name=nginx_container.name,
        image="nginx:alpine",
        status=nginx_container.status,
        ports=nginx_container.ports,
        created=nginx_container.attrs.get("Created", ""),
        vm_id=lb_vm_id
    )

    return ContainerScaleResponse(
        scale_group=group_name,
        replicas_count=len(workers_resp),
        load_balancer_address=f"http://{lb_vm_ip}:{lb_port}",
        workers=workers_resp,
        load_balancer=lb_resp
    )


def get_container_group_details(username: str, group_name: str) -> ContainerScaleResponse:
    """Fetch live status of workers and Nginx load balancer in the container group."""
    clients = get_all_clients(username)
    
    workers_resp = []
    load_balancer = None
    lb_vm_id = None
    
    for vm_id, client in clients:
        try:
            containers = client.containers.list(all=True)
            for c in containers:
                labels = c.labels
                if labels.get("scale_group") == group_name:
                    c.reload()
                    resp = ContainerResponse(
                        container_id=c.short_id,
                        name=c.name,
                        image=c.image.tags[0] if c.image.tags else c.attrs["Config"]["Image"],
                        status=c.status,
                        ports=c.ports,
                        created=c.attrs.get("Created", ""),
                        vm_id=vm_id
                    )
                    if labels.get("role") == "worker":
                        workers_resp.append(resp)
                    elif labels.get("role") == "load_balancer":
                        load_balancer = resp
                        lb_vm_id = vm_id
        except Exception as e:
            log.error("Failed to query containers on VM %d: %s", vm_id, e)
        finally:
            client.close()

    if not workers_resp and not load_balancer:
        raise FileNotFoundError(f"Container scale group '{group_name}' not found.")

    lb_address = ""
    if load_balancer and lb_vm_id:
        lb_vm_ip = db_manager.get_vm_ip_by_id(lb_vm_id)
        ports = load_balancer.ports
        mapping = ports.get("80/tcp")
        if mapping:
            lb_port = mapping[0]["HostPort"]
            lb_address = f"http://{lb_vm_ip}:{lb_port}"

    return ContainerScaleResponse(
        scale_group=group_name,
        replicas_count=len(workers_resp),
        load_balancer_address=lb_address,
        workers=workers_resp,
        load_balancer=load_balancer
    )
