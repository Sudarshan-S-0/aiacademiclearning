from datetime import datetime,timedelta,timezone
import json,re,jwt
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Header,Query
from passlib.context import CryptContext
from pydantic import BaseModel,EmailStr,Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.models import *
from app.services.ai import build_rag_prompt,grounded_answer,gemini_generate
from app.services.document import extract_text,normalize_text,chunk_text
from app.services.storage import put_object,get_object
from app.services.qdrant import upsert_chunks
router=APIRouter(prefix="/api");pwd=CryptContext(schemes=["bcrypt"],deprecated="auto")
class Login(BaseModel): email:EmailStr;password:str
class UserCreate(BaseModel): full_name:str=Field(min_length=2);email:EmailStr;password:str=Field(min_length=8);role:str
class SubjectCreate(BaseModel): semester_id:int;code:str;name:str;description:str|None=None;weeks:int=16;hours_per_week:int=4;lecture_duration_minutes:int=60
class AssignmentCreate(BaseModel): teacher_id:int;subject_id:int;section_id:int|None=None;academic_year:str
class EnrollmentCreate(BaseModel): student_id:int;subject_id:int;section_id:int|None=None;academic_year:str
class TopicCreate(BaseModel): subject_id:int;unit_number:int;topic_name:str;sequence_order:int;estimated_hours:float=1
class TopicUpdate(BaseModel): sequence_order:int|None=None;estimated_hours:float|None=None;completed:bool|None=None;status:str|None=None
class ContentCreate(BaseModel): subject_id:int;topic_id:int|None=None;title:str;content_type:str;body:str;source_reference:str|None=None;generated_by_ai:bool=False
class PublishAction(BaseModel): status:str
class PYQCreate(BaseModel): subject_id:int;year:int|None=None;question_no:str|None=None;question_text:str;marks:float=1;topic_id:int|None=None;unit_number:int|None=None
class PlanAction(BaseModel): action:str;topic_id:int;value:float|int|None=None;new_week:int|None=None;note:str|None=None
class QuizCreate(BaseModel): subject_id:int;title:str;duration_minutes:int=30;status:str="DRAFT"
class QuizQuestionCreate(BaseModel): topic_id:int|None=None;question_text:str;marks:int=1;correct_answer:str;options:list[str]|None=None
class Answer(BaseModel): question_id:int;answer:str
class AttemptCreate(BaseModel): quiz_id:int;answers:list[Answer]
class AIContentRequest(BaseModel): subject_id:int;topic_id:int|None=None;content_type:str;title:str|None=None;instructions:str|None=None
class AIPlanRequest(BaseModel): subject_id:int
class AskRequest(BaseModel): subject_id:int;question:str
def token_for(u):return jwt.encode({"sub":u.id,"role":u.role,"exp":datetime.now(timezone.utc)+timedelta(hours=8)},settings.jwt_secret,algorithm="HS256")
def current_user(authorization:str|None=Header(default=None),db:Session=Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):raise HTTPException(401,"Authentication required")
    try:data=jwt.decode(authorization[7:],settings.jwt_secret,algorithms=["HS256"])
    except jwt.PyJWTError:raise HTTPException(401,"Invalid token")
    u=db.get(User,int(data["sub"]))
    if not u or not u.is_active:raise HTTPException(401,"Inactive user")
    return u
def require_roles(*roles):
    def dep(u=Depends(current_user)):
        if u.role not in roles:raise HTTPException(403,"Insufficient permissions")
        return u
    return dep
def audit(db,actor,action,entity_type,entity_id=None,details=None):db.add(AuditLog(actor_id=actor.id if actor else None,action=action,entity_type=entity_type,entity_id=entity_id,details=details))
def can_access_subject(db,u,subject_id):
    if u.role=="ADMIN":return True
    if u.role=="TEACHER":return db.scalar(select(TeacherSubject.id).where(TeacherSubject.teacher_id==u.id,TeacherSubject.subject_id==subject_id)) is not None
    if u.role=="STUDENT":return db.scalar(select(Enrollment.id).where(Enrollment.student_id==u.id,Enrollment.subject_id==subject_id)) is not None
    return False
@router.get("/health")
def health():return {"status":"ok","service":"ai-academic-learning"}
@router.post("/auth/register")
def register(p:UserCreate,db:Session=Depends(get_db)):
    role=p.role.upper()
    if role not in {"ADMIN","TEACHER","STUDENT"}:raise HTTPException(400,"Invalid role")
    if db.scalar(select(User).where(User.email==p.email)):raise HTTPException(409,"Email already exists")
    u=User(full_name=p.full_name,email=p.email,password_hash=pwd.hash(p.password),role=role);db.add(u);db.commit();db.refresh(u);return {"id":u.id,"email":u.email,"role":u.role}
@router.post("/auth/login")
def login(p:Login,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==p.email))
    if not u or not u.password_hash or not pwd.verify(p.password,u.password_hash):raise HTTPException(401,"Invalid credentials")
    return {"access_token":token_for(u),"token_type":"bearer","user":{"id":u.id,"name":u.full_name,"role":u.role}}
@router.get("/me")
def me(u=Depends(current_user)):return {"id":u.id,"name":u.full_name,"email":u.email,"role":u.role}
@router.get("/dashboard/summary")
def summary(db:Session=Depends(get_db),u=Depends(current_user)):
    result={"users":db.scalar(select(func.count(User.id))) or 0,"subjects":db.scalar(select(func.count(Subject.id)).where(Subject.status=="ACTIVE")) or 0,"resources":db.scalar(select(func.count(Resource.id))) or 0,"topics":db.scalar(select(func.count(Topic.id)).where(Topic.status=="ACTIVE")) or 0,"published_content":db.scalar(select(func.count(Content.id)).where(Content.status=="PUBLISHED")) or 0,"quizzes":db.scalar(select(func.count(Quiz.id)).where(Quiz.status=="PUBLISHED")) or 0}
    if u.role in {"TEACHER","STUDENT"}:result["my_subjects"]=(db.scalar(select(func.count(TeacherSubject.id)).where(TeacherSubject.teacher_id==u.id)) if u.role=="TEACHER" else db.scalar(select(func.count(Enrollment.id)).where(Enrollment.student_id==u.id))) or 0
    return result
@router.post("/users")
def create_user(p:UserCreate,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN"))):
    if db.scalar(select(User).where(User.email==p.email)):raise HTTPException(409,"Email exists")
    x=User(full_name=p.full_name,email=p.email,password_hash=pwd.hash(p.password),role=p.role.upper());db.add(x);db.flush();audit(db,u,"CREATE_USER","USER",x.id);db.commit();return {"id":x.id,"name":x.full_name,"email":x.email,"role":x.role}
@router.get("/users")
def users(db:Session=Depends(get_db),u=Depends(require_roles("ADMIN"))):return [{"id":x.id,"name":x.full_name,"email":x.email,"role":x.role,"active":x.is_active} for x in db.scalars(select(User).order_by(User.id.desc())).all()]
@router.post("/subjects")
def create_subject(p:SubjectCreate,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN"))):
    x=Subject(**p.model_dump());db.add(x);db.flush();audit(db,u,"CREATE_SUBJECT","SUBJECT",x.id);db.commit();return {"id":x.id,"code":x.code,"name":x.name}
@router.get("/subjects")
def subjects(db:Session=Depends(get_db),u=Depends(current_user)):
    q=select(Subject).where(Subject.status=="ACTIVE")
    if u.role=="TEACHER":q=q.join(TeacherSubject).where(TeacherSubject.teacher_id==u.id)
    if u.role=="STUDENT":q=q.join(Enrollment).where(Enrollment.student_id==u.id)
    return [{"id":x.id,"code":x.code,"name":x.name,"weeks":x.weeks,"hours_per_week":x.hours_per_week,"total_hours":x.weeks*x.hours_per_week} for x in db.scalars(q).all()]
@router.post("/assignments")
def assignment(p:AssignmentCreate,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN"))):
    teacher=db.get(User,p.teacher_id)
    if not teacher or teacher.role!="TEACHER":raise HTTPException(400,"teacher_id must belong to a teacher")
    if not db.get(Subject,p.subject_id):raise HTTPException(404,"Subject not found")
    x=TeacherSubject(**p.model_dump());db.add(x);db.flush();audit(db,u,"ASSIGN_TEACHER","TEACHER_SUBJECT",x.id);db.commit();return {"id":x.id}
@router.post("/enrollments")
def enrollment(p:EnrollmentCreate,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN"))):
    student=db.get(User,p.student_id)
    if not student or student.role!="STUDENT":raise HTTPException(400,"student_id must belong to a student")
    if not db.get(Subject,p.subject_id):raise HTTPException(404,"Subject not found")
    x=Enrollment(**p.model_dump());db.add(x);db.flush();audit(db,u,"ENROLL_STUDENT","ENROLLMENT",x.id);db.commit();return {"id":x.id}
@router.post("/topics")
def create_topic(p:TopicCreate,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    x=Topic(**p.model_dump());db.add(x);db.flush();audit(db,u,"CREATE_TOPIC","TOPIC",x.id);db.commit();return {"id":x.id,"topic_name":x.topic_name}
@router.get("/subjects/{subject_id}/topics")
def get_topics(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    return [{"id":x.id,"unit":x.unit_number,"name":x.topic_name,"hours":x.estimated_hours,"order":x.sequence_order,"completed":x.completed} for x in db.scalars(select(Topic).where(Topic.subject_id==subject_id,Topic.status=="ACTIVE").order_by(Topic.sequence_order)).all()]
@router.patch("/topics/{topic_id}")
def update_topic(topic_id:int,p:TopicUpdate,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    x=db.get(Topic,topic_id)
    if not x or not can_access_subject(db,u,x.subject_id):raise HTTPException(404,"Topic not found")
    for k,v in p.model_dump(exclude_none=True).items():setattr(x,k,v)
    audit(db,u,"UPDATE_TOPIC","TOPIC",x.id,json.dumps(p.model_dump(exclude_none=True)));db.commit();return {"id":x.id,"updated":True}
@router.post("/resources")
async def upload_resource(subject_id:int,title:str|None=None,resource_type:str="REFERENCE",file:UploadFile=File(...),db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    data=await file.read()
    if len(data)>20*1024*1024:raise HTTPException(413,"Maximum file size is 20 MB")
    key=f"subjects/{subject_id}/resources/{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{u.id}_{file.filename.replace(' ','_')}"
    text,pages=extract_text(file.filename,data);text=normalize_text(text);stored=put_object(key,data,file.content_type or "application/octet-stream")
    x=Resource(subject_id=subject_id,uploaded_by=u.id,title=title or file.filename,resource_type=resource_type,storage_key=key,status="DRAFT",extracted_text=text,page_count=pages);db.add(x);db.flush();upsert_chunks(x.id,subject_id,chunk_text(text),x.title);audit(db,u,"UPLOAD_RESOURCE","RESOURCE",x.id,json.dumps({"key":key,"bytes":len(data),"stored":stored}));db.commit();return {"id":x.id,"storage_key":key,"status":"DRAFT","bytes":len(data),"extracted_chars":len(text),"pages":pages,"stored":stored}
@router.get("/resources")
def resources(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    return [{"id":r.id,"title":r.title,"type":r.resource_type,"status":r.status,"version":r.version,"pages":r.page_count,"chars":len(r.extracted_text or "")} for r in db.scalars(select(Resource).where(Resource.subject_id==subject_id).order_by(Resource.id.desc())).all()]
@router.patch("/resources/{resource_id}/status")
def resource_status(resource_id:int,status:str=Query(...),db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    x=db.get(Resource,resource_id)
    if not x or not can_access_subject(db,u,x.subject_id):raise HTTPException(404,"Resource not found")
    if status not in {"DRAFT","APPROVED","ARCHIVED"}:raise HTTPException(400,"Invalid resource status")
    x.status=status;audit(db,u,f"RESOURCE_{status}","RESOURCE",x.id);db.commit();return {"id":x.id,"status":status}
@router.get("/resources/{resource_id}/download")
def download_resource(resource_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    from fastapi.responses import Response
    x=db.get(Resource,resource_id)
    if not x or not can_access_subject(db,u,x.subject_id):raise HTTPException(404,"Resource not found")
    if u.role=="STUDENT" and x.status!="APPROVED":raise HTTPException(403,"Resource not published to students")
    data=get_object(x.storage_key or "")
    if data is None:raise HTTPException(404,"Stored file not available")
    return Response(data,media_type="application/octet-stream",headers={"Content-Disposition":f'attachment; filename="{x.title}"'})
@router.post("/syllabus/versions")
def syllabus_version(subject_id:int,resource_id:int|None=None,summary:str|None=None,db:Session=Depends(get_db),u=Depends(require_roles("ADMIN","TEACHER"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    current=db.scalar(select(func.max(SyllabusVersion.version)).where(SyllabusVersion.subject_id==subject_id)) or 0
    v=SyllabusVersion(subject_id=subject_id,version=current+1,source_resource_id=resource_id,summary=summary);db.add(v);db.flush();audit(db,u,"CREATE_SYLLABUS_VERSION","SYLLABUS",v.id);db.commit();return {"id":v.id,"version":v.version}
@router.get("/syllabus/{subject_id}/versions")
def syllabus_versions(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    return [{"id":v.id,"version":v.version,"resource_id":v.source_resource_id,"status":v.status,"summary":v.summary} for v in db.scalars(select(SyllabusVersion).where(SyllabusVersion.subject_id==subject_id).order_by(SyllabusVersion.version.desc())).all()]
@router.post("/content")
def create_content(p:ContentCreate,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    x=Content(**p.model_dump(),status="IN_REVIEW");db.add(x);db.flush();audit(db,u,"CREATE_CONTENT","CONTENT",x.id);db.commit();return {"id":x.id,"status":x.status}
@router.get("/content")
def list_content(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    q=select(Content).where(Content.subject_id==subject_id)
    if u.role=="STUDENT":q=q.where(Content.status=="PUBLISHED")
    return [{"id":x.id,"title":x.title,"type":x.content_type,"status":x.status,"body":x.body,"topic_id":x.topic_id,"source":x.source_reference,"ai":x.generated_by_ai} for x in db.scalars(q.order_by(Content.id.desc())).all()]
@router.patch("/content/{content_id}/status")
def content_status(content_id:int,p:PublishAction,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if p.status not in {"DRAFT","IN_REVIEW","APPROVED","PUBLISHED","ARCHIVED"}:raise HTTPException(400,"Invalid lifecycle state")
    x=db.get(Content,content_id)
    if not x or not can_access_subject(db,u,x.subject_id):raise HTTPException(404,"Content not found")
    x.status=p.status;audit(db,u,f"CONTENT_{p.status}","CONTENT",x.id);db.commit();return {"id":x.id,"status":x.status}
@router.post("/ai/ask")
def ask_ai(p:AskRequest,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    rs=db.scalars(select(Resource).where(Resource.subject_id==p.subject_id,Resource.status=="APPROVED")).all()
    result=grounded_answer(p.question,[{"status":"APPROVED","source":r.title,"text":r.extracted_text or ""} for r in rs]);audit(db,u,"AI_ASK","SUBJECT",p.subject_id,p.question[:500]);db.commit();return result
@router.post("/ai/prompt-preview")
def ai_prompt_preview(question:str,subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    rs=db.scalars(select(Resource).where(Resource.subject_id==subject_id,Resource.status=="APPROVED")).all();ctx=[{"status":"APPROVED","source":r.title,"text":r.extracted_text or ""} for r in rs if r.extracted_text]
    return {"prompt":build_rag_prompt(question,ctx),"grounding_sources":[c["source"] for c in ctx]}
@router.post("/ai/generate-content")
def generate_content(p:AIContentRequest,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    rs=db.scalars(select(Resource).where(Resource.subject_id==p.subject_id,Resource.status=="APPROVED")).all()
    if not rs:raise HTTPException(400,"Approve at least one academic resource before AI generation")
    topic=db.get(Topic,p.topic_id) if p.topic_id else None
    prompt=build_rag_prompt(f"Create {p.content_type} titled '{p.title or p.content_type}' for topic '{topic.topic_name if topic else 'the subject'}'. {p.instructions or ''}",[{"status":"APPROVED","source":r.title,"text":r.extracted_text or ""} for r in rs])
    body=gemini_generate(prompt) or ("AI generation requires GEMINI_API_KEY. Approved-resource context is ready for generation.\n\n"+(rs[0].extracted_text or "")[:2500])
    x=Content(subject_id=p.subject_id,topic_id=p.topic_id,title=p.title or f"AI {p.content_type}",content_type=p.content_type,body=body,status="IN_REVIEW",source_reference=", ".join(r.title for r in rs),generated_by_ai=True);db.add(x);db.flush();audit(db,u,"AI_GENERATE_CONTENT","CONTENT",x.id,p.content_type);db.commit();return {"id":x.id,"status":x.status,"body":x.body,"sources":[r.title for r in rs]}
@router.post("/pyq/questions")
def add_pyq(p:PYQCreate,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    q=PYQQuestion(**p.model_dump(),frequency_key=re.sub(r'[^a-z0-9 ]','',p.question_text.lower())[:255]);db.add(q);db.flush();audit(db,u,"ADD_PYQ","PYQ",q.id);db.commit();return {"id":q.id}
@router.post("/pyq/reanalyze/{subject_id}")
def reanalyze_pyq(subject_id:int,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    qs=db.scalars(select(PYQQuestion).where(PYQQuestion.subject_id==subject_id)).all();ts=db.scalars(select(Topic).where(Topic.subject_id==subject_id,Topic.status=="ACTIVE")).all()
    if not ts:raise HTTPException(400,"Create syllabus topics first")
    for q in qs:
        if not q.topic_id:
            words=set(re.findall(r'[a-z0-9]{3,}',q.question_text.lower()));best=max(ts,key=lambda t:len(words&set(re.findall(r'[a-z0-9]{3,}',t.topic_name.lower()))),default=None)
            if best:q.topic_id=best.id;q.unit_number=best.unit_number
    for old in db.scalars(select(TopicWeightage).where(TopicWeightage.subject_id==subject_id)).all():db.delete(old)
    total=sum(q.marks for q in qs) or 1
    for t in ts:
        rows=[q for q in qs if q.topic_id==t.id];marks=sum(q.marks for q in rows);db.add(TopicWeightage(subject_id=subject_id,topic_id=t.id,question_count=len(rows),total_marks=marks,percentage=round(marks*100/total,2)))
    audit(db,u,"REANALYZE_PYQ","SUBJECT",subject_id,f"questions={len(qs)}");db.commit();return pyq_analysis(subject_id,db,u)
@router.get("/pyq/analysis/{subject_id}")
def pyq_analysis(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    rows=db.execute(select(TopicWeightage,Topic).join(Topic,Topic.id==TopicWeightage.topic_id).where(TopicWeightage.subject_id==subject_id).order_by(TopicWeightage.percentage.desc())).all();qs=db.scalars(select(PYQQuestion).where(PYQQuestion.subject_id==subject_id)).all();rep={}
    for q in qs:rep[q.frequency_key or q.question_text.lower()]=rep.get(q.frequency_key or q.question_text.lower(),0)+1
    return {"questions":len(qs),"weights":[{"topic_id":w.topic_id,"topic":t.topic_name,"unit":t.unit_number,"question_count":w.question_count,"marks":w.total_marks,"percentage":w.percentage} for w,t in rows],"repeated":[{"question":k,"frequency":v} for k,v in sorted(rep.items(),key=lambda z:z[1],reverse=True) if v>1]}
@router.post("/teaching-plan/generate")
def generate_plan(p:AIPlanRequest,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    subject=db.get(Subject,p.subject_id);topics=db.scalars(select(Topic).where(Topic.subject_id==p.subject_id,Topic.status=="ACTIVE").order_by(Topic.sequence_order)).all()
    if not topics:raise HTTPException(400,"Create syllabus topics first")
    for old in db.scalars(select(TeachingPlan).where(TeachingPlan.subject_id==p.subject_id,TeachingPlan.status!="COMPLETED")).all():db.delete(old)
    week=1;used=0
    for t in topics:
        rem=t.estimated_hours
        while rem>0 and week<=subject.weeks:
            cap=max(subject.hours_per_week-used,0)
            if cap<=0:week+=1;used=0;continue
            h=min(rem,cap);db.add(TeachingPlan(subject_id=p.subject_id,topic_id=t.id,planned_week=week,planned_hours=h));rem-=h;used+=h
            if used>=subject.hours_per_week:week+=1;used=0
    audit(db,u,"GENERATE_TEACHING_PLAN","SUBJECT",p.subject_id);db.commit();return get_plan_data(db,p.subject_id)
def get_plan_data(db,subject_id):
    rows=db.execute(select(TeachingPlan,Topic).join(Topic,Topic.id==TeachingPlan.topic_id).where(TeachingPlan.subject_id==subject_id).order_by(TeachingPlan.planned_week,Topic.sequence_order)).all()
    return [{"id":p.id,"topic_id":p.topic_id,"topic":t.topic_name,"week":p.planned_week,"planned_hours":p.planned_hours,"actual_hours":p.actual_hours,"status":p.status,"note":p.teacher_note} for p,t in rows]
@router.get("/teaching-plan/{subject_id}")
def teaching_plan(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    return get_plan_data(db,subject_id)
@router.post("/teaching-plan/{subject_id}/update")
def update_plan(subject_id:int,p:PlanAction,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    plan=db.scalar(select(TeachingPlan).where(TeachingPlan.subject_id==subject_id,TeachingPlan.topic_id==p.topic_id,TeachingPlan.status!="COMPLETED"))
    if not plan:raise HTTPException(404,"Plan item not found")
    if p.action=="complete":plan.status="COMPLETED";plan.actual_hours=p.value or plan.planned_hours
    elif p.action=="postpone":plan.planned_week=p.new_week or plan.planned_week+1
    elif p.action=="duration":plan.planned_hours=float(p.value or plan.planned_hours)
    elif p.action=="note":plan.teacher_note=p.note
    else:raise HTTPException(400,"Supported actions: complete, postpone, duration, note")
    audit(db,u,f"PLAN_{p.action.upper()}","TEACHING_PLAN",plan.id);db.commit();return get_plan_data(db,subject_id)
@router.post("/quizzes")
def create_quiz(p:QuizCreate,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    if not can_access_subject(db,u,p.subject_id):raise HTTPException(403,"Subject access denied")
    q=Quiz(**p.model_dump());db.add(q);db.flush();audit(db,u,"CREATE_QUIZ","QUIZ",q.id);db.commit();return {"id":q.id,"status":q.status}
@router.post("/quizzes/{quiz_id}/questions")
def add_quiz_question(quiz_id:int,p:QuizQuestionCreate,db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    qz=db.get(Quiz,quiz_id)
    if not qz or not can_access_subject(db,u,qz.subject_id):raise HTTPException(404,"Quiz not found")
    q=QuizQuestion(quiz_id=quiz_id,topic_id=p.topic_id,question_text=p.question_text,marks=p.marks,correct_answer=p.correct_answer,options_json=json.dumps(p.options or []));db.add(q);db.commit();return {"id":q.id}
@router.patch("/quizzes/{quiz_id}/status")
def quiz_status(quiz_id:int,status:str=Query(...),db:Session=Depends(get_db),u=Depends(require_roles("TEACHER","ADMIN"))):
    q=db.get(Quiz,quiz_id)
    if not q or not can_access_subject(db,u,q.subject_id):raise HTTPException(404,"Quiz not found")
    if status not in {"DRAFT","PUBLISHED","ARCHIVED"}:raise HTTPException(400,"Invalid quiz status")
    q.status=status;audit(db,u,f"QUIZ_{status}","QUIZ",q.id);db.commit();return {"id":q.id,"status":status}
@router.get("/quizzes")
def quizzes(subject_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    if not can_access_subject(db,u,subject_id):raise HTTPException(403,"Subject access denied")
    q=select(Quiz).where(Quiz.subject_id==subject_id)
    if u.role=="STUDENT":q=q.where(Quiz.status=="PUBLISHED")
    return [{"id":x.id,"title":x.title,"status":x.status,"duration_minutes":x.duration_minutes} for x in db.scalars(q).all()]
@router.get("/quizzes/{quiz_id}")
def quiz_detail(quiz_id:int,db:Session=Depends(get_db),u=Depends(current_user)):
    q=db.get(Quiz,quiz_id)
    if not q or not can_access_subject(db,u,q.subject_id):raise HTTPException(404,"Quiz not found")
    if u.role=="STUDENT" and q.status!="PUBLISHED":raise HTTPException(403,"Quiz not published")
    rows=db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id==quiz_id)).all()
    return {"id":q.id,"title":q.title,"status":q.status,"duration_minutes":q.duration_minutes,"questions":[{"id":x.id,"question":x.question_text,"marks":x.marks,"options":json.loads(x.options_json or "[]"),"topic_id":x.topic_id} for x in rows]}
@router.post("/quizzes/attempt")
def attempt_quiz(p:AttemptCreate,db:Session=Depends(get_db),u=Depends(require_roles("STUDENT"))):
    qz=db.get(Quiz,p.quiz_id)
    if not qz or qz.status!="PUBLISHED" or not can_access_subject(db,u,qz.subject_id):raise HTTPException(404,"Quiz unavailable")
    qs=db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id==qz.id)).all();amap={a.question_id:a.answer.strip().lower() for a in p.answers};total=sum(q.marks for q in qs);score=0
    attempt=Attempt(quiz_id=qz.id,student_id=u.id,total=total,completed_at=datetime.now(timezone.utc));db.add(attempt);db.flush()
    for q in qs:
        ans=amap.get(q.id,"");correct=ans==q.correct_answer.strip().lower();marks=q.marks if correct else 0;score+=marks;db.add(AttemptAnswer(attempt_id=attempt.id,question_id=q.id,answer=ans,is_correct=correct,marks_awarded=marks));db.add(Progress(student_id=u.id,subject_id=qz.subject_id,topic_id=q.topic_id,activity_type="QUIZ",score=marks,max_score=q.marks,completed=True))
    attempt.score=score;audit(db,u,"SUBMIT_QUIZ","ATTEMPT",attempt.id);db.commit();return {"attempt_id":attempt.id,"score":score,"total":total,"percentage":round(score*100/total,2) if total else 0}
@router.get("/student/content")
def student_content(db:Session=Depends(get_db),u=Depends(require_roles("STUDENT"))):
    ids=select(Enrollment.subject_id).where(Enrollment.student_id==u.id);rows=db.scalars(select(Content).where(Content.subject_id.in_(ids),Content.status=="PUBLISHED")).all()
    return [{"id":x.id,"subject_id":x.subject_id,"title":x.title,"type":x.content_type,"body":x.body,"source":x.source_reference} for x in rows]
@router.get("/student/progress")
def student_progress(db:Session=Depends(get_db),u=Depends(require_roles("STUDENT"))):
    return [{"id":x.id,"subject_id":x.subject_id,"topic_id":x.topic_id,"activity":x.activity_type,"score":x.score,"max_score":x.max_score,"completed":x.completed} for x in db.scalars(select(Progress).where(Progress.student_id==u.id).order_by(Progress.id.desc())).all()]
@router.get("/student/weak-topics")
def weak_topics(db:Session=Depends(get_db),u=Depends(require_roles("STUDENT"))):
    rows=db.execute(select(Progress,Topic).join(Topic,Topic.id==Progress.topic_id).where(Progress.student_id==u.id,Progress.topic_id.is_not(None))).all();agg={}
    for p,t in rows:
        d=agg.setdefault(t.id,{"topic_id":t.id,"topic":t.topic_name,"score":0,"max":0});d["score"]+=p.score;d["max"]+=p.max_score
    out=[]
    for d in agg.values():d["percentage"]=round(d["score"]*100/d["max"],2) if d["max"] else 0;out.append(d)
    return sorted(out,key=lambda x:x["percentage"])
@router.get("/audit")
def audit_logs(db:Session=Depends(get_db),u=Depends(require_roles("ADMIN"))):
    return [{"id":x.id,"actor_id":x.actor_id,"action":x.action,"entity":x.entity_type,"entity_id":x.entity_id,"details":x.details,"created_at":x.created_at} for x in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(300)).all()]
