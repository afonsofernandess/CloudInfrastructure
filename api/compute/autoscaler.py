"""
Auto-scaler background thread.

Runs every CHECK_INTERVAL_SEC seconds and applies the SLA policy:
- If avg CPU > SCALE_UP_CPU_PCT and total VMs < MAX_VMS  → spin up a new VM
- If avg CPU < SCALE_DOWN_CPU_PCT and total VMs > MIN_VMS → tear down the oldest idle VM

Started and stopped via FastAPI's lifespan in main.py.
"""

import sqlite3
import threading
import logging
import time
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

# Tracks VMs that were just resumed so we can recover their Docker services
# once they finish booting.  one_vm_id → resume_timestamp
_recently_resumed: dict[int, datetime] = {}


def queue_vm_for_recovery(one_vm_id: int) -> None:
    """Queue a VM to recover its Docker containers and ports once fully booted."""
    _recently_resumed[one_vm_id] = datetime.now(timezone.utc)
    log.info("[RECOVERY] VM %d queued for post-resume service recovery.", one_vm_id)


def _get_db_path() -> str:
    """Return the filesystem path to the SQLite database file."""
    from api.database import engine
    return engine.url.database


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

        # 0. Check if any recently-resumed VMs are now fully booted and need service recovery
        self._process_pending_recoveries(all_vms, now)

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
                one_vm_id = create_vm(name, sla.DEFAULT_TEMPLATE_ID, user_id=None, disk_gb=4)
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
                                # Track this VM for post-boot service recovery
                                queue_vm_for_recovery(vm["one_vm_id"])
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
            # Pre-warming optimization: claim a pre-warmed standby VM if available
            prewarmed_vm = None
            db = SessionLocal()
            try:
                for vm in all_vms:
                    if vm["name"].startswith("prewarmed-vm-") and vm["state"] == "ACTIVE" and vm.get("lcm_state") == 3:
                        # Make sure it isn't already registered as active in our DB
                        inst_check = db.query(VMInstance).filter(VMInstance.one_vm_id == vm["one_vm_id"]).first()
                        if not inst_check or inst_check.terminated_at is not None:
                            prewarmed_vm = vm
                            break
            except Exception as e:
                log.error("Failed to search for pre-warmed VMs in autoscale: %s", e)
            finally:
                db.close()

            one_vm_id = None
            if prewarmed_vm:
                try:
                    one_vm_id = prewarmed_vm["one_vm_id"]
                    # Claim in OpenNebula: rename and change ownership
                    from opennebula.connection import get_client
                    client = get_client()
                    client.vm.rename(one_vm_id, name)
                    client.vm.chown(one_vm_id, target_user_id, -1)
                    log.info("Successfully claimed pre-warmed VM '%s' (one_vm_id=%d) for autoscale (user_id=%s)", name, one_vm_id, target_user_id)
                except Exception as e:
                    log.error("Failed to claim pre-warmed VM in autoscale, falling back to full creation: %s", e)
                    prewarmed_vm = None

            if not prewarmed_vm:
                # Fall back to standard on-demand creation
                one_vm_id = create_vm(name, sla.DEFAULT_TEMPLATE_ID, user_id=target_user_id, disk_gb=4)
                log.info("Scaled UP — created VM '%s' (one_vm_id=%d) from scratch for user_id=%s", name, one_vm_id, target_user_id)

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


    # ─────────────────────────────────────────────────────────────
    # Post-resume auto-recovery
    # ─────────────────────────────────────────────────────────────

    def _process_pending_recoveries(self, all_vms: list, now: datetime) -> None:
        """
        Called every autoscaler cycle.  For each VM that was recently resumed,
        check whether it has finished booting (ACTIVE + LCM=3).  If so, kick
        off the service-recovery routine and remove it from the pending set.
        VMs that take longer than 5 minutes to boot are dropped silently.
        """
        done = []
        for one_vm_id, resume_time in list(_recently_resumed.items()):
            # Give up after 5 minutes
            if (now - resume_time).total_seconds() > 300:
                log.warning("[RECOVERY] VM %d recovery timed out (>5 min) — dropping.", one_vm_id)
                done.append(one_vm_id)
                continue

            vm_info = next((v for v in all_vms if v["one_vm_id"] == one_vm_id), None)
            if vm_info and vm_info["state"] == "ACTIVE" and vm_info.get("lcm_state") == 3:
                ip = vm_info.get("ip_address", "")
                if ip and ip != "—":
                    log.info("[RECOVERY] VM %d (%s) is RUNNING — starting service recovery.", one_vm_id, ip)
                    try:
                        self._recover_db_services_on_vm(ip, one_vm_id)
                    except Exception as exc:
                        log.error("[RECOVERY] VM %d recovery error: %s", one_vm_id, exc)
                    done.append(one_vm_id)

        for vid in done:
            _recently_resumed.pop(vid, None)

    def _recover_db_services_on_vm(self, vm_ip: str, one_vm_id: int) -> None:
        """
        Full post-resume recovery for a single VM:

        1. Detect stopped Docker containers (exit 255 = host rebooted).
        2. Start them and wait for their ports to bind.
        3. Read new dynamic port assignments from Docker.
        4. Update SQLite db_instances with the new ports.
        5. For each affected DB cluster:
           a. Rebuild and reload the HAProxy config.
           b. Fix replica WAL primary_conninfo so streaming reconnects.
        """
        from api.loadbalancer.ssh_utils import run_ssh_command, write_ssh_file

        log.info("[RECOVERY] VM %s — starting post-resume service recovery.", vm_ip)

        # ── Step 1: find stopped containers ──────────────────────────────
        try:
            out = run_ssh_command(
                vm_ip,
                'docker ps -a --filter "status=exited" --format "{{.Names}}"'
            )
            stopped = [n.strip() for n in out.strip().splitlines() if n.strip()]
        except Exception as exc:
            log.warning("[RECOVERY] VM %s — cannot query containers: %s", vm_ip, exc)
            return

        if not stopped:
            log.info("[RECOVERY] VM %s — no stopped containers found.", vm_ip)
            return

        log.info("[RECOVERY] VM %s — restarting: %s", vm_ip, stopped)

        # ── Step 2: start them ───────────────────────────────────────────
        try:
            run_ssh_command(vm_ip, "docker start " + " ".join(stopped))
        except Exception as exc:
            log.error("[RECOVERY] VM %s — docker start failed: %s", vm_ip, exc)
            return

        time.sleep(5)  # wait for ports to bind

        # ── Step 3: read new port bindings ───────────────────────────────
        # port_info: { container_name -> { "5432": host_port, "5433": host_port } }
        port_info: dict[str, dict[str, int]] = {}
        for cname in stopped:
            try:
                raw = run_ssh_command(vm_ip, f"docker port {cname} 2>/dev/null")
                mapping: dict[str, int] = {}
                for line in raw.strip().splitlines():
                    # e.g.  "5432/tcp -> 0.0.0.0:32768"
                    if "->" in line:
                        left, right = line.split("->")
                        cport = left.strip().split("/")[0]  # "5432"
                        hport = int(right.strip().split(":")[-1])
                        mapping[cport] = hport
                if mapping:
                    port_info[cname] = mapping
            except Exception as exc:
                log.warning("[RECOVERY] VM %s — could not get port for %s: %s", vm_ip, cname, exc)

        log.info("[RECOVERY] VM %s — detected port mappings: %s", vm_ip, port_info)

        # ── Step 4: update SQLite ─────────────────────────────────────────
        db_path = _get_db_path()
        affected_clusters: set[str] = set()
        primary_port_changed: dict[str, int] = {}  # cluster_name -> new primary port

        try:
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            rows = cur.execute(
                "SELECT id, instance_name, role, cluster_name FROM db_instances"
            ).fetchall()

            for cname, ports in port_info.items():
                for row_id, inst_name, role, cluster_name in rows:
                    # Container naming: "db-{username}-{inst_name}"
                    if not cname.endswith(f"-{inst_name}"):
                        continue

                    if role == "load_balancer":
                        write_p = ports.get("5432")
                        read_p  = ports.get("5433")
                        if write_p:
                            cur.execute("UPDATE db_instances SET host_port=? WHERE id=?",
                                        (write_p, row_id))
                            log.info("[RECOVERY] %s (lb) write port -> %d", inst_name, write_p)
                        if read_p:
                            cur.execute("UPDATE db_instances SET read_host_port=? WHERE id=?",
                                        (read_p, row_id))
                            log.info("[RECOVERY] %s (lb) read port -> %d", inst_name, read_p)
                    else:
                        pg_p = ports.get("5432")
                        if pg_p:
                            cur.execute("UPDATE db_instances SET host_port=? WHERE id=?",
                                        (pg_p, row_id))
                            log.info("[RECOVERY] %s (%s) port -> %d", inst_name, role, pg_p)
                            if role == "primary" and cluster_name:
                                primary_port_changed[cluster_name] = pg_p

                    if cluster_name:
                        affected_clusters.add(cluster_name)
                    break

            con.commit()
            con.close()
        except Exception as exc:
            log.error("[RECOVERY] VM %s — SQLite update failed: %s", vm_ip, exc)
            return

        # ── Step 5a: rebuild HAProxy config for each affected cluster ─────
        for cluster in affected_clusters:
            try:
                self._rebuild_haproxy_for_cluster(cluster, db_path, vm_ip)
            except Exception as exc:
                log.error("[RECOVERY] HAProxy rebuild failed for cluster '%s': %s", cluster, exc)

        # ── Step 5b: fix WAL replica primary_conninfo ──────────────────
        for cluster, new_primary_port in primary_port_changed.items():
            try:
                self._fix_replica_wal_conninfo(cluster, new_primary_port, vm_ip, db_path)
            except Exception as exc:
                log.error("[RECOVERY] WAL conninfo fix failed for cluster '%s': %s", cluster, exc)

        log.info("[RECOVERY] VM %s — recovery complete. Clusters affected: %s",
                 vm_ip, affected_clusters or "none")

    def _rebuild_haproxy_for_cluster(
        self, cluster_name: str, db_path: str, lb_vm_ip: str
    ) -> None:
        """
        Re-read all current ports from SQLite for `cluster_name`, write a
        fresh haproxy.cfg to the LB VM, and send SIGHUP to reload it.
        """
        from api.loadbalancer.ssh_utils import run_ssh_command, write_ssh_file

        con = sqlite3.connect(db_path)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT instance_name, role, host_port, read_host_port "
            "FROM db_instances WHERE cluster_name=?",
            (cluster_name,)
        ).fetchall()
        con.close()

        primary_row = next((r for r in rows if r[1] == "primary"), None)
        replica_rows = [r for r in rows if r[1] == "replica"]

        if not primary_row:
            log.warning("[RECOVERY] Cluster '%s': no primary found — skipping HAProxy rebuild.",
                        cluster_name)
            return

        # Build replica backend lines using their VM IPs
        replica_cfg = ""
        for r in replica_rows:
            # Find which VM hosts this replica container
            r_ip = self._find_container_vm_ip(f"-{r[0]}")  # ends with inst_name
            if not r_ip:
                r_ip = lb_vm_ip  # fallback: same VM
            replica_cfg += f"    server db-{r[0]} {r_ip}:{r[2]} check\n"

        haproxy_cfg = (
            "global\n"
            "    log stdout format raw local0\n"
            "    nbthread 1\n"
            "    maxconn 100\n"
            "\n"
            "defaults\n"
            "    log     global\n"
            "    mode    tcp\n"
            "    maxconn 50\n"
            "    timeout connect 5s\n"
            "    timeout client  50s\n"
            "    timeout server  50s\n"
            "\n"
            "frontend postgres_write_front\n"
            "    bind *:5432\n"
            "    default_backend postgres_primary\n"
            "\n"
            "backend postgres_primary\n"
            "    mode tcp\n"
            "    option tcp-check\n"
            f"    server db-primary {lb_vm_ip}:{primary_row[2]} check\n"
            "\n"
            "frontend postgres_read_front\n"
            "    bind *:5433\n"
            "    default_backend postgres_replicas\n"
            "\n"
            "backend postgres_replicas\n"
            "    mode tcp\n"
            "    balance roundrobin\n"
            "    option tcp-check\n"
            f"    server db-primary {lb_vm_ip}:{primary_row[2]} check\n"
            f"{replica_cfg}"
        )

        cfg_path = f"/var/lib/haproxy-{cluster_name}/haproxy.cfg"
        write_ssh_file(lb_vm_ip, cfg_path, haproxy_cfg)
        log.info("[RECOVERY] Wrote new HAProxy config for cluster '%s'.", cluster_name)

        # Find the HAProxy container name and SIGHUP it
        try:
            out = run_ssh_command(
                lb_vm_ip,
                f'docker ps --filter "name={cluster_name}-lb" --format "{{{{.Names}}}}"'
            )
            lb_cname = next(
                (n.strip() for n in out.strip().splitlines() if cluster_name in n and "lb" in n),
                None
            )
            if lb_cname:
                run_ssh_command(lb_vm_ip, f"docker kill -s HUP {lb_cname}")
                log.info("[RECOVERY] HAProxy reloaded (SIGHUP) for cluster '%s'.", cluster_name)
            else:
                log.warning("[RECOVERY] HAProxy container not found for cluster '%s'.", cluster_name)
        except Exception as exc:
            log.warning("[RECOVERY] HAProxy SIGHUP failed for cluster '%s': %s", cluster_name, exc)

    def _fix_replica_wal_conninfo(
        self, cluster_name: str, new_primary_port: int, primary_vm_ip: str, db_path: str
    ) -> None:
        """
        For every replica in `cluster_name`, run:
          ALTER SYSTEM SET primary_conninfo = '...';
          SELECT pg_reload_conf();
        so WAL streaming reconnects to the primary's new port.
        """
        from api.loadbalancer.ssh_utils import run_ssh_command

        new_conninfo = (
            f"user=replicator password=replicasecret "
            f"host={primary_vm_ip} port={new_primary_port} sslmode=prefer"
        )

        con = sqlite3.connect(db_path)
        cur = con.cursor()
        replicas = cur.execute(
            "SELECT instance_name, db_user, db_password, db_name "
            "FROM db_instances WHERE cluster_name=? AND role='replica'",
            (cluster_name,)
        ).fetchall()
        con.close()

        for inst_name, db_user, db_password, db_name in replicas:
            replica_vm_ip = self._find_container_vm_ip(f"-{inst_name}")
            if not replica_vm_ip:
                log.warning("[RECOVERY] Cannot find VM for replica '%s' — skipping WAL fix.",
                            inst_name)
                continue
            try:
                container_name_fragment = inst_name  # e.g. "test-db-lb-replica-1"
                # Get the full container name from docker ps
                out = run_ssh_command(
                    replica_vm_ip,
                    f'docker ps --filter "name={container_name_fragment}" --format "{{{{.Names}}}}"'
                )
                cname = next(
                    (n.strip() for n in out.strip().splitlines() if container_name_fragment in n),
                    None
                )
                if not cname:
                    log.warning("[RECOVERY] Replica container '%s' not running — skipping.",
                                inst_name)
                    continue

                psql_prefix = (
                    f"docker exec -e PGPASSWORD='{db_password}' {cname} "
                    f"psql -U {db_user} -d {db_name}"
                )
                run_ssh_command(
                    replica_vm_ip,
                    f"{psql_prefix} -c \"ALTER SYSTEM SET primary_conninfo = '{new_conninfo}';\""
                )
                run_ssh_command(
                    replica_vm_ip,
                    f"{psql_prefix} -c \"SELECT pg_reload_conf();\""
                )
                log.info(
                    "[RECOVERY] Replica '%s' WAL conninfo updated → port %d.",
                    inst_name, new_primary_port
                )
            except Exception as exc:
                log.error("[RECOVERY] WAL conninfo update failed for replica '%s': %s",
                          inst_name, exc)

    def _find_container_vm_ip(self, container_name_suffix: str) -> str | None:
        """
        Scan all ACTIVE OpenNebula VMs and return the IP of the first one
        that has a Docker container whose name ends with `container_name_suffix`.
        Returns None if no match is found.
        """
        from api.loadbalancer.ssh_utils import run_ssh_command

        try:
            all_vms = list_all_vms()
        except Exception:
            return None

        for vm in all_vms:
            if vm["state"] != "ACTIVE" or vm.get("lcm_state") != 3:
                continue
            ip = vm.get("ip_address", "")
            if not ip or ip == "—":
                continue
            try:
                out = run_ssh_command(
                    ip,
                    f'docker ps --filter "name={container_name_suffix}" '
                    f'--format "{{{{.Names}}}}" 2>/dev/null'
                )
                for name in out.strip().splitlines():
                    if container_name_suffix.lstrip("-") in name:
                        return ip
            except Exception:
                continue
        return None


# Singleton used by main.py
autoscaler = AutoScaler()
