from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect Identity Service"
    API_V1_STR: str = "/api/v1"

    IDENTITY_DATABASE_URL: str = "postgresql://identity_user:identity_pass@localhost:5432/identity_db"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Email (SMTP) — for verification link and forgot-password OTP
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@astu.edu.et"
    SMTP_FROM_NAME: str = "ASTU Connect"
    SMTP_USE_TLS: bool = True

    # App URL for verification link (no trailing slash)
    APP_BASE_URL: str = "http://localhost:8000"
    VERIFY_EMAIL_PATH: str = "/verify-email"

    # Email verification token expiry (hours)
    VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # Forgot-password OTP
    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 15

    # Require email_verified for login (default True)
    REQUIRE_EMAIL_VERIFICATION: bool = True

    INITIAL_ADMIN_EMAIL: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
