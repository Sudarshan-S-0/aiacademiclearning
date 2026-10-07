from datetime import datetime,timezone
from collections import Counter,defaultdict
import json,re
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Query
from pydantic import BaseModel
from sqlalchemy import select,delete,func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import *
from app.api.routes import current_user,require_roles,can_access_subject,audit,approved_contexts,rebuild_plan,plan_rows,pyq_reanalyze,normalize_key
from app.services.document import extract_sections,extract_text,chunk_text
from app.services.qdrant import upsert_chunks,search_chunks,set_resource_status
from app.services.storage import put_object,get_object
from app.services.ai import grounded_answer,generate_structured,APPROVED_RESOURCE_MESSAGE
from app.services.artifacts import make_pptx,body_from_generated

router=APIRouter(prefix="/api")

class SyllabusCompareRequest(BaseModel):
    subject_id:int
    version:int|None=None
    topic_names:list[str]
    source_resource_id:int|None=None

class PlanEdit(BaseModel):
    action:str
    topic_id:int
    value:float|None=None
    new_week:int|None=None
    note:str|None=None

class AssignmentSubmit(BaseModel):
    content_id:int
    answer_text:str

class GenerateRequest(BaseModel):
    subject_id:int
    topic_id:int|None=None
    content_type:str
    title:str|None=None
    instructions:str|None=None

@router.post("/resources/upload-v2")
async def upload_resource_v2(subject_id:int,title:str,resource_type:str="REFERENCE",file:UploadFile=File(...),db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    data=await file.read()
    if len(data)>20*1024*1024:raise HTTPException(413,"Maximum file size is 20 MB")
    latest=db.scalar(select(Resource).where(Resource.subject_id==subject_id,Resource.title==title).order_by(Resource.version.desc()))
    version=(latest.version+1) if latest else 1
    text,pages=extract_text(file.filename,data);sections,_=extract_sections(file.filename,data)
    key=f"subjects/{subject_id}/resources/{version}-{re.sub(r'[^a-zA-Z0-9._-]','_',file.filename)}"
    stored=put_object(key,data,file.content_type or "application/octet-stream")
    r=Resource(subject_id=subject_id,uploaded_by=u.id,title=title,resource_type=resource_type.upper(),storage_key=key if stored else None,status="DRAFT",version=version,extracted_text=text,page_count=pages)
    db.add(r);db.flush();chunks=[]
    for sec in sections:
        for part in chunk_text(sec.get("text","")):chunks.append({"text":part,"page":sec.get("page"),"section":sec.get("section")})
    for i,c in enumerate(chunks):db.add(ResourceChunk(resource_id=r.id,subject_id=subject_id,chunk_index=i,text=c["text"],page_number=c.get("page"),section=c.get("section")))
    db.flush();upsert_chunks(r.id,subject_id,chunks,title,"DRAFT");audit(db,u,"UPLOAD_RESOURCE","RESOURCE",r.id,json.dumps({"version":version,"filename":file.filename,"chunks":len(chunks)}));db.commit()
    return {"id":r.id,"version":version,"status":"DRAFT","pages":pages,"chunks":len(chunks)}

@router.patch("/resources/{resource_id}/approve-v2")
def approve_resource_v2(resource_id:int,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    r=db.get(Resource,resource_id)
    if not r or not can_access_subject(db,u,r.subject_id):raise HTTPException(404,"Resource not found")
    r.status="APPROVED";set_resource_status(r.id,"APPROVED");audit(db,u,"RESOURCE_APPROVED","RESOURCE",r.id);db.commit();return {"id":r.id,"status":r.status}

@router.post("/syllabus/compare-v2")
def compare_syllabus(p:SyllabusCompareRequest,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    active=db.scalar(select(SyllabusVersion).where(SyllabusVersion.subject_id==p.subject_id,SyllabusVersion.status=="ACTIVE").order_by(SyllabusVersion.version.desc()))
    old=[]
    if active and active.summary:
        try:old=json.loads(active.summary).get("topics",[])
        except Exception:old=[]
    new=[x.strip() for x in p.topic_names if x.strip()]
    old_map={normalize_key(x):x for x in old};new_map={normalize_key(x):x for x in new};changes=[]
    for k,v in new_map.items():
        if k not in old_map:changes.append(("ADDED",None,v))
        elif old_map[k]!=v:changes.append(("MODIFIED",old_map[k],v))
        else:changes.append(("UNCHANGED",v,v))
    for k,v in old_map.items():
        if k not in new_map:changes.append(("REMOVED",v,None))
    version=p.version or ((active.version+1) if active else 1)
    if active:active.status="ARCHIVED"
    sv=SyllabusVersion(subject_id=p.subject_id,version=version,source_resource_id=p.source_resource_id,status="ACTIVE",summary=json.dumps({"topics":new}));db.add(sv);db.flush()
    for typ,oldv,newv in changes:db.add(SyllabusChange(subject_id=p.subject_id,from_version=active.version if active else version,to_version=version,change_type=typ,old_topic=oldv,new_topic=newv,details="Automatic syllabus comparison"))
    audit(db,u,"SYLLABUS_COMPARE","SYLLABUS_VERSION",sv.id);db.commit()
    return {"version":version,"added":[x[2] for x in changes if x[0]=="ADDED"],"removed":[x[1] for x in changes if x[0]=="REMOVED"],"modified":[{"old":x[1],"new":x[2]} for x in changes if x[0]=="MODIFIED"],"unchanged":[x[1] for x in changes if x[0]=="UNCHANGED"]}

@router.get("/syllabus/changes/{subject_id}")
def syllabus_changes(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    return [{"from":x.from_version,"to":x.to_version,"type":x.change_type,"old":x.old_topic,"new":x.new_topic,"details":x.details} for x in db.scalars(select(SyllabusChange).where(SyllabusChange.subject_id==subject_id).order_by(SyllabusChange.id.desc())).all()]

@router.post("/ai/generate")
def generate_content(p:GenerateRequest,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    topic=db.get(Topic,p.topic_id) if p.topic_id else None
    contexts=approved_contexts(db,p.subject_id,p.instructions or (topic.topic_name if topic else p.content_type))
    if not contexts:raise HTTPException(409,APPROVED_RESOURCE_MESSAGE)
    data=generate_structured(p.content_type,p.title,topic.topic_name if topic else None,contexts,p.instructions or "")
    if not data:raise HTTPException(502,"AI generation failed")
    title=p.title or data.get("title") or p.content_type.title();body=body_from_generated(p.content_type,data)
    c=Content(subject_id=p.subject_id,topic_id=p.topic_id,title=title,content_type=p.content_type.upper(),body=body,status="IN_REVIEW",source_reference="; ".join(x.get("citation","") for x in contexts),version=1,generated_by_ai=True,created_by=u.id)
    db.add(c);db.flush()
    used={x.get("resource_id") for x in contexts}
    for rid in used:
        if rid:db.add(ContentSource(content_id=c.id,resource_id=rid,citation=next((x.get("citation","") for x in contexts if x.get("resource_id")==rid),str(rid))))
    artifact=None
    if p.content_type.lower()=="ppt":
        try:
            blob=make_pptx(title,data.get("slides",[]));key=f"subjects/{p.subject_id}/artifacts/{c.id}.pptx"
            if put_object(key,blob,"application/vnd.openxmlformats-officedocument.presentationml.presentation"):
                artifact=GeneratedArtifact(subject_id=p.subject_id,content_id=c.id,title=title,artifact_type="PPTX",storage_key=key,created_by=u.id);db.add(artifact)
        except Exception:pass
    audit(db,u,"AI_GENERATE_CONTENT","CONTENT",c.id,json.dumps({"type":p.content_type,"sources":len(used)}));db.commit()
    return {"id":c.id,"title":title,"type":c.content_type,"status":c.status,"body":body,"artifact_id":artifact.id if artifact else None,"sources":[x.get("citation") for x in contexts]}

@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    a=db.get(GeneratedArtifact,artifact_id)
    if not a or not can_access_subject(db,u,a.subject_id):raise HTTPException(404,"Artifact not found")
    c=db.get(Content,a.content_id) if a.content_id else None
    if u.role=="STUDENT" and c and c.status!="PUBLISHED":raise HTTPException(403,"Artifact not published")
    data=get_object(a.storage_key)
    if data is None:raise HTTPException(404,"Artifact unavailable")
    from fastapi.responses import Response
    return Response(data,media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",headers={"Content-Disposition":f'attachment; filename="{a.title}.pptx"'})

@router.post("/ai/ask-v2")
def ask_v2(subject_id:int,question:str,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    contexts=approved_contexts(db,subject_id,question);return grounded_answer(question,contexts)

@router.post("/pyq/reanalyze-v2/{subject_id}")
def pyq_reanalyze_v2(subject_id:int,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    rows=pyq_reanalyze(db,subject_id);audit(db,u,"PYQ_REANALYZE","SUBJECT",subject_id);db.commit();return {"questions":len(rows)}

@router.get("/pyq/analytics-v2/{subject_id}")
def pyq_analytics_v2(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    qs=db.scalars(select(PYQQuestion).where(PYQQuestion.subject_id==subject_id)).all();topics={x.id:x for x in db.scalars(select(Topic).where(Topic.subject_id==subject_id)).all()}
    by_unit=defaultdict(float);by_year=defaultdict(float);freq=Counter()
    for q in qs:
        if q.unit_number:by_unit[q.unit_number]+=q.marks
        if q.year:by_year[q.year]+=q.marks
        freq[q.frequency_key or normalize_key(q.question_text)]+=1
    repeated=[{"question":k,"count":v} for k,v in freq.items() if v>1]
    return {"unit_weightage":[{"unit":k,"marks":v} for k,v in sorted(by_unit.items())],"year_trend":[{"year":k,"marks":v} for k,v in sorted(by_year.items())],"repeated":sorted(repeated,key=lambda x:-x["count"])[:20],"mapping":[{"question":q.question_text,"topic":topics.get(q.topic_id).topic_name if q.topic_id in topics else None,"confidence":q.mapping_confidence} for q in qs]}

@router.post("/teaching-plan/edit/{subject_id}")
def edit_plan(subject_id:int,p:PlanEdit,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    t=db.get(Topic,p.topic_id)
    if not t or t.subject_id!=subject_id:raise HTTPException(404,"Topic not found")
    if p.action=="HOURS" and p.value is not None:t.estimated_hours=p.value
    elif p.action=="REORDER" and p.value is not None:t.sequence_order=int(p.value)
    elif p.action=="REMOVE":t.status="ARCHIVED"
    elif p.action=="COMPLETE":t.completed=True
    elif p.action=="MERGE" and p.note:t.topic_name=f"{t.topic_name} + {p.note}"
    elif p.action=="SPLIT" and p.note:
        db.add(Topic(subject_id=subject_id,unit_number=t.unit_number,topic_name=p.note,sequence_order=t.sequence_order+1,estimated_hours=max(.5,t.estimated_hours/2)));t.estimated_hours=max(.5,t.estimated_hours/2)
    elif p.action=="RESCHEDULE" and p.new_week:
        item=db.scalar(select(TeachingPlan).where(TeachingPlan.subject_id==subject_id,TeachingPlan.topic_id=p.topic_id))
        if item:item.planned_week=p.new_week
    else:raise HTTPException(400,"Unsupported plan edit")
    rebuild_plan(db,subject_id);audit(db,u,"TEACHING_PLAN_EDIT","SUBJECT",subject_id,json.dumps(p.model_dump()));db.commit();return plan_rows(db,subject_id)

@router.post("/assignments/submit")
def submit_assignment(p:AssignmentSubmit,db:Session=Depends(get_db),u=Depends(require_roles("STUDENT"))):
    c=db.get(Content,p.content_id)
    if not c or c.content_type!="ASSIGNMENT" or c.status!="PUBLISHED" or not can_access_subject(db,u,c.subject_id):raise HTTPException(404,"Assignment unavailable")
    s=AssignmentSubmission(content_id=c.id,student_id=u.id,answer_text=p.answer_text);db.add(s);db.flush();db.add(Progress(student_id=u.id,subject_id=c.subject_id,topic_id=c.topic_id,activity_type="ASSIGNMENT",score=0,max_score=1,completed=True));audit(db,u,"SUBMIT_ASSIGNMENT","ASSIGNMENT",c.id);db.commit();return {"submission_id":s.id,"status":"SUBMITTED"}

@router.get("/analytics/teacher-v2/{subject_id}")
def teacher_analytics_v2(subject_id:int,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    students=db.scalar(select(func.count(Enrollment.id)).where(Enrollment.subject_id==subject_id)) or 0
    published=db.scalar(select(func.count(Content.id)).where(Content.subject_id==subject_id,Content.status=="PUBLISHED")) or 0
    attempts=db.execute(select(Attempt.score,Attempt.total).join(Quiz,Quiz.id==Attempt.quiz_id).where(Quiz.subject_id==subject_id)).all()
    avg=round(sum((s/t*100 if t else 0) for s,t in attempts)/len(attempts),2) if attempts else 0
    return {"students":students,"published_content":published,"quiz_attempts":len(attempts),"average_quiz_percentage":avg,"resources_approved":db.scalar(select(func.count(Resource.id)).where(Resource.subject_id==subject_id,Resource.status=="APPROVED")) or 0}

@router.get("/analytics/student")
def student_analytics(db:Session=Depends(get_db),u=Depends(require_roles("STUDENT"))):
    rows=db.scalars(select(Progress).where(Progress.student_id==u.id)).all();score=sum(x.score for x in rows);maximum=sum(x.max_score for x in rows)
    return {"activities":len(rows),"completed":sum(1 for x in rows if x.completed),"average_percentage":round(score*100/maximum,2) if maximum else 0}

@router.get("/admin/audit-export")
def audit_export(db:Session=Depends(get_db),u=Depends(require_roles("ADMIN"))):
    return [{"id":x.id,"actor_id":x.actor_id,"action":x.action,"entity":x.entity_type,"entity_id":x.entity_id,"details":x.details,"created_at":x.created_at} for x in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1000)).all()]
