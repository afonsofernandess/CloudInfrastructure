from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from api.database import get_db
from api.auth.jwt import get_current_user
from api.auth.models import User
from api.compute.models import VMInstance, VMMetric
from api.compute.schemas import VMCreate, VMResponse, ClusterStatus, VMMetricResponse, EnergyStats
from api.compute import sla
from opennebula.vm_manager import create_vm, destroy_vm, get_vm, list_vms_by_one_user

router = APIRouter(prefix="/compute", tags=["compute"])


def _build_vm_response(instance: VMInstance) -> dict:
    """Merge local DB record with live OpenNebula metrics."""
    try:
        live = get_vm(instance.one_vm_id)
    except Exception:
        live = {"state": "UNKNOWN", "cpu_usage_pct": 0.0, "memory_mb": 0.0}

    return {
        "id": instance.id,
        "one_vm_id": instance.one_vm_id,
        "name": instance.name,
        "template_id": instance.template_id,
        "created_at": instance.created_at,
        "state": live["state"],
        "ip_address": live.get("ip_address", "—"),
        "cpu_usage_pct": live["cpu_usage_pct"],
        "memory_mb": live["memory_mb"],
    }


# POST /compute/vms — provision a VM
@router.post("/vms", response_model=VMResponse, status_code=status.HTTP_201_CREATED)
def provision_vm(
    data: VMCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Enforce MAX_VMS SLA per user
    user_vm_count = db.query(VMInstance).filter(VMInstance.user_id == current_user.id).count()
    if user_vm_count >= sla.MAX_VMS:
        raise HTTPException(
            status_code=400,
            detail=f"SLA limit reached: max {sla.MAX_VMS} VMs allowed.",
        )

    name = data.name or f"vm-user{current_user.id}-{int(datetime.now(timezone.utc).timestamp())}"

    try:
        one_vm_id = create_vm(
            name=name,
            template_id=data.template_id,
            user_id=current_user.one_user_id,
            cpu=data.cpu,
            memory_mb=data.memory_mb,
            user_data=data.user_data,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenNebula error: {e}")

    instance = VMInstance(
        user_id=current_user.id,
        one_vm_id=one_vm_id,
        name=name,
        template_id=data.template_id,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)

    return _build_vm_response(instance)


# GET /compute/vms — list current user's VMs
@router.get("/vms", response_model=list[VMResponse])
def list_vms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only show VMs that haven't been terminated
    instances = db.query(VMInstance).filter(
        VMInstance.user_id == current_user.id,
        VMInstance.terminated_at == None
    ).all()
    
    results = []
    for instance in instances:
        response = _build_vm_response(instance)
        # If OpenNebula says it's gone, mark it as terminated locally but don't delete
        if response["state"] in ("DONE", "UNKNOWN"):
            instance.terminated_at = datetime.now(timezone.utc)
            db.commit()
        else:
            results.append(response)
    return results


# GET /compute/vms/{vm_id} — get a single VM with live metrics
@router.get("/vms/{vm_id}", response_model=VMResponse)
def get_vm_detail(
    vm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = db.query(VMInstance).filter(
        VMInstance.id == vm_id,
        VMInstance.user_id == current_user.id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="VM not found")

    return _build_vm_response(instance)


# DELETE /compute/vms/{vm_id} — destroy a VM
@router.delete("/vms/{vm_id}", status_code=status.HTTP_204_NO_CONTENT)
def terminate_vm(
    vm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = db.query(VMInstance).filter(
        VMInstance.id == vm_id,
        VMInstance.user_id == current_user.id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="VM not found")

    try:
        destroy_vm(instance.one_vm_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenNebula error: {e}")

    instance.terminated_at = datetime.now(timezone.utc)
    db.commit()
    
    # We keep the record in the DB (but state UNKNOWN/DONE) so we can calculate total uptime/energy saved later
    # The list_vms endpoint already filters out DONE VMs from the UI.


# GET /compute/status — current user's VM metrics + SLA info
@router.get("/status", response_model=ClusterStatus)
def cluster_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from api.compute.autoscaler import autoscaler

    user_vms = list_vms_by_one_user(current_user.one_user_id)
    active_vms = [vm for vm in user_vms if vm["state"] == "ACTIVE"]
    avg_cpu = (
        sum(vm["cpu_usage_pct"] for vm in active_vms) / len(active_vms)
        if active_vms else 0.0
    )

    return {
        "total_vms": len(user_vms),
        "active_vms": len(active_vms),
        "avg_cpu_pct": round(avg_cpu, 1),
        "autoscaler_enabled": autoscaler.enabled,
        "min_vms": sla.MIN_VMS,
        "max_vms": sla.MAX_VMS,
        "scale_up_threshold_pct": sla.SCALE_UP_CPU_PCT,
        "scale_down_threshold_pct": sla.SCALE_DOWN_CPU_PCT,
    }


# GET /compute/vms/{vm_id}/metrics — historical metrics for graphs
@router.get("/vms/{vm_id}/metrics", response_model=list[VMMetricResponse])
def get_vm_metrics(
    vm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = db.query(VMInstance).filter(
        VMInstance.id == vm_id,
        VMInstance.user_id == current_user.id
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="VM not found")

    # Return last 50 data points (~25 mins of data)
    metrics = db.query(VMMetric).filter(
        VMMetric.vm_instance_id == vm_id
    ).order_by(VMMetric.timestamp.desc()).limit(50).all()
    
    # Reverse so they are in chronological order for the chart
    return sorted(metrics, key=lambda x: x.timestamp)


# GET /compute/energy — global energy savings stats
@router.get("/energy-stats", response_model=EnergyStats)
def get_energy_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_instances = db.query(VMInstance).filter(VMInstance.user_id == current_user.id).all()
    
    total_uptime_sec = 0
    now = datetime.now(timezone.utc)
    
    for vm in all_instances:
        end_time = vm.terminated_at or now
        # Ensure end_time is timezone-aware
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        start_time = vm.created_at
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
            
        duration = (end_time - start_time).total_seconds()
        total_uptime_sec += max(0, duration)

    total_hours = total_uptime_sec / 3600
    
    # Baseline: what if we always ran MAX_VMS?
    # Calculate from the time the first VM was created until now
    if not all_instances:
        return {
            "total_vm_hours": 0,
            "potential_vm_hours": 0,
            "hours_saved": 0,
            "energy_saved_kwh": 0,
            "co2_saved_kg": 0
        }
        
    first_created = min(vm.created_at for vm in all_instances)
    if first_created.tzinfo is None:
        first_created = first_created.replace(tzinfo=timezone.utc)
        
    project_duration_hours = (now - first_created).total_seconds() / 3600
    potential_hours = project_duration_hours * sla.MAX_VMS
    
    hours_saved = max(0, potential_hours - total_hours)
    
    # Constants for estimation
    WATT_PER_VM = 50 # 50W average per VM
    KWH_SAVED = (hours_saved * WATT_PER_VM) / 1000
    CO2_PER_KWH = 0.4 # 0.4kg CO2 per kWh (approx average)
    
    return {
        "total_vm_hours": round(total_hours, 2),
        "potential_vm_hours": round(potential_hours, 2),
        "hours_saved": round(hours_saved, 2),
        "energy_saved_kwh": round(KWH_SAVED, 2),
        "co2_saved_kg": round(KWH_SAVED * CO2_PER_KWH, 2)
    }
