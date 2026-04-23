from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DBProvisionRequest(BaseModel):
    name: str                           # user-visible instance name, e.g. "my-analytics-db"
    db_name: Optional[str] = None       # database name inside PostgreSQL (defaults to username)


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

    class Config:
        from_attributes = True
