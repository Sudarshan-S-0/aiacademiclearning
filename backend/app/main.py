from time import monotonic
import math
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.api.routes import router
from app.api.extended_routes import router as extended_router

# Database schema changes are managed by Alembic. Run `alembic upgrade head`
# as a deployment step before starting the application.


def _json_safe_validation_value(value):
    """Make validation details JSON-safe even when the rejected input is NaN/Infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_validation_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_validation_value(item) for item in value]
    if isinstance(value, BaseException):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    # Pydantic may include the original invalid input in its error details.
    # Non-finite floats are not valid JSON, so sanitize before serializing the 422.
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe_validation_value(exc.errors())},
    )


app=FastAPI(title="AI Academic Teaching and Learning System",version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

# Process-local guardrail for authentication and AI endpoints. For multi-worker
# deployments, use a shared rate-limit store (for example Redis) instead.
_hits: dict[str, list[float]] = {}
_last_rate_limit_cleanup = 0.0
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 60
_RATE_LIMIT_MAX_CLIENTS = 10_000
_RATE_LIMIT_CLEANUP_INTERVAL = 300


def _prune_rate_limit_hits(now: float) -> None:
    """Remove expired timestamps and inactive client keys to bound memory use."""
    for client_key, timestamps in list(_hits.items()):
        recent = [stamp for stamp in timestamps if now - stamp < _RATE_LIMIT_WINDOW_SECONDS]
        if recent:
            _hits[client_key] = recent
        else:
            _hits.pop(client_key, None)


@app.middleware("http")
async def simple_rate_limit(request: Request, call_next):
    global _last_rate_limit_cleanup
    if request.url.path.startswith("/api/auth") or request.url.path.startswith("/api/ai"):
        key = request.client.host if request.client else "unknown"
        now = monotonic()
        if now - _last_rate_limit_cleanup >= _RATE_LIMIT_CLEANUP_INTERVAL or len(_hits) >= _RATE_LIMIT_MAX_CLIENTS:
            _prune_rate_limit_hits(now)
            _last_rate_limit_cleanup = now
        if key not in _hits and len(_hits) >= _RATE_LIMIT_MAX_CLIENTS:
            return JSONResponse({"detail": "Rate limit capacity reached. Try again shortly."}, status_code=429)
        bucket = [stamp for stamp in _hits.get(key, []) if now - stamp < _RATE_LIMIT_WINDOW_SECONDS]
        if len(bucket) >= _RATE_LIMIT_MAX_REQUESTS:
            _hits[key] = bucket
            return JSONResponse({"detail": "Rate limit exceeded. Try again shortly."}, status_code=429)
        bucket.append(now)
        _hits[key] = bucket
    return await call_next(request)


app.include_router(router)
app.include_router(extended_router)
