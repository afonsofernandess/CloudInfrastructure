from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from api.database import Base


class VMInstance(Base):
    """
    Tracks which user owns which VM.
    one_vm_id is the VM's ID in OpenNebula (source of truth for state/metrics).
    """
    __tablename__ = "vm_instances"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    one_vm_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    template_id = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Track termination to calculate energy savings even after the VM is gone
    terminated_at = Column(DateTime(timezone=True), nullable=True)


class VMMetric(Base):
    """
    Historical resource usage for graphing.
    """
    __tablename__ = "vm_metrics"

    id = Column(Integer, primary_key=True, index=True)
    vm_instance_id = Column(Integer, ForeignKey("vm_instances.id"), nullable=False)
    cpu_usage_pct = Column(Integer)
    memory_mb = Column(Integer)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
