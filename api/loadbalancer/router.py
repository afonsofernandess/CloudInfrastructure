from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.jwt import get_current_user
from api.auth.models import User
from api.database import get_db
from api.loadbalancer.schemas import (
    ContainerScaleRequest, ContainerScaleResponse,
    DBClusterProvisionRequest, DBClusterResponse
)
from api.loadbalancer import container_lb, db_lb

router = APIRouter(prefix="/loadbalancer", tags=["loadbalancer"])


# POST /loadbalancer/containers/scale — scale worker containers and update Nginx load balancer
@router.post("/containers/scale", response_model=ContainerScaleResponse)
def scale_containers(
    data: ContainerScaleRequest,
    current_user: User = Depends(get_current_user)
):
    print("--> SCALE CONTAINERS ENDPOINT CALLED", flush=True)
    try:
        return container_lb.scale_container_group(current_user.username, data)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scale container group: {e}")


# GET /loadbalancer/containers/scale/{name} — retrieve status of container scale group
@router.get("/containers/scale/{name}", response_model=ContainerScaleResponse)
def get_container_group(
    name: str,
    current_user: User = Depends(get_current_user)
):
    try:
        return container_lb.get_container_group_details(current_user.username, name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch scale group details: {e}")


# POST /loadbalancer/databases/cluster — provision a new clustered PostgreSQL database (with HAProxy)
@router.post("/databases/cluster", response_model=DBClusterResponse, status_code=status.HTTP_201_CREATED)
def provision_database_cluster(
    data: DBClusterProvisionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return db_lb.provision_cluster(
            db=db,
            username=current_user.username,
            user_id=current_user.id,
            cluster_name=data.cluster_name,
            db_name=data.db_name,
            replicas_count=data.replicas,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to provision database cluster: {e}")


# POST /loadbalancer/databases/cluster/{cluster_name}/scale — scale cluster replicas up or down
@router.post("/databases/cluster/{cluster_name}/scale", response_model=DBClusterResponse)
def scale_database_cluster(
    cluster_name: str,
    replicas: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return db_lb.scale_cluster(
            db=db,
            username=current_user.username,
            user_id=current_user.id,
            cluster_name=cluster_name,
            target_replicas_count=replicas,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scale cluster: {e}")


# GET /loadbalancer/databases/cluster/{cluster_name} — retrieve cluster status and member list
@router.get("/databases/cluster/{cluster_name}", response_model=DBClusterResponse)
def get_cluster(
    cluster_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return db_lb.get_cluster_details(
            db=db,
            username=current_user.username,
            user_id=current_user.id,
            cluster_name=cluster_name,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch cluster details: {e}")
