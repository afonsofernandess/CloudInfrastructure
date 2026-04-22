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
