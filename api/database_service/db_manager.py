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

POSTGRES_IMAGE = "postgres:16-alpine"
LABEL_KEY = "cloud_db_user"
CONTAINER_PORT = "5432/tcp"


def _get_client() -> docker.DockerClient:
    return docker.from_env()


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _ensure_image(client: docker.DockerClient) -> None:
    try:
        client.images.get(POSTGRES_IMAGE)
    except docker.errors.ImageNotFound:
        client.images.pull(POSTGRES_IMAGE)


def provision_db(username: str, instance_name: str, db_name: str) -> dict:
    """
    Launch a PostgreSQL container for the user.
    Returns a dict with container_id, host_port, db_name, db_user, db_password.
    """
    client = _get_client()
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


def get_container_status(container_id: str) -> str:
    """Return the Docker status string (running, exited, …) for a container."""
    client = _get_client()
    try:
        c = client.containers.get(container_id)
        c.reload()
        return c.status
    except NotFound:
        return "removed"


def deprovision_db(username: str, container_id: str) -> None:
    """
    Stop and remove the PostgreSQL container.
    Raises PermissionError if the container does not belong to the user.
    """
    client = _get_client()
    try:
        container = client.containers.get(container_id)
    except NotFound:
        return  # already gone — treat as success

    if container.labels.get(LABEL_KEY) != username:
        raise PermissionError("Database instance does not belong to this user")

    container.remove(force=True)
