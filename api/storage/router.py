from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response

from api.auth.jwt import get_current_user
from api.auth.models import User
from api.storage.schemas import FileInfo, UploadResponse
from api.storage.minio_client import (
    upload_file, list_files, download_file, delete_file, bucket_for
)

router = APIRouter(prefix="/storage", tags=["storage"])


# POST /storage/upload — upload a file
@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    data = await file.read()
    try:
        upload_file(current_user.username, file.filename, data, file.content_type or "application/octet-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    return {
        "filename": file.filename,
        "bucket": bucket_for(current_user.username),
        "size_bytes": len(data),
        "message": "File uploaded successfully",
    }


# GET /storage/files — list user's files
@router.get("/files", response_model=list[FileInfo])
def list_user_files(current_user: User = Depends(get_current_user)):
    try:
        return list_files(current_user.username)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not list files: {e}")


# GET /storage/download/{filename} — download a file
@router.get("/download/{filename}")
def download(filename: str, current_user: User = Depends(get_current_user)):
    try:
        data = download_file(current_user.username, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# DELETE /storage/files/{filename} — delete a file
@router.delete("/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete(filename: str, current_user: User = Depends(get_current_user)):
    try:
        delete_file(current_user.username, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


from sqlalchemy.orm import Session
from api.database import get_db
from api.storage.models import DiskInstance
from api.storage.schemas import DiskCreate, DiskResponse
from opennebula import disk_manager as one_disk_manager


# POST /storage/disks — provision a new persistent disk
@router.post("/disks", response_model=DiskResponse, status_code=status.HTTP_201_CREATED)
def create_user_disk(
    data: DiskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.one_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your user is not registered in OpenNebula. Please contact admin."
        )

    try:
        one_image_id = one_disk_manager.create_disk(data.name, data.size_gb, current_user.one_user_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OpenNebula image allocation failed: {e}"
        )

    disk = DiskInstance(
        user_id=current_user.id,
        one_image_id=one_image_id,
        name=data.name,
        size_gb=data.size_gb,
    )
    db.add(disk)
    db.commit()
    db.refresh(disk)

    # Retrieve live status
    status_str = one_disk_manager.get_disk_status(one_image_id)

    return DiskResponse(
        id=disk.id,
        one_image_id=disk.one_image_id,
        name=disk.name,
        size_gb=disk.size_gb,
        status=status_str,
        created_at=disk.created_at,
    )


# GET /storage/disks — list user's disks
@router.get("/disks", response_model=list[DiskResponse])
def list_user_disks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    disks = db.query(DiskInstance).filter(DiskInstance.user_id == current_user.id).all()
    res = []
    for d in disks:
        status_str = one_disk_manager.get_disk_status(d.one_image_id)
        res.append(
            DiskResponse(
                id=d.id,
                one_image_id=d.one_image_id,
                name=d.name,
                size_gb=d.size_gb,
                status=status_str,
                created_at=d.created_at,
            )
        )
    return res


# DELETE /storage/disks/{disk_id} — delete a disk
@router.delete("/disks/{disk_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_disk(
    disk_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    disk = db.query(DiskInstance).filter(
        DiskInstance.id == disk_id,
        DiskInstance.user_id == current_user.id,
    ).first()
    if not disk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disk not found"
        )

    # Get status first. If locked, we explain.
    status_str = one_disk_manager.get_disk_status(disk.one_image_id)
    if status_str in ("LOCKED", "CLONE"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disk is currently locked or cloning in OpenNebula. Please wait."
        )

    try:
        one_disk_manager.delete_disk(disk.one_image_id)
    except Exception as e:
        if "Image not found" in str(e) or "not found" in str(e).lower():
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"OpenNebula disk deletion failed: {e}"
            )

    db.delete(disk)
    db.commit()

