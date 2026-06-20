from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/mneme"
    REDIS_URL: str = "redis://localhost:6380/0"
    ANTHROPIC_API_KEY: str = "your_key_here"
    DEEPSEEK_API_KEY: str = "your_key_here"
    QWEN_API_KEY: str = "your_key_here"
    DASHSCOPE_API_KEY: str = "your_key_here"
    OPENAI_API_KEY: str = "your_key_here"
    GEMINI_API_KEY: str = "your_key_here"

    MINIO_ENDPOINT: str = "localhost:9002"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "mneme"

    JWT_SECRET: str = "mneme-dev-secret-change-in-prod!"
    JWT_EXPIRE_SECONDS: int = 86400 * 7  # 7 days

    ALIYUN_ACCESS_KEY_ID: str = ""
    ALIYUN_ACCESS_KEY_SECRET: str = ""
    ALIYUN_NLS_APP_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
