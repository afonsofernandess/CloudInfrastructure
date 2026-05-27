"""
Docker client wrapper.
Containers are labelled with cloud_user=<username> for per-user isolation.
All container operations filter by this label so users never see each other's containers.
"""

import docker
from docker.errors import NotFound, APIError
from typing import Optional

LABEL_KEY = "cloud_user"


def self_heal_docker(ip: str, ssh_user: str = "root") -> None:
    """Attempt to install or start Docker over SSH as a safety net/self-healing fallback."""
    import os
    import paramiko
    from dotenv import load_dotenv

    load_dotenv()
    gw_ip = os.getenv("GATEWAY_IP")
    gw_port = int(os.getenv("GATEWAY_PORT", "22"))
    gw_user = os.getenv("GATEWAY_USER")
    gw_pass = os.getenv("GATEWAY_PASSWORD")

    if not gw_ip or not gw_user:
        print(f"DEBUG [Self-Heal]: Gateway configuration missing, skipping self-heal for {ip}")
        return

    gateway_client = paramiko.SSHClient()
    gateway_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    vm_client = paramiko.SSHClient()
    vm_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        print(f"DEBUG [Self-Heal]: Connecting to SSH gateway {gw_user}@{gw_ip}:{gw_port}...")
        gateway_client.connect(gw_ip, port=gw_port, username=gw_user, password=gw_pass, timeout=10)
        
        transport = gateway_client.get_transport()
        vm_channel = transport.open_channel("direct-tcpip", (ip, 22), (gw_ip, 0))
        
        home = os.path.expanduser("~")
        possible_keys = [
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".ssh", "id_dsa"),
        ]
        
        print(f"DEBUG [Self-Heal]: Connecting to VM {ip} via tunnel as user '{ssh_user}'...")
        vm_client.connect(
            ip,
            username=ssh_user,
            sock=vm_channel,
            timeout=10,
            key_filename=[k for k in possible_keys if os.path.exists(k)],
            allow_agent=True
        )
        
        if ssh_user == "ubuntu":
            # Check if docker daemon is running on Ubuntu
            stdin, stdout, stderr = vm_client.exec_command("systemctl is-active docker")
            is_active = stdout.read().decode().strip() == "active"
            
            if not is_active:
                print(f"DEBUG [Self-Heal]: Docker not started on Ubuntu VM {ip}. Attempting to start...")
                stdin, stdout, stderr = vm_client.exec_command("which docker")
                has_docker = bool(stdout.read().decode().strip())
                
                if not has_docker:
                    print(f"DEBUG [Self-Heal]: Docker not installed on Ubuntu {ip}. Installing...")
                    vm_client.exec_command("sudo rm -f /etc/resolv.conf && sudo sh -c 'echo \"nameserver 8.8.8.8\" > /etc/resolv.conf' && sudo sh -c 'echo \"nameserver 1.1.1.1\" >> /etc/resolv.conf'")
                    stdin, stdout, stderr = vm_client.exec_command("sudo apt-get update -y && sudo apt-get install -y docker.io && sudo systemctl enable docker && sudo systemctl start docker && sudo usermod -aG docker ubuntu")
                    stdout.read() # wait for execution
                else:
                    stdin, stdout, stderr = vm_client.exec_command("sudo systemctl start docker")
                    stdout.read()
            else:
                print(f"DEBUG [Self-Heal]: Docker is already reported as active on Ubuntu VM {ip}.")
        else:
            # Check if docker daemon is running on Alpine (root)
            stdin, stdout, stderr = vm_client.exec_command("service docker status")
            status_out = stdout.read().decode().strip()
            
            if "started" not in status_out:
                print(f"DEBUG [Self-Heal]: Docker not started on Alpine VM {ip}. Status: '{status_out}'. Attempting to start...")
                
                # Check if docker binary exists
                stdin, stdout, stderr = vm_client.exec_command("which docker")
                has_docker = bool(stdout.read().decode().strip())
                
                if not has_docker:
                    print(f"DEBUG [Self-Heal]: Docker binary not found on Alpine {ip}. Installing...")
                    vm_client.exec_command("rm -f /etc/resolv.conf && echo 'nameserver 8.8.8.8' > /etc/resolv.conf && echo 'nameserver 1.1.1.1' >> /etc/resolv.conf")
                    # Run installation commands
                    stdin, stdout, stderr = vm_client.exec_command("apk update && apk add docker && rc-update add docker default && service docker start")
                    stdout.read() # wait for execution
                else:
                    stdin, stdout, stderr = vm_client.exec_command("service docker start")
                    stdout.read()
            else:
                print(f"DEBUG [Self-Heal]: Docker is already reported as started on Alpine VM {ip}.")
    except Exception as e:
        print(f"DEBUG [Self-Heal]: Self-healing failed for {ip}: {e}")
    finally:
        vm_client.close()
        gateway_client.close()



def get_client(username: str, vm_id: Optional[int] = None) -> docker.DockerClient:
    """Return a Docker client connected to the user's specified VM or first active VM via SSH."""
    from api.database import SessionLocal
    from api.auth.models import User
    from api.compute.models import VMInstance
    from opennebula.vm_manager import get_vm

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise RuntimeError(f"User '{username}' not found in database")

        if vm_id is not None:
            # Look up specific VM
            inst = db.query(VMInstance).filter(
                VMInstance.id == vm_id,
                VMInstance.user_id == user.id,
                VMInstance.terminated_at == None
            ).first()
            if not inst:
                raise RuntimeError(f"Active VM with ID {vm_id} not found for user '{username}'")
            instances = [inst]
        else:
            # Find active (non-terminated) VMs for this user
            instances = db.query(VMInstance).filter(
                VMInstance.user_id == user.id,
                VMInstance.terminated_at == None
            ).all()

        for inst in instances:
            try:
                live = get_vm(inst.one_vm_id)
                # Check if it is running and has an IP address
                if live["state"] == "ACTIVE" and live["lcm_state"] == 3: # 3 = RUNNING
                    ip = live.get("ip_address")
                    if ip and ip != "—":
                        from opennebula.vm_manager import get_ssh_user_by_template
                        ssh_user = get_ssh_user_by_template(inst.template_id)
                        return docker.DockerClient(base_url=f"ssh://{ssh_user}@{ip}", use_ssh_client=True)
            except Exception:
                continue

        if vm_id is not None:
            raise RuntimeError(f"VM ID {vm_id} is not currently running or accessible.")
        else:
            raise RuntimeError(f"No active and running VMs found for user '{username}'. Please provision a VM first.")
    finally:
        db.close()


def get_all_clients(username: str) -> list[tuple[int, docker.DockerClient]]:
    """Return a list of (vm_instance_id, docker_client) tuples for all active VMs of the user."""
    from api.database import SessionLocal
    from api.auth.models import User
    from api.compute.models import VMInstance
    from opennebula.vm_manager import get_vm, get_ssh_user_by_template

    db = SessionLocal()
    clients = []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        instances = db.query(VMInstance).filter(
            VMInstance.user_id == user.id,
            VMInstance.terminated_at == None
        ).all()
        for inst in instances:
            try:
                live = get_vm(inst.one_vm_id)
                if live["state"] == "ACTIVE" and live["lcm_state"] == 3:
                    ip = live.get("ip_address")
                    if ip and ip != "—":
                        ssh_user = get_ssh_user_by_template(inst.template_id)
                        cli = docker.DockerClient(base_url=f"ssh://{ssh_user}@{ip}", use_ssh_client=True)
                        clients.append((inst.id, cli))
            except Exception:
                continue
        return clients
    finally:
        db.close()


def container_label(username: str) -> dict:
    return {LABEL_KEY: username}


def ensure_user_has_running_vm(username: str, vm_id: Optional[int] = None) -> int:
    """
    Ensure the user has an active and fully booted VM.
    If a VM is suspended/powered-off, it resumes it.
    If no VM exists, it provisions a new one.
    Blocks (with timeout) until LCM_STATE is RUNNING (3) and returns the VMInstance.id.
    """
    import time
    from datetime import datetime, timezone
    from api.database import SessionLocal
    from api.auth.models import User
    from api.compute.models import VMInstance
    from opennebula.vm_manager import get_vm, resume_vm, create_vm
    from api.compute import sla

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise RuntimeError(f"User '{username}' not found in database")

        target_inst = None
        if vm_id is not None:
            # Check the specific VM requested
            target_inst = db.query(VMInstance).filter(
                VMInstance.id == vm_id,
                VMInstance.user_id == user.id,
                VMInstance.terminated_at == None
            ).first()
            if not target_inst:
                raise RuntimeError(f"VM ID {vm_id} not found or already terminated.")
            
            # Check if it is DONE in OpenNebula
            try:
                live = get_vm(target_inst.one_vm_id)
            except Exception:
                live = {"state": "DONE"}
            if live["state"] == "DONE":
                target_inst.terminated_at = datetime.now(timezone.utc)
                db.commit()
                raise RuntimeError(f"VM ID {vm_id} has been terminated/deleted.")
        else:
            # Find any non-terminated VM, checking OpenNebula state to ensure it is not DONE
            instances = db.query(VMInstance).filter(
                VMInstance.user_id == user.id,
                VMInstance.terminated_at == None
            ).all()
            
            # Filter out any instances that are actually DONE in OpenNebula
            valid_instances = []
            for inst in instances:
                try:
                    live = get_vm(inst.one_vm_id)
                    if live["state"] == "DONE":
                        inst.terminated_at = datetime.now(timezone.utc)
                        db.commit()
                    else:
                        valid_instances.append((inst, live))
                except Exception:
                    # If we can't fetch it, assume it is unreachable but not necessarily DONE
                    valid_instances.append((inst, {"state": "UNREACHABLE"}))
            
            # Prioritize the active, running VM with the fewest containers (load balancing)
            best_inst = None
            min_containers = float('inf')
            for inst, live in valid_instances:
                if live["state"] == "ACTIVE" and live.get("lcm_state") == 3:
                    ip = live.get("ip_address")
                    if ip and ip != "—":
                        try:
                            import docker
                            from opennebula.vm_manager import get_ssh_user_by_template
                            ssh_user = get_ssh_user_by_template(inst.template_id)
                            cli = docker.DockerClient(base_url=f"ssh://{ssh_user}@{ip}", use_ssh_client=True, timeout=3)
                            # Count all containers on the host as a load metric
                            count = len(cli.containers.list(all=True))
                            cli.close()
                            cli.api.adapters.clear()
                            
                            if count < min_containers:
                                min_containers = count
                                best_inst = inst
                        except Exception:
                            continue
            
            if best_inst:
                target_inst = best_inst
            else:
                # Fallback to prioritizing the first available active VM
                for inst, live in valid_instances:
                    if live["state"] == "ACTIVE" and live.get("lcm_state") == 3:
                        target_inst = inst
                        break
            
            if not target_inst:
                # If none are running, look for a suspended/powered off one to resume
                for inst, live in valid_instances:
                    if live["state"] in ("SUSPENDED", "POWEROFF", "STOPPED"):
                        target_inst = inst
                        break
            
            if not target_inst and valid_instances:
                # Fallback to the first valid one
                target_inst = valid_instances[0][0]

        # If no VM exists, auto-provision one (or claim a pre-warmed standby VM)
        if not target_inst:
            vm_name = f"auto-vm-{username}-{int(time.time())}"
            
            # Check for a pre-warmed standby VM
            prewarmed_vm = None
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
                    client.vm.rename(one_vm_id, vm_name)
                    client.vm.chown(one_vm_id, user.one_user_id, -1)
                    print(f"DEBUG: Successfully claimed pre-warmed VM '{vm_name}' (one_vm_id={one_vm_id}) for user '{username}'")
                except Exception as e:
                    print(f"DEBUG: Failed to claim pre-warmed VM, falling back to full creation: {e}")
                    prewarmed_vm = None

            if not prewarmed_vm:
                # Fall back to standard on-demand creation (takes 90s)
                print(f"DEBUG: No pre-warmed VM available. Auto-provisioning VM '{vm_name}'...")
                one_vm_id = create_vm(
                    name=vm_name,
                    template_id=sla.DEFAULT_TEMPLATE_ID,
                    user_id=user.one_user_id,
                )
                print(f"DEBUG: VM '{vm_name}' created from scratch in OpenNebula with one_vm_id={one_vm_id}")

            target_inst = VMInstance(
                user_id=user.id,
                one_vm_id=one_vm_id,
                name=vm_name,
                template_id=sla.DEFAULT_TEMPLATE_ID,
            )
            db.add(target_inst)
            db.commit()
            db.refresh(target_inst)

        # Check the VM state in OpenNebula
        one_vm_id = target_inst.one_vm_id
        live = get_vm(one_vm_id)

        # If suspended or powered off, resume it
        if live["state"] in ("SUSPENDED", "POWEROFF", "STOPPED"):
            print(f"DEBUG: VM '{target_inst.name}' is {live['state']}. Resuming...")
            resume_vm(one_vm_id)

        # Wait for the VM to be ACTIVE and LCM_STATE = 3 (RUNNING)
        max_attempts = 45  # wait up to 90 seconds (45 * 2s)
        self_healed = False
        for attempt in range(max_attempts):
            live = get_vm(one_vm_id)
            if live["state"] == "DONE":
                print(f"DEBUG: VM '{target_inst.name}' has been terminated (state=DONE). Stopping wait.")
                target_inst.terminated_at = datetime.now(timezone.utc)
                db.commit()
                raise RuntimeError(f"VM '{target_inst.name}' has been terminated/deleted.")
            if live["state"] == "ACTIVE" and live["lcm_state"] == 3:
                ip = live.get("ip_address")
                if ip and ip != "—":
                    # Verify Docker daemon is actually running and accepting connections
                    test_client = None
                    try:
                        import docker
                        from opennebula.vm_manager import get_ssh_user_by_template
                        ssh_user = get_ssh_user_by_template(target_inst.template_id)
                        test_client = docker.DockerClient(base_url=f"ssh://{ssh_user}@{ip}", use_ssh_client=True, timeout=5)
                        if test_client.ping():
                            print(f"DEBUG: VM '{target_inst.name}' is fully RUNNING and Docker is reachable at IP {ip}.")
                            return target_inst.id
                    except Exception as test_err:
                        print(f"DEBUG: VM '{target_inst.name}' is booted but Docker/SSH is not ready yet: {test_err}")
                        if not self_healed:
                            print(f"DEBUG: Triggering self-healing for VM '{target_inst.name}' at IP {ip}...")
                            self_heal_docker(ip)
                            self_healed = True
                    finally:
                        if test_client:
                            try:
                                test_client.close()
                                test_client.api.adapters.clear()
                            except:
                                pass
            print(f"DEBUG: Waiting for VM '{target_inst.name}' to boot... State={live['state']}, LCM={live['lcm_state']} (attempt {attempt+1}/{max_attempts})")
            time.sleep(2)

        raise RuntimeError(f"Timed out waiting for VM '{target_inst.name}' to start.")
    finally:
        db.close()


def launch_container(
    username: str,
    image: str,
    name: str,
    env: dict = None,
    ports: list = None,
    vm_id: Optional[int] = None
) -> dict:
    """
    Pull image if needed and run a container for the user.
    """
    resolved_vm_id = ensure_user_has_running_vm(username, vm_id)
    client = get_client(username, resolved_vm_id)
    full_name = f"{username}-{name}"

    try:
        # Pre-flight: remove any leftover container with this name that is not running
        try:
            existing = client.containers.get(full_name)
            if existing.status != "running":
                existing.remove(force=True)
            else:
                raise RuntimeError(f"A container named '{name}' is already running — stop it first")
        except NotFound:
            pass  # no leftover, proceed normally

        # Pull image if not available locally
        try:
            client.images.get(image)
        except docker.errors.ImageNotFound:
            client.images.pull(image)

        # Build port bindings: {container_port: None} lets Docker pick a free host port
        port_bindings = {p: None for p in (ports or [])}

        container = client.containers.create(
            image,
            name=full_name,
            labels=container_label(username),
            environment=env or {},
            ports=port_bindings,
        )
        try:
            container.start()
        except Exception as e:
            container.remove(force=True)
            msg = str(e)
            if "port is already allocated" in msg or "Bind for" in msg:
                raise RuntimeError("Port already in use — choose a different host port") from e
            raise RuntimeError(msg) from e

        container.reload()
        res = _container_to_dict(container)
        res["vm_id"] = resolved_vm_id
        return res
    finally:
        try:
            client.close()
            client.api.adapters.clear()
        except Exception:
            pass


def list_containers(username: str) -> list[dict]:
    """List all containers belonging to the user across all their active VMs."""
    clients = get_all_clients(username)
    all_containers = []
    for vm_id, client in clients:
        try:
            containers = client.containers.list(
                all=True,
                filters={"label": f"{LABEL_KEY}={username}"},
            )
            for c in containers:
                info = _container_to_dict(c)
                info["vm_id"] = vm_id
                all_containers.append(info)
        except Exception:
            continue
        finally:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
    return all_containers


def get_container(username: str, container_id: str) -> dict:
    """Get a single container by ID, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) == username:
                info = _container_to_dict(container)
                info["vm_id"] = vm_id
                return info
        except NotFound:
            continue
        except Exception:
            continue
        finally:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
    raise FileNotFoundError(f"Container '{container_id}' not found on any active VMs")


def start_container(username: str, container_id: str) -> dict:
    """Start a stopped container, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            try:
                container.start()
            except Exception as e:
                msg = str(e)
                if "port is already allocated" in msg or "Bind for" in msg:
                    raise RuntimeError("Port already in use — stop the other container using that port first") from e
                raise RuntimeError(msg) from e
            container.reload()
            info = _container_to_dict(container)
            info["vm_id"] = vm_id
            return info
        except NotFound:
            continue
        finally:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
    raise FileNotFoundError(f"Container '{container_id}' not found")


def stop_container(username: str, container_id: str) -> dict:
    """Stop a running container, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            container.stop()
            container.reload()
            info = _container_to_dict(container)
            info["vm_id"] = vm_id
            return info
        except NotFound:
            continue
        finally:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
    raise FileNotFoundError(f"Container '{container_id}' not found")


def remove_container(username: str, container_id: str) -> None:
    """Stop and remove a container, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            container.remove(force=True)
            return
        except NotFound:
            continue
        finally:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
    raise FileNotFoundError(f"Container '{container_id}' not found")


def get_container_logs(username: str, container_id: str, tail: int = 100) -> str:
    """Get the logs of a container, searching across all active VMs."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            # logs returns bytes, let's decode to string
            logs_bytes = container.logs(stdout=True, stderr=True, tail=tail)
            return logs_bytes.decode("utf-8", errors="ignore")
        except NotFound:
            continue
        except PermissionError as e:
            raise e
        except Exception:
            continue
        finally:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
    raise FileNotFoundError(f"Container '{container_id}' not found")


def get_container_stats(username: str, container_id: str) -> dict:
    """Get CPU/RAM usage statistics for a container."""
    clients = get_all_clients(username)
    for vm_id, client in clients:
        try:
            container = client.containers.get(container_id)
            if container.labels.get(LABEL_KEY) != username:
                raise PermissionError("Container does not belong to this user")
            
            # Fetch single stats snapshot
            stats = container.stats(stream=False)
            
            # 1. Calculate Memory stats
            mem_stats = stats.get('memory_stats', {})
            mem_usage = mem_stats.get('usage', 0)
            mem_limit = mem_stats.get('limit', 0)
            
            # Convert to MB
            mem_mb = round(mem_usage / (1024 * 1024), 1)
            mem_limit_mb = round(mem_limit / (1024 * 1024), 1)
            
            # 2. Calculate CPU stats
            cpu_stats = stats.get('cpu_stats', {})
            precpu_stats = stats.get('precpu_stats', {})
            
            cpu_percent = 0.0
            if cpu_stats and precpu_stats:
                cpu_total = cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                precpu_total = precpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                
                system_cpu = cpu_stats.get('system_cpu_usage', 0)
                pre_system_cpu = precpu_stats.get('system_cpu_usage', 0)
                
                cpu_delta = cpu_total - precpu_total
                system_delta = system_cpu - pre_system_cpu
                
                # Get number of cores
                online_cpus = cpu_stats.get('online_cpus')
                if not online_cpus:
                    percpu = cpu_stats.get('cpu_usage', {}).get('percpu_usage')
                    online_cpus = len(percpu) if percpu else 1
                
                if system_delta > 0 and cpu_delta > 0:
                    cpu_percent = round((cpu_delta / system_delta) * online_cpus * 100.0, 1)
            
            return {
                "cpu_percent": cpu_percent,
                "memory_mb": mem_mb,
                "memory_limit_mb": mem_limit_mb,
                "memory_percent": round((mem_usage / mem_limit) * 100.0, 1) if mem_limit > 0 else 0.0
            }
        except NotFound:
            continue
        except PermissionError as e:
            raise e
        except Exception:
            continue
        finally:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
    raise FileNotFoundError(f"Container '{container_id}' not found")


def _container_to_dict(container) -> dict:
    container.reload()
    ports = container.ports or {}
    return {
        "container_id": container.short_id,
        "full_id": container.id,
        "name": container.name,
        "image": container.image.tags[0] if container.image.tags else container.attrs["Config"]["Image"],
        "status": container.status,
        "ports": ports,
        "created": container.attrs.get("Created", ""),
    }
