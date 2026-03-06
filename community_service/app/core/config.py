from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect Community Service"
    API_V1_STR: str = "/api/v1"

    COMMUNITY_DATABASE_URL: str = "postgresql://community_user:community_pass@localhost:5434/community_db"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
