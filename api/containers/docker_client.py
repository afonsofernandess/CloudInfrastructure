"""
Docker client wrapper.
Containers are labelled with cloud_user=<username> for per-user isolation.
All container operations filter by this label so users never see each other's containers.
"""

import docker
from docker.errors import NotFound, APIError

LABEL_KEY = "cloud_user"


def get_client() -> docker.DockerClient:
    return docker.from_env()


def container_label(username: str) -> dict:
    return {LABEL_KEY: username}


def launch_container(username: str, image: str, name: str, env: dict = None, ports: list = None) -> dict:
    """
    Pull image if needed and run a container for the user.
    - name     : container name (prefixed with username to avoid conflicts)
    - env      : dict of environment variables e.g. {"MY_VAR": "value"}
    - ports    : list of container ports to expose e.g. ["80/tcp", "443/tcp"]
                 host ports are auto-assigned by Docker
    Returns a dict with container info.
    """
    client = get_client()
    full_name = f"{username}-{name}"

    # Pre-flight: remove any leftover container with this name that is not running
    # (e.g. from a previous failed start). Running containers are left alone.
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
    return _container_to_dict(container)


def list_containers(username: str) -> list[dict]:
    """List all containers (running or stopped) belonging to the user."""
    client = get_client()
    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_KEY}={username}"},
    )
    return [_container_to_dict(c) for c in containers]


def get_container(username: str, container_id: str) -> dict:
    """Get a single container by ID, verifying it belongs to the user."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
    except NotFound:
        raise FileNotFoundError(f"Container '{container_id}' not found")

    if container.labels.get(LABEL_KEY) != username:
        raise PermissionError("Container does not belong to this user")

    return _container_to_dict(container)


def start_container(username: str, container_id: str) -> dict:
    """Start a stopped container."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
    except NotFound:
        raise FileNotFoundError(f"Container '{container_id}' not found")

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
    return _container_to_dict(container)


def stop_container(username: str, container_id: str) -> dict:
    """Stop a running container."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
    except NotFound:
        raise FileNotFoundError(f"Container '{container_id}' not found")

    if container.labels.get(LABEL_KEY) != username:
        raise PermissionError("Container does not belong to this user")

    container.stop()
    container.reload()
    return _container_to_dict(container)


def remove_container(username: str, container_id: str) -> None:
    """Stop (if running) and remove a container."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
    except NotFound:
        raise FileNotFoundError(f"Container '{container_id}' not found")

    if container.labels.get(LABEL_KEY) != username:
        raise PermissionError("Container does not belong to this user")

    container.remove(force=True)


def _container_to_dict(container) -> dict:
    container.reload()
    ports = container.ports or {}
    return {
        "container_id": container.short_id,
        "full_id": container.id,
        "name": container.name,
        "image": container.image.tags[0] if container.image.tags else container.attrs["Config"]["Image"],
        "status": container.status,         # running, exited, created, etc.
        "ports": ports,
        "created": container.attrs.get("Created", ""),
    }
