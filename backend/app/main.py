from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.session import Base,engine
from app.api.routes import router
from app.models import models
Base.metadata.create_all(bind=engine)
app=FastAPI(title="AI Academic Teaching and Learning System",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router)
