import io
from app.core.config import settings
try:
    from minio import Minio
except Exception: Minio=None
BUCKET='academic-resources'
def client():
    if not Minio:return None
    try:
        c=Minio(settings.minio_endpoint,access_key=settings.minio_access_key,secret_key=settings.minio_secret_key,secure=settings.minio_secure)
        if not c.bucket_exists(BUCKET):c.make_bucket(BUCKET)
        return c
    except Exception:
        return None
def put_object(key,data,content_type='application/octet-stream'):
    try:
        c=client()
        if not c:return False
        c.put_object(BUCKET,key,io.BytesIO(data),len(data),content_type=content_type)
        return True
    except Exception:
        return False
def get_object(key):
    try:
        c=client()
        if not c:return None
        r=c.get_object(BUCKET,key)
        try:return r.read()
        finally:r.close();r.release_conn()
    except Exception:return None
