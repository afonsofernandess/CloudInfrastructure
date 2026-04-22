from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class VMCreate(BaseModel):
    name: Optional[str] = None          # auto-generated if not provided
    template_id: Optional[int] = 0      # defaults to Alpine Linux 3.20


class VMResponse(BaseModel):
    id: int
    one_vm_id: int
    name: str
    template_id: int
    state: str
    cpu_usage_pct: float
    memory_mb: float
    created_at: datetime

    class Config:
        from_attributes = True


class ClusterStatus(BaseModel):
    total_vms: int
    active_vms: int
    avg_cpu_pct: float
    autoscaler_enabled: bool
    min_vms: int
    max_vms: int
    scale_up_threshold_pct: float
    scale_down_threshold_pct: float
