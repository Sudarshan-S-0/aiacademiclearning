from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import tempfile
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.session import Base,get_db
from app.models.models import User,Department,Semester,Subject,TeacherSubject,Enrollment,Resource
from app.api.routes import pwd
import app.api.extended_routes as extended

def test_resource_ai_publication_gates(monkeypatch):
    db_path=tempfile.mktemp(suffix=".db")
    engine=create_engine(f"sqlite:///{db_path}")
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
        def login(e, p):
            response = client.post(
                "/api/auth/login",
                json={"email": e, "password": p},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert "access_token" in data, response.text
            token = data["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            me = client.get("/api/me", headers=headers)
            assert me.status_code == 200, me.text
            return headers
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
        approved_content=client.patch(
            f"/api/content/{generated.json()['id']}/status",
            headers=th,
            json={"status":"APPROVED"},
        )
        assert approved_content.status_code==200, approved_content.text
        published=client.patch(
            f"/api/content/{generated.json()['id']}/status",
            headers=th,
            json={"status":"PUBLISHED"},
        )
        assert published.status_code==200, published.text
        visible=client.get(f"/api/content?subject_id={subject_id}",headers=sh)
        assert [x["title"] for x in visible.json()]==["Notes"]
    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path): os.remove(db_path)


def test_resource_chunks_are_persisted_with_citations(monkeypatch):
    db_path=tempfile.mktemp(suffix=".db")
    engine=create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal=sessionmaker(bind=engine)
    db=SessionLocal()
    d=Department(code="CH",name="Chunks")
    db.add(d);db.flush()
    s=Semester(department_id=d.id,academic_year="2026-27",semester_number=1,regulation="TEST")
    db.add(s);db.flush()
    subject=Subject(semester_id=s.id,code="CH101",name="Chunk Subject")
    db.add(subject);db.flush()
    teacher=User(full_name="Chunk Teacher",email="chunk.teacher@example.com",password_hash=pwd.hash("Teacher@123"),role="TEACHER")
    db.add(teacher);db.flush()
    db.add(TeacherSubject(teacher_id=teacher.id,subject_id=subject.id,academic_year="2026-27"))
    db.commit()
    subject_id=subject.id
    db.close()

    def override():
        db=SessionLocal()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override
    monkeypatch.setattr("app.api.routes.put_object",lambda *a,**k:True)
    monkeypatch.setattr("app.api.routes.upsert_chunks",lambda *a,**k:True)

    with TestClient(app) as client:
        response=client.post("/api/auth/login",json={"email":"chunk.teacher@example.com","password":"Teacher@123"})
        assert response.status_code==200,response.text
        headers={"Authorization":f"Bearer {response.json()['access_token']}"}
        upload=client.post(
            f"/api/resources?subject_id={subject_id}&title=Notes&resource_type=REFERENCE",
            headers=headers,
            files={"file":("notes.txt",b"Machine learning learns patterns from data.\n\nClassification predicts categories.","text/plain")},
        )
        assert upload.status_code==200,upload.text
        data=upload.json()
        assert data["chunks"]>=1

        chunks=client.get(f"/api/resources/{data['id']}/chunks",headers=headers)
        assert chunks.status_code==200,chunks.text
        rows=chunks.json()
        assert rows
        assert rows[0]["page"]==1
        assert rows[0]["section"]=="document"
        assert rows[0]["qdrant_point_id"]

    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path): os.remove(db_path)
