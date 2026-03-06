from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect Feed Service"
    API_V1_STR: str = "/api/v1"

    FEED_DATABASE_URL: str = "postgresql://feed_user:feed_pass@localhost:5433/feed_db"
    FEED_REDIS_URL: str = "redis://localhost:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    IDENTITY_SERVICE_URL: str = "http://identity-service:8000"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"

    CELEBRITY_THRESHOLD: int = 1000
    TIMELINE_MAX_SIZE: int = 800

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
