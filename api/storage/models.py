from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from api.database import Base


class DiskInstance(Base):
    """
    Tracks an allocated OpenNebula block storage image/disk.
    """
    __tablename__ = "disk_instances"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    one_image_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    size_gb = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
