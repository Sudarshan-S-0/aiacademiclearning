from time import monotonic
from collections import defaultdict
from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.session import Base,engine
from app.api.routes import router
from app.models import models
Base.metadata.create_all(bind=engine)

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
