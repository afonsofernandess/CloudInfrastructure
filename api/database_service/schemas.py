from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DBProvisionRequest(BaseModel):
    name: str                           # user-visible instance name, e.g. "my-analytics-db"
    db_name: Optional[str] = None       # database name inside PostgreSQL (defaults to username)
    vm_id: Optional[int] = None         # Optional VM ID to provision on


class DBCredentials(BaseModel):
    host: str
    port: int
    db_name: str
    db_user: str
    db_password: str
    connection_string: str              # ready-to-use DSN


class DBInstanceResponse(BaseModel):
    id: int
    instance_name: str
    container_id: str
    status: str                         # running, exited, etc. (live from Docker)
    credentials: DBCredentials
    created_at: datetime
    vm_id: Optional[int] = None         # VM ID hosting the database
    role: str = "primary"
    parent_id: Optional[int] = None
    cluster_name: Optional[str] = None
    read_host_port: Optional[int] = None

    class Config:
        from_attributes = True


class DBClusterProvisionRequest(BaseModel):
    cluster_name: str
    db_name: Optional[str] = None
    replicas: int = 1


class DBClusterResponse(BaseModel):
    cluster_name: str
    primary: DBInstanceResponse
    replicas: list[DBInstanceResponse]
    load_balancer: Optional[DBInstanceResponse] = None


class DBMetricsResponse(BaseModel):
    active_connections: int
    db_size: str
    timestamp: str
    error: Optional[str] = None
