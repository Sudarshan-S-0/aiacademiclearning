from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/academic_lms"
    cors_origins: str = "http://localhost:5173"
    jwt_secret: str = "change-this-in-production"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    qdrant_url: str = "http://localhost:6333"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "minio123"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.environment.strip().lower() not in {"production", "prod"}:
            return self

        problems = []
        if self.jwt_secret == "change-this-in-production" or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a unique secret with at least 32 characters")

        database = urlsplit(self.database_url)
        if not database.hostname or database.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
            problems.append("DATABASE_URL must point to a non-local database host")

        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        if not origins or any(
            (urlsplit(origin).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
            for origin in origins
        ):
            problems.append("CORS_ORIGINS must contain explicit non-local frontend origins")

        if self.minio_access_key == "minio" or self.minio_secret_key == "minio123":
            problems.append("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must not use demo credentials")

        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self


settings = Settings()
