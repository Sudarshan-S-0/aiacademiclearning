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

        # Approving a replacement resource version must archive the old approved
        # version so retrieval cannot mix stale and current source material.
        session = next(app.dependency_overrides[get_db]())
        try:
            teacher = session.query(User).filter_by(email="wf.teacher@example.com").one()
            newer = Resource(
                subject_id=subject_id,
                uploaded_by=teacher.id,
                title="Approved Notes",
                resource_type="REFERENCE",
                status="DRAFT",
                extracted_text="Updated approved academic source.",
                page_count=1,
                version=2,
                parent_resource_id=resource_id,
            )
            session.add(newer)
            session.commit()
            newer_resource_id = newer.id
        finally:
            session.close()

        replacement_approval = client.patch(
            f"/api/resources/{newer_resource_id}/approve-v2",
            headers=th,
        )
        assert replacement_approval.status_code == 200, replacement_approval.text
        session = next(app.dependency_overrides[get_db]())
        try:
            assert session.get(Resource, resource_id).status == "ARCHIVED"
            assert session.get(Resource, newer_resource_id).status == "APPROVED"
        finally:
            session.close()

        cannot_reapprove_archived = client.patch(
            f"/api/resources/{resource_id}/approve-v2",
            headers=th,
        )
        assert cannot_reapprove_archived.status_code == 409

        # The legacy status endpoint must enforce the same version rules.
        session = next(app.dependency_overrides[get_db]())
        try:
            teacher = session.query(User).filter_by(email="wf.teacher@example.com").one()
            latest = Resource(
                subject_id=subject_id,
                uploaded_by=teacher.id,
                title="Approved Notes",
                resource_type="REFERENCE",
                status="DRAFT",
                extracted_text="Third version.",
                page_count=1,
                version=3,
                parent_resource_id=newer_resource_id,
            )
            session.add(latest)
            session.commit()
            latest_resource_id = latest.id
        finally:
            session.close()

        legacy_approval = client.patch(
            f"/api/resources/{latest_resource_id}/status?status=APPROVED",
            headers=th,
        )
        assert legacy_approval.status_code == 200, legacy_approval.text
        session = next(app.dependency_overrides[get_db]())
        try:
            assert session.get(Resource, newer_resource_id).status == "ARCHIVED"
            assert session.get(Resource, latest_resource_id).status == "APPROVED"
        finally:
            session.close()

        legacy_reactivation = client.patch(
            f"/api/resources/{resource_id}/status?status=APPROVED",
            headers=th,
        )
        assert legacy_reactivation.status_code == 409
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


def test_grounded_answer_ignores_unapproved_context(monkeypatch):
    from app.services import ai
    def fake_generate(prompt, temperature=0.2):
        assert "approved concept" in prompt
        assert "draft secret" not in prompt
        return "The approved concept is supported."
    monkeypatch.setattr(ai, "gemini_generate", fake_generate)
    result=ai.grounded_answer("What is the approved concept?",[
        {"status":"DRAFT","source":"Draft","text":"draft secret","citation":"page 1"},
        {"status":"APPROVED","source":"Notes","text":"approved concept","citation":"page 2, section Classification"},
    ])
    assert result["answer"].startswith("The approved concept")
    assert result["sources"]==["page 2, section Classification"]


def test_grounded_answer_returns_exact_fallback(monkeypatch):
    from app.services import ai
    monkeypatch.setattr(ai, "gemini_generate", lambda *a,**k: None)
    result=ai.grounded_answer("What is quantum networking?",[
        {"status":"APPROVED","source":"Notes","text":"Classification predicts categories.","citation":"page 1"},
    ])
    assert result["answer"]==ai.APPROVED_RESOURCE_MESSAGE
    assert result["sources"]==[]


def test_qdrant_search_filters_subject_and_approved_status(monkeypatch):
    from app.services import qdrant
    captured={}
    class FakeResponse:
        status_code=200
        def json(self): return {"result":[{"payload":{"status":"APPROVED","subject_id":7,"text":"approved"}}]}
        def raise_for_status(self): return None
    def fake_post(url,**kwargs):
        captured["json"]=kwargs["json"]
        return FakeResponse()
    monkeypatch.setattr(qdrant,"ensure_collection",lambda:True)
    monkeypatch.setattr(qdrant,"embed",lambda text:[0.0]*384)
    monkeypatch.setattr(qdrant.httpx,"post",fake_post)
    monkeypatch.setattr(qdrant.settings,"qdrant_url","http://qdrant.test")
    rows=qdrant.search_chunks(7,"classification",top_k=5)
    must=captured["json"]["filter"]["must"]
    assert {"key":"subject_id","match":{"value":7}} in must
    assert {"key":"status","match":{"value":"APPROVED"}} in must
    assert captured["json"]["limit"]==5
    assert rows[0]["status"]=="APPROVED"


def test_ai_ask_enforces_subject_isolation(monkeypatch):
    db_path=tempfile.mktemp(suffix=".db")
    engine=create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal=sessionmaker(bind=engine)
    db=SessionLocal()

    d=Department(code="AI",name="AI Security")
    db.add(d);db.flush()
    sem=Semester(department_id=d.id,academic_year="2026-27",semester_number=1,regulation="TEST")
    db.add(sem);db.flush()
    allowed=Subject(semester_id=sem.id,code="AI101",name="Allowed Subject")
    private=Subject(semester_id=sem.id,code="AI102",name="Private Subject")
    db.add_all([allowed,private]);db.flush()

    teacher=User(full_name="AI Teacher",email="ai.teacher@example.com",
                 password_hash=pwd.hash("Teacher@123"),role="TEACHER")
    student=User(full_name="AI Student",email="ai.student@example.com",
                 password_hash=pwd.hash("Student@123"),role="STUDENT")
    db.add_all([teacher,student]);db.flush()
    db.add(Enrollment(student_id=student.id,subject_id=allowed.id,academic_year="2026-27"))

    allowed_resource=Resource(
        subject_id=allowed.id,uploaded_by=teacher.id,title="Allowed Notes",
        resource_type="REFERENCE",status="APPROVED",
        extracted_text="Approved material for the allowed subject.",page_count=1
    )
    private_resource=Resource(
        subject_id=private.id,uploaded_by=teacher.id,title="Private Notes",
        resource_type="REFERENCE",status="APPROVED",
        extracted_text="Private material that must never be exposed.",page_count=1
    )
    db.add_all([allowed_resource,private_resource]);db.commit()
    allowed_id=allowed.id
    private_id=private.id
    db.close()

    def override():
        db=SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db]=override

    captured={}
    def fake_answer(question, contexts):
        captured["contexts"]=contexts
        return {"answer":"Grounded answer","sources":[x["source"] for x in contexts]}

    monkeypatch.setattr("app.api.routes.search_chunks",lambda *a,**k: [])
    monkeypatch.setattr("app.api.routes.grounded_answer",fake_answer)

    with TestClient(app) as client:
        login=client.post(
            "/api/auth/login",
            json={"email":"ai.student@example.com","password":"Student@123"},
        )
        assert login.status_code==200,login.text
        headers={"Authorization":f"Bearer {login.json()['access_token']}"}

        denied=client.post(
            "/api/ai/ask",
            headers=headers,
            json={"subject_id":private_id,"question":"What is in the private subject?"},
        )
        assert denied.status_code==403,denied.text

        allowed_response=client.post(
            "/api/ai/ask",
            headers=headers,
            json={"subject_id":allowed_id,"question":"What is the approved material?"},
        )
        assert allowed_response.status_code==200,allowed_response.text
        assert captured["contexts"]
        assert [x["source"] for x in captured["contexts"]]==["Allowed Notes"]

    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_legacy_ai_context_validation_rechecks_current_resource_status():
    from types import SimpleNamespace
    from app.api.routes import approved_contexts_from_hits

    class FakeDB:
        resources = {
            1: SimpleNamespace(id=1, subject_id=7, status="ARCHIVED", title="Archived Notes"),
            2: SimpleNamespace(id=2, subject_id=7, status="APPROVED", title="Approved Notes"),
            3: SimpleNamespace(id=3, subject_id=8, status="APPROVED", title="Other Subject Notes"),
        }

        def get(self, model, resource_id):
            return self.resources.get(resource_id)

    hits = [
        {"status": "APPROVED", "subject_id": 7, "resource_id": 1, "text": "stale archived text"},
        {"status": "APPROVED", "subject_id": 7, "resource_id": 2, "text": "approved text", "page": 2, "section": "Arrays"},
        {"status": "APPROVED", "subject_id": 8, "resource_id": 3, "text": "other subject text"},
    ]

    contexts = approved_contexts_from_hits(FakeDB(), 7, hits)
    assert len(contexts) == 1
    assert contexts[0]["source"] == "Approved Notes"
    assert contexts[0]["text"] == "approved text"
    assert contexts[0]["citation"] == "page 2, Arrays"
