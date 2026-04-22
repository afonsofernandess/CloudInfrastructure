"""
MinIO client wrapper.
Each user gets their own bucket: user-{username}
Buckets are created automatically on first use.
"""

from minio import Minio
from minio.error import S3Error
from io import BytesIO

MINIO_ENDPOINT  = "localhost:9002"
MINIO_ACCESS    = "minioadmin"
MINIO_SECRET    = "minioadmin123"
MINIO_SECURE    = False   # no TLS in local setup


def get_client() -> Minio:
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS, secret_key=MINIO_SECRET, secure=MINIO_SECURE)


def bucket_for(username: str) -> str:
    """Return the bucket name for a given user."""
    return f"user-{username.lower()}"


def ensure_bucket(username: str) -> str:
    """Create the user's bucket if it doesn't exist yet. Returns bucket name."""
    client = get_client()
    name = bucket_for(username)
    if not client.bucket_exists(name):
        client.make_bucket(name)
    return name


def upload_file(username: str, filename: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to the user's bucket. Returns the object name."""
    bucket = ensure_bucket(username)
    client = get_client()
    client.put_object(bucket, filename, BytesIO(data), length=len(data), content_type=content_type)
    return filename


def list_files(username: str) -> list[dict]:
    """List all objects in the user's bucket."""
    bucket = ensure_bucket(username)
    client = get_client()
    objects = client.list_objects(bucket)
    return [
        {
            "filename": obj.object_name,
            "size_bytes": obj.size,
            "last_modified": obj.last_modified,
        }
        for obj in objects
    ]


def download_file(username: str, filename: str) -> bytes:
    """Download an object from the user's bucket. Returns raw bytes."""
    bucket = ensure_bucket(username)
    client = get_client()
    try:
        response = client.get_object(bucket, filename)
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_file(username: str, filename: str) -> None:
    """Delete an object from the user's bucket."""
    bucket = ensure_bucket(username)
    client = get_client()
    try:
        client.remove_object(bucket, filename)
    except S3Error as e:
        if e.code == "NoSuchKey":
            raise FileNotFoundError(f"File '{filename}' not found")
        raise
