from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./eve.db"
    jwt_secret: str = "development-only-change-this-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    payment_success: bool = True
    log_level: str = "INFO"
    auth_requests_per_minute: int = Field(default=10, gt=0)
    booking_requests_per_minute: int = Field(default=30, gt=0)
    payment_requests_per_minute: int = Field(default=30, gt=0)
    webhook_requests_per_minute: int = Field(default=120, gt=0)
    redis_url: str | None = None
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    cache_ttl_seconds: int = Field(default=60, gt=0)
    admin_api_key: str | None = None
    admin_requests_per_minute: int = Field(default=30, gt=0)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
