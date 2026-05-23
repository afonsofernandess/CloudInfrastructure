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

    class Config:
        from_attributes = True


class DBMetricsResponse(BaseModel):
    active_connections: int
    db_size: str
    timestamp: str
    error: Optional[str] = None
