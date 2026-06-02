from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class VMCreate(BaseModel):
    name: Optional[str] = None          # auto-generated if not provided
    template_id: Optional[int] = 0      # defaults to Alpine Linux 3.20
    cpu: Optional[float] = None         # override CPU (e.g. 0.5)
    memory_mb: Optional[int] = None     # override Memory (e.g. 1024)
    disk_gb: Optional[int] = None       # override disk size in GB (e.g. 10)
    user_data: Optional[str] = None      # Shell script to run on boot


class VMResponse(BaseModel):
    id: int
    one_vm_id: int
    name: str
    template_id: int
    state: str
    lcm_state: Optional[int] = None
    ip_address: str
    cpu_usage_pct: float
    memory_mb: float
    memory_limit_mb: float
    disk_gb: float
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
    total_ram_mb: float
    used_ram_mb: float


class VMMetricResponse(BaseModel):
    cpu_usage_pct: float
    memory_mb: float
    timestamp: datetime

    class Config:
        from_attributes = True


class EnergyStats(BaseModel):
    total_vm_hours: float
    potential_vm_hours: float
    hours_saved: float
    energy_saved_kwh: float
    co2_saved_kg: float


class TemplateResponse(BaseModel):
    id: int
    name: str
