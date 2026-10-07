import hashlib,httpx
from app.core.config import settings
COLLECTION='academic_chunks_v2'
MODEL_NAME='all-MiniLM-L6-v2'
_model=None

def embed(text:str)->list[float]:
    global _model
    try:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model=SentenceTransformer(MODEL_NAME)
        return _model.encode(text,normalize_embeddings=True).tolist()
    except Exception:
        raw=hashlib.sha256(text.encode()).digest()
        return [((raw[i%len(raw)]/255)*2-1) for i in range(384)]

def ensure_collection():
    if not settings.qdrant_url:return False
    base=settings.qdrant_url.rstrip('/')
    try:
        r=httpx.get(f'{base}/collections/{COLLECTION}',timeout=4)
        if r.status_code==404:
            httpx.put(f'{base}/collections/{COLLECTION}',json={'vectors':{'size':384,'distance':'Cosine'}},timeout=8).raise_for_status()
        return True
    except Exception:return False

def upsert_chunks(resource_id,subject_id,chunks,source,status='DRAFT'):
    if not chunks or not ensure_collection():return False
    points=[]
    for i,c in enumerate(chunks):
        if isinstance(c, str):
            c={'text':c,'page':None,'section':None}
        pid=int(hashlib.sha1(f'{resource_id}:{i}'.encode()).hexdigest()[:15],16)
        points.append({'id':pid,'vector':embed(c['text']),'payload':{**c,'resource_id':resource_id,'subject_id':subject_id,'source':source,'status':status}})
    try:
        httpx.put(f'{settings.qdrant_url.rstrip("/")}/collections/{COLLECTION}/points',json={'points':points},timeout=90).raise_for_status();return True
    except Exception:return False

def set_resource_status(resource_id,status):
    if not settings.qdrant_url:return False
    try:
        base=settings.qdrant_url.rstrip('/')
        httpx.post(f'{base}/collections/{COLLECTION}/points/payload',json={'payload':{'status':status},'filter':{'must':[{'key':'resource_id','match':{'value':resource_id}}]}},timeout=20).raise_for_status()
        return True
    except Exception:return False

def search_chunks(subject_id,query,top_k=8):
    if not settings.qdrant_url or not ensure_collection():return []
    try:
        r=httpx.post(f'{settings.qdrant_url.rstrip("/")}/collections/{COLLECTION}/points/search',json={
            'vector':embed(query),'limit':top_k,'with_payload':True,
            'filter':{'must':[{'key':'subject_id','match':{'value':subject_id}},{'key':'status','match':{'value':'APPROVED'}}]}
        },timeout=90)
        if r.status_code>=400:
            r=httpx.post(f'{settings.qdrant_url.rstrip("/")}/collections/{COLLECTION}/points/query',json={'query':embed(query),'limit':top_k,'with_payload':True,'filter':{'must':[{'key':'subject_id','match':{'value':subject_id}},{'key':'status','match':{'value':'APPROVED'}}]}},timeout=90)
        r.raise_for_status();return [x.get('payload',{}) for x in r.json().get('result',[])]
    except Exception:return []
