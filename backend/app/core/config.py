from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    database_url:str="postgresql+psycopg://postgres:postgres@localhost:5432/academic_lms"
    cors_origins:str="http://localhost:5173"
    jwt_secret:str="change-this-in-production"
    gemini_api_key:str=""
    gemini_model:str="gemini-2.0-flash"
    qdrant_url:str="http://localhost:6333"
    minio_endpoint:str="localhost:9000"
    minio_access_key:str="minio"
    minio_secret_key:str="minio123"
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
settings=Settings()
