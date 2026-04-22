from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from api.database import get_db
from api.auth.jwt import get_current_user
from api.auth.models import User
from api.compute.models import VMInstance
from api.compute.schemas import VMCreate, VMResponse, ClusterStatus
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
        one_vm_id = create_vm(name, data.template_id, current_user.one_user_id)
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
    instances = db.query(VMInstance).filter(VMInstance.user_id == current_user.id).all()
    results = []
    for instance in instances:
        response = _build_vm_response(instance)
        # Auto-clean stale DB records for VMs that are already terminated in OpenNebula
        if response["state"] in ("DONE", "UNKNOWN"):
            db.delete(instance)
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

    db.delete(instance)
    db.commit()


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
