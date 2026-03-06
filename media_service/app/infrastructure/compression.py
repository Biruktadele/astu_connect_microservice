"""Compress images and videos before upload."""

import io
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Tuple

from PIL import Image

from ..core.config import settings

logger = logging.getLogger(__name__)

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}


def _is_image(content_type: str, filename: str) -> bool:
    if content_type and content_type.split(";")[0].strip().lower() in IMAGE_TYPES:
        return True
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return ext in ("jpg", "jpeg", "png", "webp", "gif")


def _is_video(content_type: str, filename: str) -> bool:
    if content_type and content_type.split(";")[0].strip().lower() in VIDEO_TYPES:
        return True
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return ext in ("mp4", "webm", "mov", "avi")


def get_media_type(content_type: str, filename: str) -> str:
    if _is_image(content_type, filename):
        return "image"
    if _is_video(content_type, filename):
        return "video"
    return "unknown"


def compress_image(data: bytes, content_type: str, filename: str) -> Tuple[bytes, str]:
    """Compress image: resize if too large, reduce quality. Returns (bytes, new_content_type)."""
    try:
        img = Image.open(io.BytesIO(data))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        w, h = img.size
        max_sz = settings.IMAGE_MAX_SIZE_PX
        if w > max_sz or h > max_sz:
            img.thumbnail((max_sz, max_sz), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=settings.IMAGE_JPEG_QUALITY, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception as e:
        logger.warning("Image compression failed, using original: %s", e)
        return data, (content_type or "image/jpeg")


def compress_video(data: bytes, content_type: str, filename: str) -> Tuple[bytes, str]:
    """Compress video with ffmpeg. Returns (bytes, new_content_type). If ffmpeg missing, returns original."""
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg not installed, skipping video compression")
        return data, (content_type or "video/mp4")
    suffix = ".mp4"
    if filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in ("webm", "mov", "avi"):
            suffix = f".{ext}"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fin:
            fin.write(data)
            in_path = fin.name
        out_path = in_path + ".out.mp4"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", in_path,
                    "-c:v", "libx264", "-crf", str(settings.VIDEO_CRF),
                    "-preset", settings.VIDEO_PRESET, "-movflags", "+faststart",
                    "-c:a", "aac", "-b:a", settings.VIDEO_AUDIO_BITRATE,
                    out_path,
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
            with open(out_path, "rb") as f:
                result = f.read()
            return result, "video/mp4"
        finally:
            for p in (in_path, out_path):
                if os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Video compression failed, using original: %s", e)
        return data, (content_type or "video/mp4")
