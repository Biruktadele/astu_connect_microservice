import logging
from datetime import timedelta
from minio import Minio
from ..core.config import settings

logger = logging.getLogger(__name__)

_client = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_USE_SSL,
        )
        if not _client.bucket_exists(settings.MINIO_BUCKET):
            _client.make_bucket(settings.MINIO_BUCKET)
            logger.info("Created bucket %s", settings.MINIO_BUCKET)
    return _client


def generate_presigned_upload(object_name: str, expires_hours: int = 1) -> str:
    client = get_minio_client()
    url = client.presigned_put_object(
        settings.MINIO_BUCKET, object_name,
        expires=timedelta(hours=expires_hours),
    )
    return url


def generate_presigned_download(object_name: str, expires_hours: int = 24) -> str:
    client = get_minio_client()
    url = client.presigned_get_object(
        settings.MINIO_BUCKET, object_name,
        expires=timedelta(hours=expires_hours),
    )
    return url


def delete_object(object_name: str) -> None:
    client = get_minio_client()
    client.remove_object(settings.MINIO_BUCKET, object_name)
