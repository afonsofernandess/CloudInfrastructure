"""
PostgreSQL-on-demand manager.
Each instance is a postgres:16-alpine Docker container with a randomly generated
password and an auto-assigned host port. Containers are labelled with
cloud_db_user=<username> for per-user isolation.
"""

import secrets
import string
import time
import docker
from docker.errors import NotFound
from datetime import datetime, timezone

POSTGRES_IMAGE = "postgres:16-alpine"
LABEL_KEY = "cloud_db_user"
CONTAINER_PORT = "5432/tcp"


from typing import Optional

def get_user_vm_ip(username: str, vm_id: Optional[int] = None) -> str:
    """Find the IP of the user's active and running VM (optionally targeting a specific vm_id)."""
    from api.database import SessionLocal
    from api.auth.models import User
    from api.compute.models import VMInstance
    from opennebula.vm_manager import get_vm

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise RuntimeError(f"User '{username}' not found in database")

        if vm_id is not None:
            inst = db.query(VMInstance).filter(
                VMInstance.id == vm_id,
                VMInstance.user_id == user.id,
                VMInstance.terminated_at == None
            ).first()
            if not inst:
                raise RuntimeError(f"Active VM with ID {vm_id} not found for user '{username}'")
            instances = [inst]
        else:
            # Find active (non-terminated) VMs for this user
            instances = db.query(VMInstance).filter(
                VMInstance.user_id == user.id,
                VMInstance.terminated_at == None
            ).all()

        for inst in instances:
            try:
                live = get_vm(inst.one_vm_id)
                # Check if it is running and has an IP address
                if live["state"] == "ACTIVE" and live["lcm_state"] == 3: # 3 = RUNNING
                    ip = live.get("ip_address")
                    if ip and ip != "—":
                        return ip
            except Exception:
                continue

        if vm_id is not None:
            raise RuntimeError(f"VM ID {vm_id} is not currently running or accessible.")
        else:
            raise RuntimeError(f"No active and running VMs found for user '{username}'. Please provision a VM first.")
    finally:
        db.close()


def _get_client(username: str, vm_id: Optional[int] = None) -> docker.DockerClient:
    ip = get_user_vm_ip(username, vm_id)
    return docker.DockerClient(base_url=f"ssh://root@{ip}", use_ssh_client=True)


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _ensure_image(client: docker.DockerClient) -> None:
    try:
        client.images.get(POSTGRES_IMAGE)
    except docker.errors.ImageNotFound:
        client.images.pull(POSTGRES_IMAGE)


def provision_db(username: str, instance_name: str, db_name: str, vm_id: Optional[int] = None) -> dict:
    """
    Launch a PostgreSQL container for the user.
    Returns a dict with container_id, host_port, db_name, db_user, db_password, vm_id.
    """
    from api.containers.docker_client import ensure_user_has_running_vm
    resolved_vm_id = ensure_user_has_running_vm(username, vm_id)

    client = _get_client(username, resolved_vm_id)
    _ensure_image(client)

    db_user = username
    db_password = _random_password()
    full_name = f"db-{username}-{instance_name}"

    # Remove any stuck leftover container with this name
    try:
        existing = client.containers.get(full_name)
        if existing.status != "running":
            existing.remove(force=True)
        else:
            raise RuntimeError(f"A database instance named '{instance_name}' is already running — delete it first")
    except NotFound:
        pass

    container = client.containers.create(
        POSTGRES_IMAGE,
        name=full_name,
        labels={LABEL_KEY: username},
        environment={
            "POSTGRES_DB": db_name,
            "POSTGRES_USER": db_user,
            "POSTGRES_PASSWORD": db_password,
        },
        ports={CONTAINER_PORT: None},   # let Docker pick a free host port
        volumes={
            f"/var/lib/postgresql/data-{instance_name}": {
                "bind": "/var/lib/postgresql/data",
                "mode": "rw"
            }
        },
        detach=True,
    )

    try:
        container.start()
    except Exception as e:
        container.remove(force=True)
        raise RuntimeError(f"Failed to start PostgreSQL container: {e}") from e

    # Wait up to 15 s for PostgreSQL to bind the port (it writes to logs when ready)
    host_port = _wait_for_port(container, timeout=15)

    return {
        "container_id": container.id,
        "host_port": host_port,
        "db_name": db_name,
        "db_user": db_user,
        "db_password": db_password,
        "vm_id": resolved_vm_id,
    }


def _wait_for_port(container, timeout: int = 15) -> int:
    """Poll until Docker reports the mapped host port (assigned at container start)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        container.reload()
        ports = container.ports
        mapping = ports.get(CONTAINER_PORT)
        if mapping:
            return int(mapping[0]["HostPort"])
        time.sleep(0.3)
    raise RuntimeError("PostgreSQL container started but no host port was assigned in time")


def get_db_container_and_client(username: str, container_id: str):
    """Search across all active VMs for the database container and return (client, container, vm_id)."""
    from api.containers.docker_client import get_all_clients
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            c = client.containers.get(container_id)
            return client, c, vm_id
        except Exception:
            continue
    return None, None, None


def get_vm_ip_by_id(vm_id: int) -> str:
    from api.database import SessionLocal
    from api.compute.models import VMInstance
    from opennebula.vm_manager import get_vm
    db = SessionLocal()
    try:
        inst = db.query(VMInstance).filter(VMInstance.id == vm_id).first()
        if inst:
            live = get_vm(inst.one_vm_id)
            return live.get("ip_address", "localhost")
    except Exception:
        pass
    finally:
        db.close()
    return "localhost"


def get_container_status(username: str, container_id: str) -> str:
    """Return the Docker status string (running, exited, …) for a container."""
    try:
        _, container, _ = get_db_container_and_client(username, container_id)
        if container:
            return container.status
        return "removed"
    except Exception:
        return "unknown"


def deprovision_db(username: str, container_id: str) -> None:
    """
    Stop and remove the PostgreSQL container.
    Raises PermissionError if the container does not belong to the user.
    """
    try:
        _, container, _ = get_db_container_and_client(username, container_id)
    except Exception:
        return  # connection error, VM offline etc.

    if not container:
        return  # already gone — treat as success

    if container.labels.get(LABEL_KEY) != username:
        raise PermissionError("Database instance does not belong to this user")

    container.remove(force=True)


def get_db_metrics(username: str, container_id: str, db_user: str, db_name: str, db_password: str) -> dict:
    """Run queries inside the PostgreSQL container via Docker exec to fetch connection count and size."""
    import subprocess
    try:
        client, container, vm_id = get_db_container_and_client(username, container_id)
        if not container or container.status != "running" or not vm_id:
            return {"active_connections": 0, "db_size": "0 kB", "error": "Container is not running"}

        ip = get_vm_ip_by_id(vm_id)
        if not ip or ip == "localhost":
            return {"active_connections": 0, "db_size": "0 kB", "error": "Could not resolve VM IP"}

        # Query 1: Active connections
        cmd_connections = [
            "ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
            f"docker exec -e PGPASSWORD={db_password} {container.name} psql -U {db_user} -d {db_name} -t -c \"SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';\""
        ]
        res_conn = subprocess.run(cmd_connections, capture_output=True, text=True, timeout=5)
        connections = 0
        if res_conn.returncode == 0:
            try:
                connections = int(res_conn.stdout.strip())
            except ValueError:
                pass

        # Query 2: Database size
        cmd_size = [
            "ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
            f"docker exec -e PGPASSWORD={db_password} {container.name} psql -U {db_user} -d {db_name} -t -c \"SELECT pg_size_pretty(pg_database_size('{db_name}'));\""
        ]
        res_size = subprocess.run(cmd_size, capture_output=True, text=True, timeout=5)
        db_size = "0 kB"
        if res_size.returncode == 0:
            db_size = res_size.stdout.strip()

        return {
            "active_connections": connections,
            "db_size": db_size,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"active_connections": 0, "db_size": "0 kB", "error": str(e)}
