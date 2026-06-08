from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.jwt import get_current_user
from api.auth.models import User
from api.database import get_db
from api.database_service.models import DBInstance
from api.database_service.schemas import DBProvisionRequest, DBInstanceResponse, DBCredentials, DBMetricsResponse
from api.database_service import db_manager

router = APIRouter(prefix="/databases", tags=["databases"])


from typing import Optional

def _build_response(instance: DBInstance, status_str: str, host_ip: str, vm_id: Optional[int] = None) -> DBInstanceResponse:
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


# POST /databases — provision a new PostgreSQL instance
@router.post("", response_model=DBInstanceResponse, status_code=status.HTTP_201_CREATED)
def provision(
    data: DBProvisionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_name = data.db_name or current_user.username

    try:
        info = db_manager.provision_db(
            username=current_user.username,
            instance_name=data.name,
            db_name=db_name,
            vm_id=data.vm_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to provision database: {e}")

    instance = DBInstance(
        user_id=current_user.id,
        container_id=info["container_id"],
        instance_name=data.name,
        db_name=info["db_name"],
        db_user=info["db_user"],
        db_password=info["db_password"],
        host_port=info["host_port"],
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)

    host_ip = "localhost"
    if info["vm_id"]:
        host_ip = db_manager.get_vm_ip_by_id(info["vm_id"])

    return _build_response(instance, "running", host_ip, info["vm_id"])


# GET /databases — list user's database instances
@router.get("", response_model=list[DBInstanceResponse])
def list_instances(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from api.containers.docker_client import get_all_clients
    instances = db.query(DBInstance).filter(DBInstance.user_id == current_user.id).all()
    
    # 1. Establish connections to all active VMs once in parallel
    clients = get_all_clients(current_user.username)
    result = []
    
    try:
        # 2. For each database instance, find its container status
        for inst in instances:
            container = None
            found_vm_id = None
            for vm_id, client in clients:
                try:
                    c = client.containers.get(inst.container_id)
                    container = c
                    found_vm_id = vm_id
                    break
                except Exception:
                    pass
            
            status_str = container.status if container else "removed"
            host_ip = "localhost"
            if found_vm_id:
                host_ip = db_manager.get_vm_ip_by_id(found_vm_id)
            result.append(_build_response(inst, status_str, host_ip, found_vm_id))
    finally:
        # 3. Close all clients at the end
        for vm_id, client in clients:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass
                
    return result



# GET /databases/{instance_id} — get credentials + live status for one instance
@router.get("/{instance_id}", response_model=DBInstanceResponse)
def get_instance(
    instance_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instance = db.query(DBInstance).filter(
        DBInstance.id == instance_id,
        DBInstance.user_id == current_user.id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Database instance not found")

    client, container, vm_id = db_manager.get_db_container_and_client(current_user.username, instance.container_id)
    try:
        status_str = container.status if container else "removed"
        host_ip = "localhost"
        if vm_id:
            host_ip = db_manager.get_vm_ip_by_id(vm_id)
        return _build_response(instance, status_str, host_ip, vm_id)
    finally:
        if client:
            try:
                client.close()
                client.api.adapters.clear()
            except Exception:
                pass


# DELETE /databases/{instance_id} — deprovision (stop + remove container, delete record)
@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def deprovision(
    instance_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instance = db.query(DBInstance).filter(
        DBInstance.id == instance_id,
        DBInstance.user_id == current_user.id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Database instance not found")

    try:
        db_manager.deprovision_db(current_user.username, instance.container_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to deprovision database: {e}")

    db.delete(instance)
    db.commit()


# POST /databases/{instance_id}/restart — restart database container
@router.post("/{instance_id}/restart", status_code=status.HTTP_204_NO_CONTENT)
def restart_instance(
    instance_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instance = db.query(DBInstance).filter(
        DBInstance.id == instance_id,
        DBInstance.user_id == current_user.id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Database instance not found")

    try:
        new_ports = db_manager.restart_db(current_user.username, instance.container_id)
        if "host_port" in new_ports:
            instance.host_port = new_ports["host_port"]
        if "read_host_port" in new_ports:
            instance.read_host_port = new_ports["read_host_port"]
        db.commit()

        # If this database instance is part of a cluster, synchronize HAProxy & replication settings
        if instance.cluster_name:
            try:
                # Refresh data from DB
                db.refresh(instance)
                
                # Find all cluster members
                cluster_instances = db.query(DBInstance).filter(
                    DBInstance.cluster_name == instance.cluster_name
                ).all()
                primary_db = next((r for r in cluster_instances if r.role == "primary"), None)
                replicas = [r for r in cluster_instances if r.role == "replica"]
                lb_db = next((r for r in cluster_instances if r.role == "load_balancer"), None)

                if lb_db and primary_db:
                    from api.loadbalancer.db_lb import deploy_haproxy_lb
                    from api.database_service.db_manager import get_user_vm_ip
                    lb_ip = get_user_vm_ip(current_user.username, lb_db.vm_id)
                    deploy_haproxy_lb(
                        db=db,
                        username=current_user.username,
                        user_id=current_user.id,
                        cluster_name=instance.cluster_name,
                        primary_db=primary_db,
                        replicas=replicas,
                        lb_vm_id=lb_db.vm_id,
                        lb_vm_ip=lb_ip
                    )

                    # If we restarted the primary node, update WAL connection info on the replica nodes
                    if instance.role == "primary" and "host_port" in new_ports:
                        primary_vm_ip = get_user_vm_ip(current_user.username, primary_db.vm_id)
                        from api.compute.autoscaler import autoscaler
                        from api.database import engine
                        autoscaler._fix_replica_wal_conninfo(
                            cluster_name=instance.cluster_name,
                            new_primary_port=new_ports["host_port"],
                            primary_vm_ip=primary_vm_ip,
                            db_path=engine.url.database
                        )
            except Exception as lb_err:
                import logging
                logging.getLogger("databases.router").warning(
                    f"Failed to synchronize database cluster after restart: {lb_err}"
                )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart database: {e}")


# GET /databases/{instance_id}/metrics — get database connection count & size metrics
@router.get("/{instance_id}/metrics", response_model=DBMetricsResponse)
def get_database_metrics(
    instance_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instance = db.query(DBInstance).filter(
        DBInstance.id == instance_id,
        DBInstance.user_id == current_user.id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Database instance not found")

    metrics = db_manager.get_db_metrics(
        username=current_user.username,
        container_id=instance.container_id,
        db_user=instance.db_user,
        db_name=instance.db_name,
        db_password=instance.db_password,
    )
    return metrics
