from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class FileInfo(BaseModel):
    filename: str
    size_bytes: Optional[int] = None
    last_modified: Optional[datetime] = None


class UploadResponse(BaseModel):
    filename: str
    bucket: str
    size_bytes: int
    message: str


class DiskCreate(BaseModel):
    name: str
    size_gb: int


class DiskResponse(BaseModel):
    id: int
    one_image_id: int
    name: str
    size_gb: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


