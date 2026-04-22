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
