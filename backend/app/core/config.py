from typing import Optional, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Настройки приложения.

    Все настройки загружаются из переменных окружения или .env файла.
    Значения по умолчанию указаны в полях класса.
    """

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEBUG: bool = True

    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "places_db"
    POSTGRES_USER: str = "places_user"
    POSTGRES_PASSWORD: str = "places_password"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "places"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    SESSION_TTL: int = 86400  # 24 hours

    # OpenAI / LLM
    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENAI_API_KEY: str = ""  # ОБЯЗАТЕЛЬНО: укажите в .env
    OPENAI_MODEL: str = "google/gemini-2.5-flash"
    OPENAI_TEMPERATURE: float = 0.7

    # Embeddings
    OPENAI_EMBEDDING_BASE_URL: str = "https://localhost:1234/v1"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-bge-m3"
    OPENAI_EMBEDDING_DIM: int = 1024

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""  # ОБЯЗАТЕЛЬНО: укажите в .env

    # Security
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_RANDOM_STRING"  # ОБЯЗАТЕЛЬНО: укажите в .env
    JWT_ALGORITHM: str = "HS256"
    BOT_API_TOKEN: str = ""  # ОБЯЗАТЕЛЬНО: укажите в .env
    ALLOWED_ORIGINS: Union[str, list[str]] = ["http://localhost:3000", "http://localhost:8080"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        import json

        if isinstance(v, list):
            return v

        if not v or (isinstance(v, str) and not v.strip()):
            return []

        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("["):
                try:
                    parsed = json.loads(v_stripped)
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass

            return [origin.strip() for origin in v_stripped.split(",") if origin.strip()]

        return v

    @field_validator("ALLOWED_ORIGINS", mode="after")
    @classmethod
    def ensure_allowed_origins_is_list(cls, v):
        if not isinstance(v, list):
            return []
        return v

    # Phoenix Tracing
    PHOENIX_ENABLED: bool = True
    PHOENIX_ENDPOINT: str = "http://localhost:6006/v1/traces"
    PHOENIX_PROJECT_NAME: str = "places-recommendation-agent"

    @property
    def postgres_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
