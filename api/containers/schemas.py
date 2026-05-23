from pydantic import BaseModel
from typing import Optional


class ContainerCreate(BaseModel):
    image: str                              # e.g. "nginx:latest", "python:3.12-alpine"
    name: str                               # short name, will be prefixed with username
    env: Optional[dict[str, str]] = {}      # environment variables
    ports: Optional[list[str]] = []         # container ports to expose, e.g. ["80/tcp", "443/tcp"]
                                            # host ports are auto-assigned by Docker to avoid conflicts
    vm_id: Optional[int] = None             # Optional VM database ID to launch on


class ContainerResponse(BaseModel):
    container_id: str
    name: str
    image: str
    status: str
    ports: dict
    created: str
    vm_id: Optional[int] = None             # VM ID where the container is running
