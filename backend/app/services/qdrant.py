import hashlib, math, httpx
from app.core.config import settings
COLLECTION='academic_chunks'
def vector(text,n=64):
    raw=hashlib.sha256(text.encode()).digest(); vals=[(raw[i%len(raw)]/255)*2-1 for i in range(n)]; norm=math.sqrt(sum(v*v for v in vals)) or 1; return [v/norm for v in vals]
def upsert_chunks(resource_id,subject_id,chunks,source):
    if not settings.qdrant_url or not chunks:return False
    try:
        base=settings.qdrant_url.rstrip('/'); h=httpx.get(f'{base}/collections/{COLLECTION}',timeout=3)
        if h.status_code==404:httpx.put(f'{base}/collections/{COLLECTION}',json={'vectors':{'size':64,'distance':'Cosine'}},timeout=5).raise_for_status()
        points=[{'id':resource_id*100000+i,'vector':vector(ch),'payload':{'resource_id':resource_id,'subject_id':subject_id,'source':source,'text':ch}} for i,ch in enumerate(chunks)]
        httpx.put(f'{base}/collections/{COLLECTION}/points',json={'points':points},timeout=20).raise_for_status();return True
    except Exception:return False
