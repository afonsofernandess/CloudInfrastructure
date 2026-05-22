from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.jwt import get_current_user
from api.auth.models import User
from api.database import get_db
from api.database_service.models import DBInstance
from api.database_service.schemas import DBProvisionRequest, DBInstanceResponse, DBCredentials
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
    instances = db.query(DBInstance).filter(DBInstance.user_id == current_user.id).all()
    result = []
    for inst in instances:
        client, container, vm_id = db_manager.get_db_container_and_client(current_user.username, inst.container_id)
        status_str = container.status if container else "removed"
        
        host_ip = "localhost"
        if vm_id:
            host_ip = db_manager.get_vm_ip_by_id(vm_id)
            
        result.append(_build_response(inst, status_str, host_ip, vm_id))
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
    status_str = container.status if container else "removed"
    
    host_ip = "localhost"
    if vm_id:
        host_ip = db_manager.get_vm_ip_by_id(vm_id)

    return _build_response(instance, status_str, host_ip, vm_id)


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
