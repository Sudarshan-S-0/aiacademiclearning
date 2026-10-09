import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_settings_reject_demo_secrets_and_local_origins():
    with pytest.raises(ValidationError, match="Invalid production configuration"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://app:secure-password@db.internal:5432/academic",
            cors_origins="http://localhost:5173",
            jwt_secret="change-this-in-production",
            minio_access_key="minio",
            minio_secret_key="minio123",
        )


def test_production_settings_accept_explicit_secure_values():
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://app:secure-password@db.internal:5432/academic",
        cors_origins="https://academic.example.com",
        jwt_secret="a-unique-production-secret-with-more-than-32-chars",
        minio_endpoint="minio.internal:9000",
        minio_access_key="academic-service",
        minio_secret_key="a-unique-object-storage-secret",
    )

    assert settings.environment == "production"
    assert settings.cors_origins == "https://academic.example.com"
