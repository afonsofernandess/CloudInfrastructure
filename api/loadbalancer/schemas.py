from pydantic import BaseModel
from typing import Optional
from api.containers.schemas import ContainerResponse
from api.database_service.schemas import DBInstanceResponse


class ContainerScaleRequest(BaseModel):
    name: str                               # scale group name, e.g. "my-web-app"
    image: str                              # image to run, e.g. "nginx:alpine"
    replicas: int                           # number of container instances
    container_port: str = "80/tcp"          # port of container to balance (e.g. "80/tcp")
    env: Optional[dict[str, str]] = {}      # optional environment variables
    no_autoscale: bool = False              # if True, workers will be excluded from autoscaling


class ContainerScaleResponse(BaseModel):
    scale_group: str
    replicas_count: int
    load_balancer_address: str              # e.g. "http://<VM_IP>:<LB_PORT>"
    workers: list[ContainerResponse]
    load_balancer: Optional[ContainerResponse] = None


class DBClusterProvisionRequest(BaseModel):
    cluster_name: str
    db_name: Optional[str] = None
    replicas: int = 1


class DBClusterResponse(BaseModel):
    cluster_name: str
    primary: DBInstanceResponse
    replicas: list[DBInstanceResponse]
    load_balancer: Optional[DBInstanceResponse] = None
