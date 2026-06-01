import time
import threading
import logging
from datetime import datetime, timezone

from api.database import SessionLocal
from api.auth.models import User
from api.containers.docker_client import get_all_clients
from api.loadbalancer.container_lb import scale_container_group
from api.loadbalancer.schemas import ContainerScaleRequest

# Configure Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("container_autoscaler")
log.setLevel(logging.INFO)

# Default configuration parameters
CHECK_INTERVAL_SEC = 15       # Run check every 15 seconds
CPU_HIGH_THRESHOLD = 70.0     # Scale up if average CPU usage exceeds 70.0%
CPU_LOW_THRESHOLD = 15.0      # Scale down if average CPU usage falls below 15.0%
MIN_REPLICAS = 1
MAX_REPLICAS = 4
COOLDOWN_SEC = 45            # Minimum seconds between scaling actions for a group

class ContainerAutoScaler:
    def __init__(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._stop_event = threading.Event()
        self.enabled = True
        self._last_scale_time = {}  # Track cooldown per scale group: group_name -> timestamp

    def start(self):
        log.info("ContainerAutoScaler starting (interval=%ss)", CHECK_INTERVAL_SEC)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        log.info("ContainerAutoScaler stopped")

    def _loop(self):
        while not self._stop_event.wait(timeout=CHECK_INTERVAL_SEC):
            if self.enabled:
                try:
                    self._check_and_scale()
                except Exception as e:
                    log.error("ContainerAutoScaler error: %s", e, exc_info=True)

    def _calculate_cpu_usage(self, container) -> float:
        """Calculate CPU usage percent for a docker container."""
        try:
            stats = container.stats(stream=False)
            cpu_stats = stats.get('cpu_stats', {})
            precpu_stats = stats.get('precpu_stats', {})
            
            if cpu_stats and precpu_stats:
                cpu_total = cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                precpu_total = precpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                
                system_cpu = cpu_stats.get('system_cpu_usage', 0)
                pre_system_cpu = precpu_stats.get('system_cpu_usage', 0)
                
                cpu_delta = cpu_total - precpu_total
                system_delta = system_cpu - pre_system_cpu
                
                if system_delta > 0.0 and cpu_delta > 0.0:
                    cpu_cores = cpu_stats.get('online_cpus') or len(cpu_stats.get('cpu_usage', {}).get('percpu_usage', [])) or 1
                    cpu_percent = (cpu_delta / system_delta) * cpu_cores * 100.0
                    return round(cpu_percent, 1)
        except Exception:
            pass
        return 0.0

    def _check_and_scale(self):
        db = SessionLocal()
        try:
            users = db.query(User).all()
        finally:
            db.close()

        # Dictionary to store detected worker groups:
        # group_name -> {
        #   'username': str,
        #   'workers': list[(client, container_id, container_name)],
        #   'image': str,
        #   'container_port': str,
        #   'env': dict
        # }
        groups = {}

        # 1. Discover all active container scale groups across all users/VMs
        for user in users:
            clients = get_all_clients(user.username)
            for vm_id, client in clients:
                try:
                    containers = client.containers.list(all=True)
                    for c in containers:
                        labels = c.labels
                        group_name = labels.get("scale_group")
                        role = labels.get("role")
                        
                        if group_name and role == "worker":
                            if group_name not in groups:
                                # Retrieve container image name
                                image = c.image.tags[0] if c.image.tags else c.attrs.get("Config", {}).get("Image", "nginx:alpine")
                                port = labels.get("container_port", "80/tcp")
                                
                                # Parse env vars from existing container
                                env = {}
                                for item in c.attrs.get("Config", {}).get("Env", []):
                                    if "=" in item:
                                        k, v = item.split("=", 1)
                                        if k not in ("PATH", "HOME", "HOSTNAME", "PWD", "TERM"):
                                            env[k] = v

                                groups[group_name] = {
                                    'username': user.username,
                                    'workers': [],
                                    'image': image,
                                    'container_port': port,
                                    'env': env
                                }
                            
                            # Add container to group
                            groups[group_name]['workers'].append((c, vm_id))
                except Exception as e:
                    log.error("Failed to scan VM %s for user %s: %s", vm_id, user.username, e)
                finally:
                    # We close the client connections to release socket resources
                    try:
                        client.close()
                    except Exception:
                        pass

        # 2. For each discovered scale group, check CPU metrics and scale if needed
        now = time.time()
        for group_name, info in groups.items():
            username = info['username']
            workers = info['workers']
            current_count = len(workers)
            
            if current_count == 0:
                continue

            # Check if this group is in cooldown
            last_scale = self._last_scale_time.get(group_name, 0)
            if now - last_scale < COOLDOWN_SEC:
                log.debug("Container group '%s' is in cooldown.", group_name)
                continue

            # Fetch CPU percentages for all worker containers in the group
            cpu_usages = []
            
            # Since we closed the main clients, we quickly connect to fetch stats
            # or do it sequentially.
            # To fetch stats, we create a temp client for the worker's VM.
            for c, vm_id in workers:
                from api.containers.docker_client import get_client
                try:
                    temp_cli = get_client(username, vm_id)
                    try:
                        live_c = temp_cli.containers.get(c.id)
                        if live_c.status == "running":
                            cpu = self._calculate_cpu_usage(live_c)
                            cpu_usages.append(cpu)
                        else:
                            cpu_usages.append(0.0)
                    finally:
                        temp_cli.close()
                except Exception as e:
                    log.warning("Failed to fetch CPU stats for container %s on VM %s: %s", c.id[:12], vm_id, e)
                    cpu_usages.append(0.0)

            avg_cpu = sum(cpu_usages) / len(cpu_usages) if cpu_usages else 0.0
            log.info("ContainerAutoscale monitor for '%s' (%s) — replicas=%d avg_cpu=%.1f%%", 
                     group_name, username, current_count, avg_cpu)

            # Determine scaling action
            direction = None
            if avg_cpu > CPU_HIGH_THRESHOLD and current_count < MAX_REPLICAS:
                direction = "up"
            elif avg_cpu < CPU_LOW_THRESHOLD and current_count > MIN_REPLICAS:
                direction = "down"

            if direction:
                target_count = current_count + 1 if direction == "up" else current_count - 1
                log.info("ContainerAutoscale scaling %s for '%s' from %d to %d replicas (avg CPU: %.1f%%)...",
                         direction.upper(), group_name, current_count, target_count, avg_cpu)
                
                try:
                    req = ContainerScaleRequest(
                        name=group_name,
                        image=info['image'],
                        replicas=target_count,
                        container_port=info['container_port'],
                        env=info['env']
                    )
                    scale_container_group(username, req)
                    self._last_scale_time[group_name] = now
                    log.info("[SUCCESS] ContainerAutoscale scaled %s completed for '%s'!", direction.upper(), group_name)
                except Exception as ex:
                    log.error("[FAIL] ContainerAutoscale scaling failed for '%s': %s", group_name, ex)

# Singleton container autoscaler
container_autoscaler = ContainerAutoScaler()
