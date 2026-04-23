from fastapi import APIRouter, Depends, HTTPException, status

from api.auth.jwt import get_current_user
from api.auth.models import User
from api.containers.schemas import ContainerCreate, ContainerResponse
from api.containers.docker_client import (
    launch_container, list_containers, get_container,
    start_container, stop_container, remove_container,
)

router = APIRouter(prefix="/containers", tags=["containers"])


# POST /containers — launch a container
@router.post("", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED)
def launch(data: ContainerCreate, current_user: User = Depends(get_current_user)):
    try:
        return launch_container(
            username=current_user.username,
            image=data.image,
            name=data.name,
            env=data.env,
            ports=data.ports,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch container: {e}")


# GET /containers — list user's containers
@router.get("", response_model=list[ContainerResponse])
def list_user_containers(current_user: User = Depends(get_current_user)):
    try:
        return list_containers(current_user.username)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list containers: {e}")


# GET /containers/{container_id} — get container details
@router.get("/{container_id}", response_model=ContainerResponse)
def get_container_detail(container_id: str, current_user: User = Depends(get_current_user)):
    try:
        return get_container(current_user.username, container_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# POST /containers/{container_id}/start — start a stopped container
@router.post("/{container_id}/start", response_model=ContainerResponse)
def start(container_id: str, current_user: User = Depends(get_current_user)):
    try:
        return start_container(current_user.username, container_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start container: {e}")


# POST /containers/{container_id}/stop — stop a running container
@router.post("/{container_id}/stop", response_model=ContainerResponse)
def stop(container_id: str, current_user: User = Depends(get_current_user)):
    try:
        return stop_container(current_user.username, container_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop container: {e}")


# DELETE /containers/{container_id} — remove a container
@router.delete("/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(container_id: str, current_user: User = Depends(get_current_user)):
    try:
        remove_container(current_user.username, container_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove container: {e}")
