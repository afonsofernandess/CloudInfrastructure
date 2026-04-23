from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from api.database import Base


class DBInstance(Base):
    """
    Tracks a provisioned PostgreSQL instance (runs as a Docker container).
    Credentials are stored here so they can be retrieved by the user at any time.
    """
    __tablename__ = "db_instances"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    container_id = Column(String, unique=True, nullable=False)   # Docker full container ID
    instance_name = Column(String, nullable=False)               # user-visible name
    db_name = Column(String, nullable=False)                     # POSTGRES_DB
    db_user = Column(String, nullable=False)                     # POSTGRES_USER
    db_password = Column(String, nullable=False)                 # POSTGRES_PASSWORD (plaintext — internal use)
    host_port = Column(Integer, nullable=False)                  # host port Docker assigned to 5432
    created_at = Column(DateTime(timezone=True), server_default=func.now())
