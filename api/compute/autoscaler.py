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
        metrics = get_cluster_metrics()
        active = metrics["active_vms"]
        total = metrics["total_vms"]
        avg_cpu = metrics["avg_cpu_pct"]

        log.info("AutoScaler check — active=%d total=%d avg_cpu=%.1f%%", active, total, avg_cpu)

        now = datetime.now(timezone.utc)
        all_vms = list_all_vms()

        # 1. Record VM metrics for graphing
        self._record_metrics(all_vms)

        # 2. Maintain Pre-Warming (Hot Standby) Pool
        self._maintain_prewarming_pool(all_vms, total, now)

        # 3. Check for inactive users and suspend/resume their VMs
        self._manage_user_vms_inactivity(all_vms, now)

        # 4. Scale UP if criteria are met
        if self._scale_up(all_vms, total, avg_cpu, now):
            return

        # 5. Scale DOWN if criteria are met
        self._scale_down(all_vms, total, avg_cpu, now)

    def _record_metrics(self, all_vms):
        from api.database import SessionLocal
        from api.compute.models import VMInstance, VMMetric

        db = SessionLocal()
        try:
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

    def _maintain_prewarming_pool(self, all_vms, total, now):
        try:
            prewarmed_vms = [
                vm for vm in all_vms
                if vm["name"].startswith("prewarmed-vm-")
                and vm["state"] in ("ACTIVE", "PENDING")
            ]
            if len(prewarmed_vms) < 1 and total < sla.MAX_VMS:
                name = f"prewarmed-vm-{int(now.timestamp())}"
                # Create the VM under system/oneadmin (user_id=None)
                one_vm_id = create_vm(name, sla.DEFAULT_TEMPLATE_ID, user_id=None)
                log.info("Replenishing Pre-Warming Pool — created standby VM '%s' (one_vm_id=%d)", name, one_vm_id)
        except Exception as e:
            log.error("Failed to maintain pre-warming pool: %s", e)

    def _manage_user_vms_inactivity(self, all_vms, now):
        from api.database import SessionLocal
        from api.auth.models import User
        from api.compute.models import VMInstance
        from opennebula.vm_manager import suspend_vm, resume_vm

        db = SessionLocal()
        try:
            users = db.query(User).all()
            for user in users:
                if user.one_user_id is not None and user.last_active_at:
                    last_active = user.last_active_at
                    if last_active.tzinfo is None:
                        last_active = last_active.replace(tzinfo=timezone.utc)
                    
                    inactive_duration = (now - last_active).total_seconds()
                    if inactive_duration >= sla.USER_INACTIVITY_TIMEOUT_SEC:
                        # User is inactive! Check if they have active user VMs (not autoscale VMs)
                        user_vms = [
                            vm for vm in all_vms
                            if vm["one_owner_id"] == user.one_user_id 
                            and vm["state"] == "ACTIVE"
                            and not vm["name"].startswith(AUTOSCALE_PREFIX)
                        ]
                        for vm in user_vms:
                            log.info("Suspending VM '%s' (one_vm_id=%d) due to user '%s' inactivity (idle for %.1fs)", 
                                     vm["name"], vm["one_vm_id"], user.username, inactive_duration)
                            suspend_vm(vm["one_vm_id"])
                            # Mark in the DB that the system suspended this VM
                            inst = db.query(VMInstance).filter(VMInstance.one_vm_id == vm["one_vm_id"]).first()
                            if inst:
                                inst.suspended_by_system = True
                                db.commit()
                    else:
                        # User is active! Check if they have suspended user VMs that should be resumed
                        suspended_vms = [
                            vm for vm in all_vms
                            if vm["one_owner_id"] == user.one_user_id
                            and vm["state"] in ("SUSPENDED", "POWEROFF")
                        ]
                        for vm in suspended_vms:
                            # Only auto-resume if the system suspended it automatically
                            inst = db.query(VMInstance).filter(VMInstance.one_vm_id == vm["one_vm_id"]).first()
                            if inst and inst.suspended_by_system:
                                log.info("Resuming VM '%s' (one_vm_id=%d) because user '%s' is active",
                                         vm["name"], vm["one_vm_id"], user.username)
                                resume_vm(vm["one_vm_id"])
                                inst.suspended_by_system = False
                                db.commit()
        except Exception as e:
            log.error("Failed to manage user VMs state: %s", e)
        finally:
            db.close()

    def _scale_up(self, all_vms, total, avg_cpu, now) -> bool:
        """
        Attempts to scale up if criteria are met.
        Returns True if a scale-up was triggered or handled (even if in cooldown or fallback),
        meaning the caller should skip scale-down check.
        """
        if not (avg_cpu > sla.SCALE_UP_CPU_PCT and total < sla.MAX_VMS):
            return False

        # Cooldown check: Wait at least 2 minutes between scale-ups
        if (now - self._last_scale_up).total_seconds() < 120:
            log.info("Scale UP requested but in COOLDOWN (%.1fs left)", 120 - (now - self._last_scale_up).total_seconds())
            return True

        name = f"autoscale-vm-{int(now.timestamp())}"
        
        # Find the user who should own this VM (the one whose VMs are busy)
        target_user_id = None
        local_user_id = None
        
        # Group active user VMs by owner and find the one with the highest average CPU usage
        user_cpu_sums = {}
        user_cpu_counts = {}
        user_local_ids = {}
        
        from api.database import SessionLocal
        from api.compute.models import VMInstance

        db = SessionLocal()
        try:
            for vm in all_vms:
                if vm["state"] == "ACTIVE" and vm["one_owner_id"] != 0:
                    inst = db.query(VMInstance).filter(VMInstance.one_vm_id == vm["one_vm_id"]).first()
                    if inst:
                        owner_id = vm["one_owner_id"]
                        user_cpu_sums[owner_id] = user_cpu_sums.get(owner_id, 0.0) + vm["cpu_usage_pct"]
                        user_cpu_counts[owner_id] = user_cpu_counts.get(owner_id, 0) + 1
                        user_local_ids[owner_id] = inst.user_id
            
            busiest_owner_id = None
            highest_avg_cpu = -1.0
            for owner_id, cpu_sum in user_cpu_sums.items():
                avg = cpu_sum / user_cpu_counts[owner_id]
                if avg > highest_avg_cpu:
                    highest_avg_cpu = avg
                    busiest_owner_id = owner_id
            
            if busiest_owner_id is not None:
                target_user_id = busiest_owner_id
                local_user_id = user_local_ids[busiest_owner_id]
            else:
                # Fallback to the most recently active user
                from api.auth.models import User
                newest_active_user = db.query(User).filter(User.one_user_id != None).order_by(User.last_active_at.desc()).first()
                if newest_active_user:
                    target_user_id = newest_active_user.one_user_id
                    local_user_id = newest_active_user.id
        except Exception as e:
            log.error("Error determining target user for autoscale: %s", e)
        finally:
            db.close()
        
        if target_user_id is not None:
            one_vm_id = create_vm(name, sla.DEFAULT_TEMPLATE_ID, user_id=target_user_id)
            db = SessionLocal()
            try:
                new_inst = VMInstance(
                    user_id=local_user_id,
                    one_vm_id=one_vm_id,
                    name=name,
                    template_id=sla.DEFAULT_TEMPLATE_ID
                )
                db.add(new_inst)
                db.commit()
            except Exception as e:
                log.error("Failed to save autoscaled VMInstance to DB: %s", e)
            finally:
                db.close()
                
            self._last_scale_up = now
            log.info("Scaled UP — created VM '%s' (one_vm_id=%d) for user_id=%s", name, one_vm_id, target_user_id)
        else:
            log.warning("Scale UP failed: No active/fallback user found to assign the new VM.")
        
        return True

    def _scale_down(self, all_vms, total, avg_cpu, now):
        """
        Attempts to scale down if criteria are met.
        """
        if not (avg_cpu < sla.SCALE_DOWN_CPU_PCT and total > sla.MIN_VMS):
            return

        from api.database import SessionLocal
        from api.compute.models import VMInstance

        # Only VMs created by the autoscaler are eligible for removal
        autoscale_vms = [
            vm for vm in all_vms
            if vm["state"] == "ACTIVE" and vm["name"].startswith(AUTOSCALE_PREFIX)
        ]

        for vm in autoscale_vms:
            vid = vm["one_vm_id"]
            if vm["cpu_usage_pct"] < sla.SCALE_DOWN_CPU_PCT:
                # Drain check: verify if the VM is hosting any containers
                ip = vm.get("ip_address")
                if not ip or ip == "—":
                    # Skip if VM is not fully booted or has no IP address
                    continue

                has_containers = False
                try:
                    import docker
                    from opennebula.vm_manager import get_ssh_user_by_template
                    ssh_user = "root"
                    db_sess = SessionLocal()
                    try:
                        inst = db_sess.query(VMInstance).filter(VMInstance.one_vm_id == vid).first()
                        if inst:
                            ssh_user = get_ssh_user_by_template(inst.template_id)
                    finally:
                        db_sess.close()

                    cli = docker.DockerClient(base_url=f"ssh://{ssh_user}@{ip}", use_ssh_client=True, timeout=3)
                    containers = cli.containers.list(all=True)
                    if len(containers) > 0:
                        has_containers = True
                    cli.close()
                    cli.api.adapters.clear()
                except Exception as e:
                    log.warning("Could not connect to VM %d to check containers: %s", vid, e)
                    has_containers = True  # Safe fallback: do not destroy

                if has_containers:
                    # Reset idle tracking since it is not actually idle/empty
                    _idle_since.pop(vid, None)
                    continue

                if vid not in _idle_since:
                    _idle_since[vid] = now
                elif (now - _idle_since[vid]).total_seconds() >= sla.SCALE_DOWN_WINDOW_SEC:
                    destroy_vm(vid)
                    _idle_since.pop(vid, None)
                    self._last_scale_down = now
                    
                    # Update DB record to mark VM as terminated
                    db = SessionLocal()
                    try:
                        inst = db.query(VMInstance).filter(VMInstance.one_vm_id == vid).first()
                        if inst:
                            inst.terminated_at = now
                            db.commit()
                    except Exception as e:
                        log.error("Failed to mark autoscale VM as terminated in DB: %s", e)
                    finally:
                        db.close()

                    log.info("Scaled DOWN — destroyed autoscale VM one_vm_id=%d (idle >%ds)", vid, sla.SCALE_DOWN_WINDOW_SEC)
                    return
            else:
                _idle_since.pop(vid, None)


# Singleton used by main.py
autoscaler = AutoScaler()
