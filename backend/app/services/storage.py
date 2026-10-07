import io
from app.core.config import settings
try:
    from minio import Minio
except Exception: Minio=None
BUCKET='academic-resources'
def client():
    if not Minio:return None
    c=Minio(settings.minio_endpoint,access_key=settings.minio_access_key,secret_key=settings.minio_secret_key,secure=False)
    if not c.bucket_exists(BUCKET):c.make_bucket(BUCKET)
    return c
def put_object(key,data,content_type='application/octet-stream'):
    c=client()
    if not c:return False
    c.put_object(BUCKET,key,io.BytesIO(data),len(data),content_type=content_type);return True
def get_object(key):
    c=client()
    if not c:return None
    try:
        r=c.get_object(BUCKET,key)
        try:return r.read()
        finally:r.close();r.release_conn()
    except Exception:return None
