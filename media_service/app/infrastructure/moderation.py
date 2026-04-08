"""Content moderation using NudeNet for NSFW detection."""

import io
import logging
import os
import subprocess
import tempfile
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)

_detector = None

NSFW_LABELS = {
    "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED", "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED", "FEMALE_BREAST_COVERED",
}


def _get_detector():
    global _detector
    if _detector is None:
        try:
            from nudenet import NudeDetector
            _detector = NudeDetector()
            logger.info("NudeNet detector loaded")
        except Exception:
            logger.exception("Failed to load NudeNet detector")
    return _detector


def scan_image(image_bytes: bytes) -> dict:
    """Scan image bytes for NSFW content.

    Returns {"is_flagged": bool, "labels": [...], "max_score": float}
    """
    if not settings.CONTENT_MODERATION_ENABLED:
        return {"is_flagged": False, "labels": [], "max_score": 0.0}

    detector = _get_detector()
    if detector is None:
        return {"is_flagged": False, "labels": [], "max_score": 0.0}

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(image_bytes)
        tmp_path = f.name

    try:
        detections = detector.detect(tmp_path)
        flagged_labels = []
        max_score = 0.0

        for det in detections:
            label = det.get("class", "")
            score = det.get("score", 0.0)
            if label in NSFW_LABELS and score >= settings.NSFW_THRESHOLD:
                flagged_labels.append(label)
                max_score = max(max_score, score)

        return {
            "is_flagged": len(flagged_labels) > 0,
            "labels": flagged_labels,
            "max_score": round(max_score, 3),
        }
    except Exception:
        logger.exception("NudeNet scan failed")
        return {"is_flagged": False, "labels": [], "max_score": 0.0}
    finally:
        os.unlink(tmp_path)


def scan_video(video_bytes: bytes) -> dict:
    """Extract frames from video and scan each for NSFW content."""
    if not settings.CONTENT_MODERATION_ENABLED:
        return {"is_flagged": False, "labels": [], "max_score": 0.0}

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        video_path = f.name

    frame_dir = tempfile.mkdtemp()
    try:
        subprocess.run(
            [
                "ffmpeg", "-i", video_path,
                "-vf", "select='eq(n\\,0)+eq(n\\,30)+eq(n\\,60)'",
                "-vsync", "vfn", "-frames:v", "3",
                os.path.join(frame_dir, "frame_%02d.jpg"),
            ],
            capture_output=True, timeout=30,
        )

        all_labels = []
        max_score = 0.0

        for fname in sorted(os.listdir(frame_dir)):
            fpath = os.path.join(frame_dir, fname)
            with open(fpath, "rb") as img_f:
                result = scan_image(img_f.read())
            all_labels.extend(result["labels"])
            max_score = max(max_score, result["max_score"])

        unique_labels = list(set(all_labels))
        return {
            "is_flagged": len(unique_labels) > 0,
            "labels": unique_labels,
            "max_score": round(max_score, 3),
        }
    except Exception:
        logger.exception("Video moderation scan failed")
        return {"is_flagged": False, "labels": [], "max_score": 0.0}
    finally:
        os.unlink(video_path)
        import shutil
        shutil.rmtree(frame_dir, ignore_errors=True)
