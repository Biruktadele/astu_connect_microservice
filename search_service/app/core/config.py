from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect Search Service"
    API_V1_STR: str = "/api/v1"
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
