"""
Docker client wrapper.
Containers are labelled with cloud_user=<username> for per-user isolation.
All container operations filter by this label so users never see each other's containers.
"""

import docker
from docker.errors import NotFound, APIError
from typing import Optional

LABEL_KEY = "cloud_user"


def get_client(username: str, vm_id: Optional[int] = None) -> docker.DockerClient:
    """Return a Docker client connected to the user's specified VM or first active VM via SSH."""
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
            # Look up specific VM
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
                        return docker.DockerClient(base_url=f"ssh://root@{ip}", use_ssh_client=True)
            except Exception:
                continue

        if vm_id is not None:
            raise RuntimeError(f"VM ID {vm_id} is not currently running or accessible.")
        else:
            raise RuntimeError(f"No active and running VMs found for user '{username}'. Please provision a VM first.")
    finally:
        db.close()


def get_all_clients(username: str) -> list[tuple[int, docker.DockerClient]]:
    """Return a list of (vm_instance_id, docker_client) tuples for all active VMs of the user."""
    from api.database import SessionLocal
    from api.auth.models import User
    from api.compute.models import VMInstance
    from opennebula.vm_manager import get_vm

    db = SessionLocal()
    clients = []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        instances = db.query(VMInstance).filter(
            VMInstance.user_id == user.id,
            VMInstance.terminated_at == None
        ).all()
        for inst in instances:
            try:
                live = get_vm(inst.one_vm_id)
                if live["state"] == "ACTIVE" and live["lcm_state"] == 3:
                    ip = live.get("ip_address")
                    if ip and ip != "—":
                        cli = docker.DockerClient(base_url=f"ssh://root@{ip}", use_ssh_client=True)
                        clients.append((inst.id, cli))
            except Exception:
                continue
        return clients
    finally:
        db.close()


def container_label(username: str) -> dict:
    return {LABEL_KEY: username}


def launch_container(
    username: str,
    image: str,
    name: str,
    env: dict = None,
    ports: list = None,
    vm_id: Optional[int] = None
) -> dict:
    """
    Pull image if needed and run a container for the user.
    """
    client = get_client(username, vm_id)
    full_name = f"{username}-{name}"

    # Pre-flight: remove any leftover container with this name that is not running
    try:
        existing = client.containers.get(full_name)
        if existing.status != "running":
            existing.remove(force=True)
        else:
            raise RuntimeError(f"A container named '{name}' is already running — stop it first")
    except NotFound:
        pass  # no leftover, proceed normally

    # Pull image if not available locally
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        client.images.pull(image)

    # Build port bindings: {container_port: None} lets Docker pick a free host port
    port_bindings = {p: None for p in (ports or [])}

    container = client.containers.create(
        image,
        name=full_name,
        labels=container_label(username),
        environment=env or {},
        ports=port_bindings,
    )
    try:
        container.start()
    except Exception as e:
        container.remove(force=True)
        msg = str(e)
        if "port is already allocated" in msg or "Bind for" in msg:
            raise RuntimeError("Port already in use — choose a different host port") from e
        raise RuntimeError(msg) from e

    container.reload()
    res = _container_to_dict(container)
    if vm_id is not None:
        res["vm_id"] = vm_id
    else:
        # Resolve which vm_id we used
        clients = get_all_clients(username)
        for vid, cli in clients:
            try:
                cli.containers.get(full_name)
                res["vm_id"] = vid
                break
            except Exception:
                continue
    return res


def list_containers(username: str) -> list[dict]:
    """List all containers belonging to the user across all their active VMs."""
    clients = get_all_clients(username)
    all_containers = []
    for vm_id, client in clients:
        try:
            containers = client.containers.list(
                all=True,
                filters={"label": f"{LABEL_KEY}={username}"},
            )
            for c in containers:
                info = _container_to_dict(c)
                info["vm_id"] = vm_id
                all_containers.append(info)
        except Exception:
            continue
    return all_containers


def get_container(username: str, container_id: str) -> dict:
    """Get a single container by ID, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) == username:
                info = _container_to_dict(container)
                info["vm_id"] = vm_id
                return info
        except NotFound:
            continue
        except Exception:
            continue
    raise FileNotFoundError(f"Container '{container_id}' not found on any active VMs")


def start_container(username: str, container_id: str) -> dict:
    """Start a stopped container, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            try:
                container.start()
            except Exception as e:
                msg = str(e)
                if "port is already allocated" in msg or "Bind for" in msg:
                    raise RuntimeError("Port already in use — stop the other container using that port first") from e
                raise RuntimeError(msg) from e
            container.reload()
            info = _container_to_dict(container)
            info["vm_id"] = vm_id
            return info
        except NotFound:
            continue
    raise FileNotFoundError(f"Container '{container_id}' not found")


def stop_container(username: str, container_id: str) -> dict:
    """Stop a running container, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            container.stop()
            container.reload()
            info = _container_to_dict(container)
            info["vm_id"] = vm_id
            return info
        except NotFound:
            continue
    raise FileNotFoundError(f"Container '{container_id}' not found")


def remove_container(username: str, container_id: str) -> None:
    """Stop and remove a container, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            container.remove(force=True)
            return
        except NotFound:
            continue
    raise FileNotFoundError(f"Container '{container_id}' not found")


def _container_to_dict(container) -> dict:
    container.reload()
    ports = container.ports or {}
    return {
        "container_id": container.short_id,
        "full_id": container.id,
        "name": container.name,
        "image": container.image.tags[0] if container.image.tags else container.attrs["Config"]["Image"],
        "status": container.status,
        "ports": ports,
        "created": container.attrs.get("Created", ""),
    }
