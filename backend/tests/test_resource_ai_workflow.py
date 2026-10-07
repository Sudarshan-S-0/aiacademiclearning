from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.session import Base,get_db
from app.models.models import User,Department,Semester,Subject,TeacherSubject,Enrollment,Resource
from app.api.routes import pwd
import app.api.extended_routes as extended

def test_resource_ai_publication_gates(monkeypatch):
    engine=create_engine("sqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal=sessionmaker(bind=engine)
    db=SessionLocal()
    d=Department(code="WF",name="Workflow")
    db.add(d);db.flush()
    s=Semester(department_id=d.id,academic_year="2026-27",semester_number=1,regulation="TEST")
    db.add(s);db.flush()
    subject=Subject(semester_id=s.id,code="WF101",name="Workflow Subject")
    db.add(subject);db.flush()
    teacher=User(full_name="Teacher",email="wf.teacher@example.com",password_hash=pwd.hash("Teacher@123"),role="TEACHER")
    student=User(full_name="Student",email="wf.student@example.com",password_hash=pwd.hash("Student@123"),role="STUDENT")
    db.add_all([teacher,student]);db.flush()
    db.add(TeacherSubject(teacher_id=teacher.id,subject_id=subject.id,academic_year="2026-27"))
    db.add(Enrollment(student_id=student.id,subject_id=subject.id,academic_year="2026-27"))
    resource=Resource(subject_id=subject.id,uploaded_by=teacher.id,title="Approved Notes",resource_type="REFERENCE",status="DRAFT",extracted_text="Artificial intelligence uses data and algorithms.",page_count=1)
    db.add(resource);db.commit()
    subject_id=subject.id;resource_id=resource.id;db.close()
    def override():
        db=SessionLocal()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override
    monkeypatch.setattr(extended,"set_resource_status",lambda resource_id,status:True)
    monkeypatch.setattr(extended,"generate_structured",lambda *a,**k:{"title":"Generated Notes","sections":[{"heading":"AI","points":["Grounded point"]}]})
    with TestClient(app) as client:
        login=lambda e,p:{"Authorization":"Bearer "+client.post("/api/auth/login",json={"email":e,"password":p}).json()["access_token"]}
        th=login("wf.teacher@example.com","Teacher@123")
        blocked=client.post("/api/ai/generate",headers=th,json={"subject_id":subject_id,"content_type":"notes","title":"Notes"})
        assert blocked.status_code==409
        approved=client.patch(f"/api/resources/{resource_id}/approve-v2",headers=th)
        assert approved.status_code==200
        generated=client.post("/api/ai/generate",headers=th,json={"subject_id":subject_id,"content_type":"notes","title":"Notes"})
        assert generated.status_code==200
        assert generated.json()["status"]=="IN_REVIEW"
        sh=login("wf.student@example.com","Student@123")
        assert client.get(f"/api/content?subject_id={subject_id}",headers=sh).json()==[]
        published=client.patch(f"/api/content/{generated.json()['id']}/status",headers=th,json={"status":"PUBLISHED"})
        assert published.status_code==200
        visible=client.get(f"/api/content?subject_id={subject_id}",headers=sh)
        assert [x["title"] for x in visible.json()]==["Notes"]
    app.dependency_overrides.clear()
