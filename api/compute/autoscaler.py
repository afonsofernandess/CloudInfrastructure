"""
Auto-scaler background thread.

Runs every CHECK_INTERVAL_SEC seconds and applies the SLA policy:
- If avg CPU > SCALE_UP_CPU_PCT and total VMs < MAX_VMS  → spin up a new VM
- If avg CPU < SCALE_DOWN_CPU_PCT and total VMs > MIN_VMS → tear down the oldest idle VM

Started and stopped via FastAPI's lifespan in main.py.
"""

import threading
import logging
from datetime import datetime, timezone

from opennebula.vm_manager import create_vm, destroy_vm, list_all_vms
from api.compute.monitor import get_cluster_metrics
from api.compute import sla

AUTOSCALE_PREFIX = "autoscale-vm-"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("autoscaler")
log.setLevel(logging.INFO)

# Tracks how long each VM (by one_vm_id) has been below the idle threshold
_idle_since: dict[int, datetime] = {}


class AutoScaler:
    def __init__(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._stop_event = threading.Event()
        self.enabled = True
        self._last_scale_up = datetime.min.replace(tzinfo=timezone.utc)
        self._last_scale_down = datetime.min.replace(tzinfo=timezone.utc)

    def start(self):
        log.info("AutoScaler started (interval=%ss)", sla.CHECK_INTERVAL_SEC)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        log.info("AutoScaler stopped")

    def _loop(self):
        while not self._stop_event.wait(timeout=sla.CHECK_INTERVAL_SEC):
            if self.enabled:
                try:
                    self._check_and_scale()
                except Exception as e:
                    log.error("AutoScaler error: %s", e)

    def _check_and_scale(self):
        from api.database import SessionLocal
        from api.compute.models import VMInstance, VMMetric

        metrics = get_cluster_metrics()
        active = metrics["active_vms"]
        total = metrics["total_vms"]
        avg_cpu = metrics["avg_cpu_pct"]

        log.info("AutoScaler check — active=%d total=%d avg_cpu=%.1f%%", active, total, avg_cpu)

        # Record metrics for graphing
        db = SessionLocal()
        try:
            all_vms = list_all_vms()
            for vm_data in all_vms:
                if vm_data["state"] == "ACTIVE":
                    # Map OpenNebula VM to our local DB record
                    instance = db.query(VMInstance).filter(VMInstance.one_vm_id == vm_data["one_vm_id"]).first()
                    if instance:
                        metric = VMMetric(
                            vm_instance_id=instance.id,
                            cpu_usage_pct=vm_data["cpu_usage_pct"],
                            memory_mb=vm_data["memory_mb"]
                        )
                        db.add(metric)
            db.commit()
        except Exception as e:
            log.error("Failed to record metrics: %s", e)
        finally:
            db.close()

        # Scale UP
        now = datetime.now(timezone.utc)
        if avg_cpu > sla.SCALE_UP_CPU_PCT and total < sla.MAX_VMS:
            # Cooldown check: Wait at least 2 minutes between scale-ups
            if (now - self._last_scale_up).total_seconds() < 120:
                log.info("Scale UP requested but in COOLDOWN (%.1fs left)", 120 - (now - self._last_scale_up).total_seconds())
                return

            name = f"autoscale-vm-{int(now.timestamp())}"
            
            # Find the user who should own this VM (the one whose VMs are busy)
            target_user_id = None
            local_user_id = None
            all_vms = list_all_vms()
            for vm in all_vms:
                if vm["state"] == "ACTIVE" and vm["one_owner_id"] != 0: # Not oneadmin
                    target_user_id = vm["one_owner_id"]
                    # Get our local user_id from the DB
                    db = SessionLocal()
                    inst = db.query(VMInstance).filter(VMInstance.one_vm_id == vm["one_vm_id"]).first()
                    if inst:
                        local_user_id = inst.user_id
                    db.close()
                    break
            
            # If we found a user, create the VM for them
            one_vm_id = create_vm(name, sla.DEFAULT_TEMPLATE_ID, user_id=target_user_id)
            
            # Create the local DB record so they see it in the dashboard
            if local_user_id:
                db = SessionLocal()
                new_inst = VMInstance(
                    user_id=local_user_id,
                    one_vm_id=one_vm_id,
                    name=name,
                    template_id=sla.DEFAULT_TEMPLATE_ID
                )
                db.add(new_inst)
                db.commit()
                db.close()
                
            self._last_scale_up = now
            log.info("Scaled UP — created VM '%s' (one_vm_id=%d) for user_id=%s", name, one_vm_id, target_user_id)
            return

        # Scale DOWN — only consider autoscaler-managed VMs (never touch user VMs)
        if avg_cpu < sla.SCALE_DOWN_CPU_PCT and total > sla.MIN_VMS:
            # Only VMs created by the autoscaler are eligible for removal
            autoscale_vms = [
                vm for vm in all_vms
                if vm["state"] == "ACTIVE" and vm["name"].startswith(AUTOSCALE_PREFIX)
            ]

            for vm in autoscale_vms:
                vid = vm["one_vm_id"]
                if vm["cpu_usage_pct"] < sla.SCALE_DOWN_CPU_PCT:
                    if vid not in _idle_since:
                        _idle_since[vid] = now
                    # Testing window: 60 seconds of idle instead of 300
                    elif (now - _idle_since[vid]).total_seconds() >= 300:
                        destroy_vm(vid)
                        _idle_since.pop(vid, None)
                        self._last_scale_down = now
                        log.info("Scaled DOWN — destroyed autoscale VM one_vm_id=%d (idle >300s)", vid)
                        return
                else:
                    _idle_since.pop(vid, None)


# Singleton used by main.py
autoscaler = AutoScaler()
