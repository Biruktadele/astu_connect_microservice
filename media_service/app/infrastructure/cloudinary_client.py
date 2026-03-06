"""Cloudinary upload with round-robin across multiple clouds."""

import io
import logging
import re
import threading
import uuid
from typing import Optional

import cloudinary
import cloudinary.uploader

from ..core.config import settings

logger = logging.getLogger(__name__)

# Cloudinary URL pattern: https://res.cloudinary.com/<cloud_name>/<resource_type>/upload/...
_CLOUDINARY_URL_PATTERN = re.compile(
    r"https?://res\.cloudinary\.com/(?P<cloud_name>[^/]+)/(?P<resource_type>image|video)/upload/(?:v\d+/)?(?P<public_id>.+?)(?:\.[a-zA-Z0-9]+)?(?:\?|$)"
)

_rotation_lock = threading.Lock()
_rotation_index = 0


def _get_next_config() -> Optional[dict]:
    configs = settings.cloudinary_configs
    if not configs:
        return None
    global _rotation_index
    with _rotation_lock:
        idx = _rotation_index % len(configs)
        _rotation_index += 1
        return configs[idx].copy()


def upload_to_cloudinary(
    file_bytes: bytes,
    resource_type: str = "image",
    folder: str = "astu",
    public_id_prefix: Optional[str] = None,
) -> dict:
    """
    Upload bytes to the next Cloudinary cloud in rotation.
    Returns dict with url, secure_url, public_id, and object_name (for compatibility with feed media_refs).
    """
    config = _get_next_config()
    if not config:
        raise RuntimeError("No Cloudinary clouds configured. Set CLOUDINARY_CLOUDS_JSON.")

    cloudinary.config(
        cloud_name=config["cloud_name"],
        api_key=config["api_key"],
        api_secret=config["api_secret"],
    )

    public_id = public_id_prefix or f"{folder}/{uuid.uuid4().hex}"

    result = cloudinary.uploader.upload(
        io.BytesIO(file_bytes),
        resource_type=resource_type,
        public_id=public_id,
        overwrite=True,
    )

    secure_url = result.get("secure_url") or result.get("url", "")
    return {
        "url": secure_url,
        "secure_url": secure_url,
        "public_id": result.get("public_id", public_id),
        "object_name": secure_url,
    }


def is_cloudinary_available() -> bool:
    return len(settings.cloudinary_configs) > 0


def delete_from_cloudinary(cloudinary_url: str) -> bool:
    """
    Delete an asset from Cloudinary by its URL.
    Parses cloud_name, resource_type, and public_id from the URL and calls destroy.
    Returns True if deleted, False if URL not recognized or delete failed.
    """
    match = _CLOUDINARY_URL_PATTERN.match(cloudinary_url.strip())
    if not match:
        logger.warning("Not a Cloudinary URL: %s", cloudinary_url[:80])
        return False

    cloud_name = match.group("cloud_name")
    resource_type = match.group("resource_type")
    public_id = match.group("public_id").rstrip("/")
    if not public_id:
        return False

    configs = settings.cloudinary_configs
    config = next((c for c in configs if c["cloud_name"] == cloud_name), configs[0] if configs else None)
    if not config:
        logger.warning("No Cloudinary config for cloud_name=%s", cloud_name)
        return False

    cloudinary.config(
        cloud_name=config["cloud_name"],
        api_key=config["api_key"],
        api_secret=config["api_secret"],
    )

    try:
        result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
        if result.get("result") == "ok":
            logger.info("Deleted from Cloudinary: public_id=%s", public_id)
            return True
        logger.warning("Cloudinary destroy result: %s", result.get("result"))
        return False
    except Exception as e:
        logger.exception("Cloudinary delete failed: %s", e)
        return False


def is_cloudinary_url(value: str) -> bool:
    """Return True if value looks like a Cloudinary resource URL."""
    return "res.cloudinary.com" in (value or "")
