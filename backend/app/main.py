import logging
from time import monotonic
from collections import defaultdict
from fastapi import FastAPI,Request
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.session import Base,engine
from app.api.routes import router
from app.api.extended_routes import router as extended_router
from app.models import models

logger = logging.getLogger(__name__)
Base.metadata.create_all(bind=engine)

def apply_compat_migrations():
    statements = [
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS parent_resource_id INTEGER REFERENCES resources(id)",
        "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)",
        "ALTER TABLE pyq_questions ADD COLUMN IF NOT EXISTS mapping_confidence FLOAT",
    ]
    try:
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                for statement in statements:
                    conn.execute(text(statement))
    except Exception:
        # Never hide a schema-compatibility failure in production: the app could
        # otherwise start against a database with missing columns.
        if settings.environment.strip().lower() in {"production", "prod"}:
            raise
        logger.exception("Compatibility migration failed; development startup will continue")

apply_compat_migrations()

app=FastAPI(title="AI Academic Teaching and Learning System",version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

_hits=defaultdict(list)
@app.middleware("http")
async def simple_rate_limit(request:Request,call_next):
    if request.url.path.startswith("/api/auth") or request.url.path.startswith("/api/ai"):
        key=request.client.host if request.client else "unknown";now=monotonic();bucket=[x for x in _hits[key] if now-x<60]
        if len(bucket)>=60:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail":"Rate limit exceeded. Try again shortly."},status_code=429)
        bucket.append(now);_hits[key]=bucket
    return await call_next(request)

app.include_router(router)
app.include_router(extended_router)
