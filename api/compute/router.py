import pyone
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from api.database import get_db
from api.auth.jwt import get_current_user
from api.auth.models import User
from api.compute.models import VMInstance, VMMetric
from api.database_service.models import DBInstance
from api.compute.schemas import VMCreate, VMResponse, ClusterStatus, VMMetricResponse, EnergyStats, TemplateResponse
from api.compute import sla
from opennebula.vm_manager import create_vm, destroy_vm, get_vm, list_vms_by_one_user, suspend_vm, resume_vm

router = APIRouter(prefix="/compute", tags=["compute"])


def _build_vm_response(instance: VMInstance) -> dict:
    """Merge local DB record with live OpenNebula metrics."""
    try:
        live = get_vm(instance.one_vm_id)
    except pyone.OneNoExistsException:
        live = {"state": "DONE", "cpu_usage_pct": 0.0, "memory_mb": 0.0, "memory_limit_mb": 2048.0, "disk_gb": 2.0}
    except Exception:
        live = {"state": "UNREACHABLE", "cpu_usage_pct": 0.0, "memory_mb": 0.0, "memory_limit_mb": 2048.0, "disk_gb": 2.0}

    return {
        "id": instance.id,
        "one_vm_id": instance.one_vm_id,
        "name": instance.name,
        "template_id": instance.template_id,
        "created_at": instance.created_at,
        "state": live["state"],
        "lcm_state": live.get("lcm_state"),
        "ip_address": live.get("ip_address", "—"),
        "cpu_usage_pct": live["cpu_usage_pct"],
        "memory_mb": live["memory_mb"],
        "memory_limit_mb": live.get("memory_limit_mb", 2048.0),
        "disk_gb": live.get("disk_gb", 2.0),
    }


# POST /compute/vms — provision a VM
@router.post("/vms", response_model=VMResponse, status_code=status.HTTP_201_CREATED)
def provision_vm(
    data: VMCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Enforce MAX_VMS SLA per user
    user_vm_count = db.query(VMInstance).filter(
        VMInstance.user_id == current_user.id,
        VMInstance.terminated_at == None
    ).count()
    if user_vm_count >= sla.MAX_VMS:
        raise HTTPException(
            status_code=400,
            detail=f"SLA limit reached: max {sla.MAX_VMS} VMs allowed.",
        )

    name = data.name or f"vm-user{current_user.id}-{int(datetime.now(timezone.utc).timestamp())}"

    # Pre-warming optimization: only claim a pre-warmed VM if no overrides (CPU, memory, disk, or user_data) are requested AND the template is the default Alpine template (ID 0)
    prewarmed_vm = None
    if (data.template_id == 0 and data.cpu is None and data.memory_mb is None and data.disk_gb is None and data.user_data is None):
        try:
            from opennebula.vm_manager import list_all_vms
            all_vms = list_all_vms()
            for vm in all_vms:
                if vm["name"].startswith("prewarmed-vm-") and vm["state"] == "ACTIVE" and vm.get("lcm_state") == 3:
                    # Make sure it isn't already registered as active in our DB
                    inst_check = db.query(VMInstance).filter(VMInstance.one_vm_id == vm["one_vm_id"]).first()
                    if not inst_check or inst_check.terminated_at is not None:
                        prewarmed_vm = vm
                        break
        except Exception as e:
            print(f"DEBUG: Failed to search for pre-warmed VMs: {e}")

    one_vm_id = None
    if prewarmed_vm:
        try:
            one_vm_id = prewarmed_vm["one_vm_id"]
            # Claim in OpenNebula: rename and change ownership
            from opennebula.connection import get_client
            client = get_client()
            client.vm.rename(one_vm_id, name)
            client.vm.chown(one_vm_id, current_user.one_user_id, -1)
            print(f"DEBUG: Successfully claimed pre-warmed VM for manual provision (one_vm_id={one_vm_id})")
        except Exception as e:
            print(f"DEBUG: Failed to claim pre-warmed VM, falling back to full creation: {e}")
            prewarmed_vm = None

    if not prewarmed_vm:
        # Fall back to standard on-demand creation
        try:
            one_vm_id = create_vm(
                name=name,
                template_id=data.template_id,
                user_id=current_user.one_user_id,
                cpu=data.cpu,
                memory_mb=data.memory_mb,
                disk_gb=data.disk_gb,
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
        if response["state"] == "DONE":
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

    # --- Cascade cleanup: remove orphaned DB instance records for this VM ---
    # Containers live inside Docker on the VM and are physically destroyed with it.
    # But DBInstance records in SQLite would remain pointing to a dead container.
    # We find which db_instances belonged to this VM by cross-referencing the
    # vm_id stored in get_db_container_and_client, then delete those records.
    try:
        from api.database_service import db_manager
        user_db_instances = db.query(DBInstance).filter(
            DBInstance.user_id == current_user.id
        ).all()
        for db_inst in user_db_instances:
            client, _, db_vm_id = db_manager.get_db_container_and_client(
                current_user.username, db_inst.container_id
            )
            if client:
                try:
                    client.close()
                except Exception:
                    pass
            if db_vm_id == instance.id:
                db.delete(db_inst)
    except Exception:
        # Non-fatal: VM is already being destroyed, best-effort cleanup
        pass

    instance.terminated_at = datetime.now(timezone.utc)
    db.commit()

    # We keep the VMInstance record in the DB (but state DONE) so we can
    # calculate total uptime/energy saved later.
    # The list_vms endpoint already filters out terminated VMs from the UI.


# POST /compute/vms/{vm_id}/start — start (resume) a VM
@router.post("/vms/{vm_id}/start", response_model=VMResponse)
def start_vm(
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
        resume_vm(instance.one_vm_id)
        try:
            from api.compute.autoscaler import queue_vm_for_recovery
            queue_vm_for_recovery(instance.one_vm_id)
        except Exception:
            pass  # Best effort
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenNebula error: {e}")

    return _build_vm_response(instance)


# POST /compute/vms/{vm_id}/stop — stop (suspend) a VM
@router.post("/vms/{vm_id}/stop", response_model=VMResponse)
def stop_vm(
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
        suspend_vm(instance.one_vm_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenNebula error: {e}")

    return _build_vm_response(instance)



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
    used_ram = sum(vm.get("memory_mb", 0.0) for vm in active_vms)
    total_ram = sum(vm.get("memory_limit_mb", 2048.0) for vm in active_vms)

    return {
        "total_vms": len(user_vms),
        "active_vms": len(active_vms),
        "avg_cpu_pct": round(avg_cpu, 1),
        "autoscaler_enabled": autoscaler.enabled,
        "min_vms": sla.MIN_VMS,
        "max_vms": sla.MAX_VMS,
        "scale_up_threshold_pct": sla.SCALE_UP_CPU_PCT,
        "scale_down_threshold_pct": sla.SCALE_DOWN_CPU_PCT,
        "total_ram_mb": float(total_ram),
        "used_ram_mb": float(used_ram),
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


# POST /compute/prewarm — pre-warm / ensure VM is booted in the background
@router.post("/prewarm", status_code=status.HTTP_202_ACCEPTED)
def prewarm_vm(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    from api.containers.docker_client import ensure_user_has_running_vm
    
    def do_prewarm():
        try:
            ensure_user_has_running_vm(current_user.username)
        except Exception as e:
            # Asynchronous log warning
            print(f"Background pre-warm error for user '{current_user.username}': {e}")

    background_tasks.add_task(do_prewarm)
    return {"message": "Pre-warming initiated in the background"}


# GET /compute/templates — list available VM templates from OpenNebula
@router.get("/templates", response_model=list[TemplateResponse])
def get_templates(
    current_user: User = Depends(get_current_user),
):
    from opennebula.vm_manager import list_templates
    return list_templates()
