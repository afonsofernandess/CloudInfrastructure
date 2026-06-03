import logging
import time
from typing import Optional
from sqlalchemy.orm import Session
import docker
from docker.errors import NotFound

from api.database_service import db_manager
from api.database_service.models import DBInstance
from api.database_service.schemas import DBInstanceResponse, DBCredentials
from api.loadbalancer.schemas import DBClusterResponse
from api.containers.docker_client import (
    ensure_user_has_running_vm, get_client
)
from api.loadbalancer.ssh_utils import run_ssh_command, write_ssh_file

POSTGRES_IMAGE = "postgres:16-alpine"
LABEL_KEY = "cloud_db_user"
CONTAINER_PORT = "5432/tcp"

log = logging.getLogger("loadbalancer.db_lb")


def _get_client(username: str, vm_id: Optional[int] = None) -> docker.DockerClient:
    return get_client(username, vm_id)


def _wait_for_port(container, timeout: int = 60) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        container.reload()
        if container.status not in ("running", "created"):
            raise RuntimeError(
                f"PostgreSQL container '{container.name}' exited unexpectedly (status={container.status}). "
                f"Check logs with: docker logs {container.name}"
            )
        ports = container.ports
        mapping = ports.get(CONTAINER_PORT)
        if mapping:
            return int(mapping[0]["HostPort"])
        time.sleep(1)
    raise RuntimeError("PostgreSQL container started but no host port was assigned in time")


def _build_db_response(instance: DBInstance, status_str: str, host_ip: str, vm_id: Optional[int] = None) -> DBInstanceResponse:
    creds = DBCredentials(
        host=host_ip,
        port=instance.host_port,
        db_name=instance.db_name,
        db_user=instance.db_user,
        db_password=instance.db_password,
        connection_string=(
            f"postgresql://{instance.db_user}:{instance.db_password}"
            f"@{host_ip}:{instance.host_port}/{instance.db_name}"
        ),
    )
    return DBInstanceResponse(
        id=instance.id,
        instance_name=instance.instance_name,
        container_id=instance.container_id[:12],
        status=status_str,
        credentials=creds,
        created_at=instance.created_at,
        vm_id=vm_id,
        role=instance.role,
        parent_id=instance.parent_id,
        cluster_name=instance.cluster_name,
        read_host_port=instance.read_host_port,
    )


def provision_cluster(
    db: Session,
    username: str,
    user_id: int,
    cluster_name: str,
    db_name: Optional[str] = None,
    replicas_count: int = 1,
) -> DBClusterResponse:
    """
    Provision a PostgreSQL database cluster:
    1. Primary PostgreSQL database container.
    2. Configures Primary for replication and reloads settings.
    3. Syncs Standby replicas via pg_basebackup over network/VM-to-VM.
    4. Deploys an HAProxy TCP load balancer container.
    """
    existing = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name
    ).first()
    if existing:
        raise RuntimeError(f"A database cluster named '{cluster_name}' already exists.")

    final_db_name = db_name or username

    # Step 1: Provision Primary PostgreSQL
    log.info("Provisioning Primary DB for cluster '%s'...", cluster_name)
    primary_info = db_manager.provision_db(
        username=username,
        instance_name=f"{cluster_name}-primary",
        db_name=final_db_name,
    )
    
    primary_vm_id = primary_info["vm_id"]
    primary_vm_ip = db_manager.get_vm_ip_by_id(primary_vm_id)

    primary_db = DBInstance(
        user_id=user_id,
        container_id=primary_info["container_id"],
        instance_name=f"{cluster_name}-primary",
        db_name=primary_info["db_name"],
        db_user=primary_info["db_user"],
        db_password=primary_info["db_password"],
        host_port=primary_info["host_port"],
        role="primary",
        cluster_name=cluster_name,
    )
    db.add(primary_db)
    db.commit()
    db.refresh(primary_db)

    # Step 2: Configure Primary for replication via direct SSH (exec_run hangs over SSH transport)
    log.info("Configuring Primary DB for replication permissions...")
    try:
        container_name = f"db-{username}-{cluster_name}-primary"

        # Wait for PostgreSQL inside the container to be ready to accept connections
        log.info("Waiting for primary PostgreSQL to accept connections...")
        db_ready = False
        for attempt in range(30):
            try:
                run_ssh_command(
                    primary_vm_ip,
                    f"docker exec {container_name} pg_isready -U {primary_db.db_user} -d {primary_db.db_name}"
                )
                db_ready = True
                log.info("Primary DB is ready!")
                break
            except Exception as e:
                log.info("Primary DB not ready yet (attempt %d/30): %s", attempt + 1, e)
                time.sleep(1)
        if not db_ready:
            raise RuntimeError("Primary DB did not become ready to accept connections in time.")

        # Create replicator role (ignore if already exists)
        run_ssh_command(
            primary_vm_ip,
            f"docker exec {container_name} psql -U {primary_db.db_user} -d {primary_db.db_name} "
            f"-c \"CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicasecret';\" || true"
        )
        log.info("CREATE ROLE replicator done.")

        # Allow replication connections from any host (scram-sha-256 matches PG16 default)
        run_ssh_command(
            primary_vm_ip,
            f"docker exec {container_name} sh -c "
            f"\"grep -qF 'host replication replicator 0.0.0.0/0' "
            f"/var/lib/postgresql/data/pg_hba.conf || "
            f"echo 'host replication replicator 0.0.0.0/0 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf\""
        )
        log.info("pg_hba.conf replication rule updated.")

        # Allow all users to connect from any network host via password.
        # This is required so connections routed through HAProxy (which arrive at
        # PostgreSQL from the VM bridge/network IP instead of 127.0.0.1) can
        # authenticate successfully with scram-sha-256.
        run_ssh_command(
            primary_vm_ip,
            f"docker exec {container_name} sh -c "
            f"\"grep -qF 'host all all 0.0.0.0/0' "
            f"/var/lib/postgresql/data/pg_hba.conf || "
            f"echo 'host all all 0.0.0.0/0 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf\""
        )
        log.info("pg_hba.conf host-all rule updated.")

        # Reload configuration
        run_ssh_command(
            primary_vm_ip,
            f"docker exec {container_name} psql -U {primary_db.db_user} -d {primary_db.db_name} "
            f"-c \"SELECT pg_reload_conf();\""
        )
        log.info("pg_reload_conf done.")
    except Exception as e:
        log.error("Failed to configure primary replication options via SSH: %s", e)

    # Step 3: Provision Read Replicas
    replicas = []
    for i in range(1, replicas_count + 1):
        log.info("Provisioning Replica #%d for cluster '%s'...", i, cluster_name)
        replica_vm_id = ensure_user_has_running_vm(username)
        replica_vm_ip = db_manager.get_vm_ip_by_id(replica_vm_id)
        
        local_data_path = f"/var/lib/postgresql/data-{cluster_name}-replica-{i}"
        run_ssh_command(replica_vm_ip, f"mkdir -p {local_data_path} && rm -rf {local_data_path}/*")
        
        # Sync databases via pg_basebackup container inside VM
        backup_cmd = (
            f"docker run --rm -e PGPASSWORD=replicasecret "
            f"-v {local_data_path}:/backup {POSTGRES_IMAGE} "
            f"pg_basebackup -h {primary_vm_ip} -p {primary_db.host_port} "
            f"-D /backup -U replicator --checkpoint=fast -v -P -R"
        )
        run_ssh_command(replica_vm_ip, backup_cmd)

        # Fix ownership so the postgres user inside the container can read the data
        run_ssh_command(replica_vm_ip, f"chown -R 999:999 {local_data_path}")
        
        replica_client = _get_client(username, replica_vm_id)
        replica_container_name = f"db-{username}-{cluster_name}-replica-{i}"
        
        try:
            existing_c = replica_client.containers.get(replica_container_name)
            existing_c.remove(force=True)
        except NotFound:
            pass
        try:
            replica_client.images.get(POSTGRES_IMAGE)
        except docker.errors.ImageNotFound:
            log.info("Pulling database replica image '%s'...", POSTGRES_IMAGE)
            replica_client.images.pull(POSTGRES_IMAGE)
            
        replica_container = replica_client.containers.create(
            POSTGRES_IMAGE,
            name=replica_container_name,
            labels={LABEL_KEY: username},
            environment={
                # Required so Postgres can start even if the data dir is somehow empty
                "POSTGRES_PASSWORD": primary_db.db_password,
                "POSTGRES_USER": primary_db.db_user,
                "POSTGRES_DB": primary_db.db_name,
                # Tell Postgres it is already initialised (pg_basebackup output)
                "PGDATA": "/var/lib/postgresql/data",
            },
            ports={CONTAINER_PORT: None},
            volumes={
                local_data_path: {
                    "bind": "/var/lib/postgresql/data",
                    "mode": "rw"
                }
            },
            detach=True
        )
        
        try:
            replica_container.start()
        except Exception as e:
            replica_container.remove(force=True)
            raise RuntimeError(f"Failed to start Replica container: {e}")
            
        replica_host_port = _wait_for_port(replica_container)
        replica_client.close()
        
        replica_db = DBInstance(
            user_id=user_id,
            container_id=replica_container.id,
            instance_name=f"{cluster_name}-replica-{i}",
            db_name=primary_db.db_name,
            db_user=primary_db.db_user,
            db_password=primary_db.db_password,
            host_port=replica_host_port,
            role="replica",
            parent_id=primary_db.id,
            cluster_name=cluster_name,
        )
        db.add(replica_db)
        db.commit()
        db.refresh(replica_db)
        replicas.append(replica_db)

    # Step 4: Deploy HAProxy Load Balancer
    # Use a dedicated VM so HAProxy doesn't compete for memory with the primary PostgreSQL
    lb_vm_id = ensure_user_has_running_vm(username)
    lb_vm_ip = db_manager.get_vm_ip_by_id(lb_vm_id)

    lb_db = deploy_haproxy_lb(
        db=db,
        username=username,
        user_id=user_id,
        cluster_name=cluster_name,
        primary_db=primary_db,
        replicas=replicas,
        lb_vm_id=lb_vm_id,
        lb_vm_ip=lb_vm_ip
    )

    primary_resp = _build_db_response(primary_db, "running", primary_vm_ip, primary_vm_id)
    replicas_resp = []
    
    for r in replicas:
        _, _, r_vmid = db_manager.get_db_container_and_client(username, r.container_id)
        r_ip = db_manager.get_vm_ip_by_id(r_vmid)
        replicas_resp.append(_build_db_response(r, "running", r_ip, r_vmid))

    lb_resp = _build_db_response(lb_db, "running", lb_vm_ip, lb_vm_id)
    
    return DBClusterResponse(
        cluster_name=cluster_name,
        primary=primary_resp,
        replicas=replicas_resp,
        load_balancer=lb_resp
    )


def deploy_haproxy_lb(
    db: Session,
    username: str,
    user_id: int,
    cluster_name: str,
    primary_db: DBInstance,
    replicas: list[DBInstance],
    lb_vm_id: int,
    lb_vm_ip: str
) -> DBInstance:
    """Configure and deploy the HAProxy load balancer container on the target VM."""
    _, _, p_vmid = db_manager.get_db_container_and_client(username, primary_db.container_id)
    p_ip = db_manager.get_vm_ip_by_id(p_vmid)
    
    replica_servers_cfg = ""
    for idx, r in enumerate(replicas):
        _, _, r_vmid = db_manager.get_db_container_and_client(username, r.container_id)
        r_ip = db_manager.get_vm_ip_by_id(r_vmid)
        replica_servers_cfg += f"    server db-replica-{idx+1} {r_ip}:{r.host_port} check\n"

    # Config has two frontends: 5432 (Write to Primary) and 5433 (Read to primary + replicas)
    haproxy_cfg = f"""global
    log stdout format raw local0
    nbthread 1
    maxconn 100

defaults
    log     global
    mode    tcp
    maxconn 50
    timeout connect 5s
    timeout client  50s
    timeout server  50s

frontend postgres_write_front
    bind *:5432
    default_backend postgres_primary

backend postgres_primary
    mode tcp
    option tcp-check
    server db-primary {p_ip}:{primary_db.host_port} check

frontend postgres_read_front
    bind *:5433
    default_backend postgres_replicas

backend postgres_replicas
    mode tcp
    balance roundrobin
    option tcp-check
    server db-primary {p_ip}:{primary_db.host_port} check
{replica_servers_cfg}"""

    local_cfg_dir = f"/var/lib/haproxy-{cluster_name}"
    write_ssh_file(lb_vm_ip, f"{local_cfg_dir}/haproxy.cfg", haproxy_cfg)
    
    lb_client = _get_client(username, lb_vm_id)
    lb_container_name = f"db-{username}-{cluster_name}-lb"
    
    try:
        existing = lb_client.containers.get(lb_container_name)
        existing.remove(force=True)
    except NotFound:
        pass
    try:
        lb_client.images.get("haproxy:2.8-alpine")
    except docker.errors.ImageNotFound:
        log.info("Pulling load balancer image 'haproxy:2.8-alpine'...")
        lb_client.images.pull("haproxy:2.8-alpine")
        
    container = lb_client.containers.create(
        "haproxy:2.8-alpine",
        name=lb_container_name,
        labels={LABEL_KEY: username},
        ports={"5432/tcp": None, "5433/tcp": None},
        volumes={
            local_cfg_dir: {
                "bind": "/usr/local/etc/haproxy",
                "mode": "ro"
            }
        },
        detach=True
    )
    
    container.start()

    # Poll until Docker assigns both host ports (SSH transport can be slow)
    _deadline = time.time() + 60
    write_port = None
    read_port = None
    while time.time() < _deadline:
        container.reload()
        if container.status not in ("running", "created"):
            raise RuntimeError(
                f"HAProxy container '{lb_container_name}' exited unexpectedly (status={container.status})"
            )
        _ports = container.ports
        _w = _ports.get("5432/tcp")
        _r = _ports.get("5433/tcp")
        if _w and _r:
            write_port = int(_w[0]["HostPort"])
            read_port = int(_r[0]["HostPort"])
            break
        time.sleep(1)
    if write_port is None or read_port is None:
        raise RuntimeError("HAProxy container started but ports were not assigned in time")

    lb_client.close()

    existing_lb = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name,
        DBInstance.role == "load_balancer"
    ).first()
    
    if existing_lb:
        existing_lb.container_id = container.id
        existing_lb.host_port = write_port
        existing_lb.read_host_port = read_port
        existing_lb.db_password = ""
        db.commit()
        db.refresh(existing_lb)
        return existing_lb
    else:
        new_lb = DBInstance(
            user_id=user_id,
            container_id=container.id,
            instance_name=f"{cluster_name}-lb",
            db_name=primary_db.db_name,
            db_user=primary_db.db_user,
            db_password="",
            host_port=write_port,
            read_host_port=read_port,
            role="load_balancer",
            cluster_name=cluster_name,
        )
        db.add(new_lb)
        db.commit()
        db.refresh(new_lb)
        return new_lb


def scale_cluster(
    db: Session,
    username: str,
    user_id: int,
    cluster_name: str,
    target_replicas_count: int
) -> DBClusterResponse:
    """Scale DB replica count and update HAProxy load balancer backends."""
    primary_db = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name,
        DBInstance.role == "primary"
    ).first()
    
    if not primary_db:
        raise RuntimeError(f"Primary database for cluster '{cluster_name}' not found.")
        
    _, _, primary_vm_id = db_manager.get_db_container_and_client(username, primary_db.container_id)
    primary_vm_ip = db_manager.get_vm_ip_by_id(primary_vm_id)

    current_replicas = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name,
        DBInstance.role == "replica"
    ).all()
    
    current_count = len(current_replicas)
    
    if target_replicas_count > current_count:
        # Scale up
        for i in range(current_count + 1, target_replicas_count + 1):
            log.info("Scaling up DB Cluster: adding Replica #%d...", i)
            replica_vm_id = ensure_user_has_running_vm(username)
            replica_vm_ip = db_manager.get_vm_ip_by_id(replica_vm_id)
            
            local_data_path = f"/var/lib/postgresql/data-{cluster_name}-replica-{i}"
            run_ssh_command(replica_vm_ip, f"mkdir -p {local_data_path} && rm -rf {local_data_path}/*")

            backup_cmd = (
                f"docker run --rm -e PGPASSWORD=replicasecret "
                f"-v {local_data_path}:/backup {POSTGRES_IMAGE} "
                f"pg_basebackup -h {primary_vm_ip} -p {primary_db.host_port} "
                f"-D /backup -U replicator --checkpoint=fast -v -P -R"
            )
            run_ssh_command(replica_vm_ip, backup_cmd)

            # Fix ownership so the postgres user inside the container can read the data
            run_ssh_command(replica_vm_ip, f"chown -R 999:999 {local_data_path}")

            replica_client = _get_client(username, replica_vm_id)
            replica_container_name = f"db-{username}-{cluster_name}-replica-{i}"

            try:
                existing_c = replica_client.containers.get(replica_container_name)
                existing_c.remove(force=True)
            except NotFound:
                pass
            try:
                replica_client.images.get(POSTGRES_IMAGE)
            except docker.errors.ImageNotFound:
                log.info("Pulling database replica image '%s' for scale-up...", POSTGRES_IMAGE)
                replica_client.images.pull(POSTGRES_IMAGE)

            replica_container = replica_client.containers.create(
                POSTGRES_IMAGE,
                name=replica_container_name,
                labels={LABEL_KEY: username},
                environment={
                    "POSTGRES_PASSWORD": primary_db.db_password,
                    "POSTGRES_USER": primary_db.db_user,
                    "POSTGRES_DB": primary_db.db_name,
                    "PGDATA": "/var/lib/postgresql/data",
                },
                ports={CONTAINER_PORT: None},
                volumes={
                    local_data_path: {
                        "bind": "/var/lib/postgresql/data",
                        "mode": "rw"
                    }
                },
                detach=True
            )
            replica_container.start()
            replica_host_port = _wait_for_port(replica_container)
            replica_client.close()
            
            new_replica = DBInstance(
                user_id=user_id,
                container_id=replica_container.id,
                instance_name=f"{cluster_name}-replica-{i}",
                db_name=primary_db.db_name,
                db_user=primary_db.db_user,
                db_password=primary_db.db_password,
                host_port=replica_host_port,
                role="replica",
                parent_id=primary_db.id,
                cluster_name=cluster_name,
            )
            db.add(new_replica)
            db.commit()
            db.refresh(new_replica)
            current_replicas.append(new_replica)
    elif target_replicas_count < current_count:
        # Scale down
        for i in range(current_count, target_replicas_count, -1):
            log.info("Scaling down DB Cluster: removing Replica #%d...", i)
            rep_to_remove = next((r for r in current_replicas if r.instance_name == f"{cluster_name}-replica-{i}"), None)
            if rep_to_remove:
                client = None
                try:
                    client, container, _ = db_manager.get_db_container_and_client(username, rep_to_remove.container_id)
                    if container:
                        container.remove(force=True)
                except Exception as e:
                    log.error("Failed to remove replica container: %s", e)
                finally:
                    if client:
                        client.close()
                
                db.delete(rep_to_remove)
                db.commit()
                current_replicas.remove(rep_to_remove)

    updated_replicas = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name,
        DBInstance.role == "replica"
    ).all()

    lb_db = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name,
        DBInstance.role == "load_balancer"
    ).first()
    
    if lb_db:
        _, _, lb_vmid = db_manager.get_db_container_and_client(username, lb_db.container_id)
        lb_ip = db_manager.get_vm_ip_by_id(lb_vmid)
        deploy_haproxy_lb(
            db=db,
            username=username,
            user_id=user_id,
            cluster_name=cluster_name,
            primary_db=primary_db,
            replicas=updated_replicas,
            lb_vm_id=lb_vmid,
            lb_vm_ip=lb_ip
        )
        db.refresh(lb_db)

    primary_resp = _build_db_response(primary_db, "running", primary_vm_ip, primary_vm_id)
    replicas_resp = []
    
    for r in updated_replicas:
        _, _, r_vmid = db_manager.get_db_container_and_client(username, r.container_id)
        r_ip = db_manager.get_vm_ip_by_id(r_vmid)
        replicas_resp.append(_build_db_response(r, "running", r_ip, r_vmid))

    lb_resp = _build_db_response(lb_db, "running", lb_ip, lb_vmid) if lb_db else None

    return DBClusterResponse(
        cluster_name=cluster_name,
        primary=primary_resp,
        replicas=replicas_resp,
        load_balancer=lb_resp
    )


def get_cluster_details(db: Session, username: str, user_id: int, cluster_name: str) -> DBClusterResponse:
    """Get active database cluster details."""
    instances = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name
    ).all()
    
    if not instances:
        raise FileNotFoundError(f"Database cluster '{cluster_name}' not found.")
        
    primary_db = next((i for i in instances if i.role == "primary"), None)
    replicas_db = [i for i in instances if i.role == "replica"]
    lb_db = next((i for i in instances if i.role == "load_balancer"), None)

    if not primary_db:
        # Orphaned rows — the cluster was partially deleted outside the API.
        # Purge them so the user can re-provision, then return 404.
        for inst in instances:
            db.delete(inst)
        db.commit()
        raise FileNotFoundError(
            f"Database cluster '{cluster_name}' has orphaned records (no primary found). "
            "Stale records have been cleaned up — you can provision a new cluster now."
        )

    _, _, p_vmid = db_manager.get_db_container_and_client(username, primary_db.container_id)
    p_ip = db_manager.get_vm_ip_by_id(p_vmid)
    primary_resp = _build_db_response(primary_db, "running", p_ip, p_vmid)
    
    replicas_resp = []
    for r in replicas_db:
        _, _, r_vmid = db_manager.get_db_container_and_client(username, r.container_id)
        r_ip = db_manager.get_vm_ip_by_id(r_vmid)
        replicas_resp.append(_build_db_response(r, "running", r_ip, r_vmid))

    lb_resp = None
    if lb_db:
        _, _, lb_vmid = db_manager.get_db_container_and_client(username, lb_db.container_id)
        lb_ip = db_manager.get_vm_ip_by_id(lb_vmid)
        lb_resp = _build_db_response(lb_db, "running", lb_ip, lb_vmid)

    return DBClusterResponse(
        cluster_name=cluster_name,
        primary=primary_resp,
        replicas=replicas_resp,
        load_balancer=lb_resp
    )


def delete_cluster(
    db: Session,
    username: str,
    user_id: int,
    cluster_name: str,
) -> None:
    """
    Stop and remove all containers belonging to the cluster (best-effort),
    then delete every DB row for the cluster so it can be re-provisioned.
    """
    instances = db.query(DBInstance).filter(
        DBInstance.user_id == user_id,
        DBInstance.cluster_name == cluster_name,
    ).all()

    if not instances:
        raise FileNotFoundError(f"Database cluster '{cluster_name}' not found.")

    # Remove each container best-effort (container may already be gone)
    for inst in instances:
        vm_ip = None
        try:
            client, container, vm_id = db_manager.get_db_container_and_client(username, inst.container_id)
            if vm_id:
                vm_ip = db_manager.get_vm_ip_by_id(vm_id)
            if container:
                container.remove(force=True)
            if client:
                try:
                    client.close()
                    client.api.adapters.clear()
                except Exception:
                    pass
        except Exception as e:
            log.warning(
                "Could not remove container for instance '%s' (may already be gone): %s",
                inst.instance_name, e
            )

        # Clean up directories on VM (volume/config)
        if vm_ip:
            if inst.role == "primary":
                try:
                    run_ssh_command(vm_ip, f"rm -rf /var/lib/postgresql/data-{cluster_name}-primary")
                    log.info("Deleted volume directory for primary on VM %s", vm_ip)
                except Exception as e:
                    log.warning("Could not delete primary volume directory on VM %s: %s", vm_ip, e)
            elif inst.role == "replica":
                try:
                    parts = inst.instance_name.split("-")
                    rep_idx = parts[-1]
                    run_ssh_command(vm_ip, f"rm -rf /var/lib/postgresql/data-{cluster_name}-replica-{rep_idx}")
                    log.info("Deleted volume directory for replica-%s on VM %s", rep_idx, vm_ip)
                except Exception as e:
                    log.warning("Could not delete replica-%s volume directory on VM %s: %s", rep_idx, vm_ip, e)
            elif inst.role == "load_balancer":
                try:
                    run_ssh_command(vm_ip, f"rm -rf /var/lib/haproxy-{cluster_name}")
                    log.info("Deleted config directory for load balancer on VM %s", vm_ip)
                except Exception as e:
                    log.warning("Could not delete load balancer config directory on VM %s: %s", vm_ip, e)

        db.delete(inst)

    db.commit()
    log.info("Cluster '%s' deleted for user '%s'.", cluster_name, username)
