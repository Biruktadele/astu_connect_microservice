import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect Media Service"
    API_V1_STR: str = "/api/v1"
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "astu-media"
    MINIO_USE_SSL: bool = False
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"

    CONTENT_MODERATION_ENABLED: bool = True
    NSFW_THRESHOLD: float = 0.45

    FEED_REDIS_URL: str = "redis://redis-feed:6379/0"

    # Cloudinary: JSON array of {"cloud_name", "api_key", "api_secret"} for multi-cloud rotation
    CLOUDINARY_CLOUDS_JSON: str = ""

    # Image compression
    IMAGE_MAX_SIZE_PX: int = 1920
    IMAGE_JPEG_QUALITY: int = 85

    # Video compression (ffmpeg)
    VIDEO_CRF: int = 28
    VIDEO_PRESET: str = "fast"
    VIDEO_AUDIO_BITRATE: str = "128k"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("CLOUDINARY_CLOUDS_JSON", mode="before")
    @classmethod
    def parse_cloudinary_clouds(cls, v: Any) -> str:
        return v or ""

    @property
    def cloudinary_configs(self) -> list[dict[str, str]]:
        if not self.CLOUDINARY_CLOUDS_JSON.strip():
            return []
        try:
            data = json.loads(self.CLOUDINARY_CLOUDS_JSON)
            if not isinstance(data, list):
                return []
            out = []
            for item in data:
                if isinstance(item, dict) and "cloud_name" in item and "api_key" in item and "api_secret" in item:
                    out.append({
                        "cloud_name": str(item["cloud_name"]),
                        "api_key": str(item["api_key"]),
                        "api_secret": str(item["api_secret"]),
                    })
            return out
        except (json.JSONDecodeError, TypeError):
            return []


settings = Settings()
