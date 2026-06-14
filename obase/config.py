from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/mneme"
    REDIS_URL: str = "redis://localhost:6380/0"
    ANTHROPIC_API_KEY: str = "your_key_here"

    MINIO_ENDPOINT: str = "localhost:9002"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "mneme"

    JWT_SECRET: str = "mneme-dev-secret-change-in-prod!"
    JWT_EXPIRE_SECONDS: int = 86400 * 7  # 7 days

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
