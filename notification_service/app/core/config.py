from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect Notification Service"
    API_V1_STR: str = "/api/v1"
    NOTIFICATION_DATABASE_URL: str = "postgresql://notification_user:notification_pass@localhost:5435/notification_db"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
