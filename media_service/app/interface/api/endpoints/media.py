import uuid
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional

from ....infrastructure.minio_client import generate_presigned_upload, generate_presigned_download, delete_object
from ....infrastructure.cloudinary_client import (
    upload_to_cloudinary,
    is_cloudinary_available,
    delete_from_cloudinary,
    is_cloudinary_url,
)
from ....infrastructure.compression import get_media_type, compress_image, compress_video
from ..deps import get_current_user_id

router = APIRouter(prefix="/media", tags=["media"])


class UploadRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    purpose: str = "avatar"


class UploadResponse(BaseModel):
    upload_url: str
    object_name: str
    download_url: str


class CloudinaryUploadResponse(BaseModel):
    url: str
    secure_url: str
    public_id: str
    object_name: str


class DownloadRequest(BaseModel):
    object_name: str


@router.post("/upload", response_model=CloudinaryUploadResponse)
async def upload_media(
    file: UploadFile = File(...),
    purpose: str = "post",
    user_id: str = Depends(get_current_user_id),
):
    """Upload image or video: compress then upload to Cloudinary (round-robin across configured clouds)."""
    if not is_cloudinary_available():
        raise HTTPException(
            status_code=503,
            detail="Cloudinary not configured. Set CLOUDINARY_CLOUDS_JSON with at least one cloud.",
        )
    content_type = file.content_type or ""
    filename = file.filename or "upload"
    media_type = get_media_type(content_type, filename)
    if media_type not in ("image", "video"):
        raise HTTPException(
            status_code=400,
            detail="Only images (jpeg, png, webp, gif) and videos (mp4, webm, mov, avi) are allowed.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    if media_type == "image":
        data, content_type = compress_image(data, content_type, filename)
        resource_type = "image"
    else:
        data, content_type = compress_video(data, content_type, filename)
        resource_type = "video"

    folder = f"astu/{purpose}/{user_id}"
    public_id_prefix = f"{folder}/{uuid.uuid4().hex}"

    try:
        result = upload_to_cloudinary(
            file_bytes=data,
            resource_type=resource_type,
            folder=folder,
            public_id_prefix=public_id_prefix,
        )
        return CloudinaryUploadResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cloudinary upload failed: {e}")


@router.post("/upload-url", response_model=UploadResponse)
def get_upload_url(req: UploadRequest, user_id: str = Depends(get_current_user_id)):
    """Legacy MinIO presigned URL (use /upload for Cloudinary with compression)."""
    ext = req.filename.rsplit(".", 1)[-1] if "." in req.filename else "bin"
    object_name = f"{req.purpose}/{user_id}/{uuid.uuid4()}.{ext}"
    upload_url = generate_presigned_upload(object_name)
    download_url = generate_presigned_download(object_name)
    return UploadResponse(upload_url=upload_url, object_name=object_name, download_url=download_url)


@router.post("/download-url")
def get_download_url(req: DownloadRequest, user_id: str = Depends(get_current_user_id)):
    """Return download URL. If object_name is already a full URL (e.g. Cloudinary), return as-is; else MinIO presigned."""
    if req.object_name.startswith("http://") or req.object_name.startswith("https://"):
        return {"download_url": req.object_name}
    try:
        url = generate_presigned_download(req.object_name)
        return {"download_url": url}
    except Exception:
        raise HTTPException(status_code=404, detail="Object not found")


@router.delete("/{object_name:path}")
def delete_media(object_name: str, user_id: str = Depends(get_current_user_id)):
    # Cloudinary: allow delete if URL path contains this user's id (e.g. /astu/post/<user_id>/)
    if is_cloudinary_url(object_name):
        if f"/{user_id}/" not in object_name and not object_name.endswith(f"/{user_id}"):
            raise HTTPException(status_code=403, detail="Not authorized to delete this file")
        if delete_from_cloudinary(object_name):
            return {"status": "deleted"}
        raise HTTPException(status_code=404, detail="Cloudinary delete failed or resource not found")
    # MinIO: allow only avatar or post paths for this user
    if not object_name.startswith(f"avatar/{user_id}/") and not object_name.startswith(f"post/{user_id}/"):
        raise HTTPException(status_code=403, detail="Not authorized to delete this file")
    try:
        delete_object(object_name)
        return {"status": "deleted"}
    except Exception:
        raise HTTPException(status_code=404, detail="Object not found")
