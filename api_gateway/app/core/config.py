from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect API Gateway"

    IDENTITY_SERVICE_URL: str = "http://identity-service:8000"
    FEED_SERVICE_URL: str = "http://feed-service:8000"
    CHAT_SERVICE_URL: str = "http://chat-service:8000"
    COMMUNITY_SERVICE_URL: str = "http://community-service:8000"
    NOTIFICATION_SERVICE_URL: str = "http://notification-service:8000"
    MEDIA_SERVICE_URL: str = "http://media-service:8000"
    SEARCH_SERVICE_URL: str = "http://search-service:8000"
    GAMIFICATION_SERVICE_URL: str = "http://gamification-service:8000"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"

    RATE_LIMIT_PER_MINUTE: int = 120
    RATE_LIMIT_AUTH_PER_MINUTE: int = 20

    # Comma-separated list of allowed CORS origins
    CORS_ORIGINS: str = "http://localhost:3000"

    # Redis URL used for distributed rate limiting (uses redis-feed)
    REDIS_URL: str = "redis://redis-feed:6379/0"

    # Set to true in production to disable /docs and /redoc
    PRODUCTION: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
