import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import tempfile

from app.main import app, _hits
from app.db.session import Base, get_db
from app.models.models import User, Department, Semester, Subject, TeacherSubject, Enrollment, Content, Resource, ResourceChunk, Topic, Quiz, TeachingPlan
from app.api.routes import pwd


@pytest.fixture()
def client():
    # The app's in-memory rate limiter is shared across TestClient instances.
    # Reset it for each test so unrelated tests do not consume this test's quota.
    _hits.clear()
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    db = SessionLocal()
    department = Department(code="TEST", name="Test Department")
    db.add(department)
    db.flush()

    semester = Semester(
        department_id=department.id,
        academic_year="2026-27",
        semester_number=1,
        regulation="TEST",
    )
    db.add(semester)
    db.flush()

    subject_a = Subject(
        semester_id=semester.id,
        code="TEST101",
        name="Approved Resources",
        weeks=16,
        hours_per_week=4,
        lecture_duration_minutes=60,
    )
    subject_b = Subject(
        semester_id=semester.id,
        code="TEST102",
        name="Private Subject",
        weeks=16,
        hours_per_week=4,
        lecture_duration_minutes=60,
    )
    db.add_all([subject_a, subject_b])
    db.flush()

    teacher = User(
        full_name="Test Teacher",
        email="teacher@example.com",
        password_hash=pwd.hash("Teacher@123"),
        role="TEACHER",
    )
    student = User(
        full_name="Test Student",
        email="student@example.com",
        password_hash=pwd.hash("Student@123"),
        role="STUDENT",
    )
    db.add_all([teacher, student])
    db.flush()

    db.add(
        TeacherSubject(
            teacher_id=teacher.id,
            subject_id=subject_a.id,
            academic_year="2026-27",
        )
    )
    db.add(
        Enrollment(
            student_id=student.id,
            subject_id=subject_a.id,
            academic_year="2026-27",
        )
    )

    db.add_all(
        [
            Content(
                subject_id=subject_a.id,
                title="Draft Notes",
                content_type="NOTES",
                body="Draft only",
                status="IN_REVIEW",
                created_by=teacher.id,
            ),
            Content(
                subject_id=subject_a.id,
                title="Published Notes",
                content_type="NOTES",
                body="Published academic material",
                status="PUBLISHED",
                created_by=teacher.id,
            ),
        ]
    )
    db.commit()
    db.close()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path): os.remove(db_path)


def login(client, email, password):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "access_token" in data, response.text
    token = data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers


def test_student_sees_only_assigned_subjects_and_published_content(client):
    headers = login(client, "student@example.com", "Student@123")

    subjects = client.get("/api/subjects", headers=headers)
    assert subjects.status_code == 200
    assert [row["code"] for row in subjects.json()] == ["TEST101"]

    content = client.get(
        "/api/content?subject_id=1",
        headers=headers,
    )
    assert content.status_code == 200
    titles = [row["title"] for row in content.json()]
    assert titles == ["Published Notes"]


def test_student_cannot_access_unassigned_subject(client):
    headers = login(client, "student@example.com", "Student@123")

    response = client.get(
        "/api/content?subject_id=2",
        headers=headers,
    )
    assert response.status_code == 403


def test_resource_access_and_download_isolation(client, monkeypatch):
    db = next(iter(app.dependency_overrides[get_db]()))
    try:
        subject_a_resource = Resource(
            subject_id=1,
            uploaded_by=1,
            title="Approved Resource",
            resource_type="REFERENCE",
            storage_key="subject-a/approved.txt",
            status="APPROVED",
            extracted_text="Approved material",
            page_count=1,
        )
        draft_resource = Resource(
            subject_id=1,
            uploaded_by=1,
            title="Draft Resource",
            resource_type="REFERENCE",
            storage_key="subject-a/draft.txt",
            status="DRAFT",
            extracted_text="Draft material",
            page_count=1,
        )
        private_resource = Resource(
            subject_id=2,
            uploaded_by=1,
            title="Private Resource",
            resource_type="REFERENCE",
            storage_key="subject-b/private.txt",
            status="APPROVED",
            extracted_text="Private material",
            page_count=1,
        )
        db.add_all([subject_a_resource, draft_resource, private_resource])
        db.flush()
        db.add(
            ResourceChunk(
                resource_id=subject_a_resource.id,
                subject_id=1,
                chunk_index=0,
                text="Approved chunk",
                page_number=1,
                section="document",
                qdrant_point_id="resource-test-point",
            )
        )
        db.commit()
        approved_id = subject_a_resource.id
        draft_id = draft_resource.id
        private_id = private_resource.id
    finally:
        db.close()

    monkeypatch.setattr(
        "app.api.routes.get_object",
        lambda key: b"approved file" if key == "subject-a/approved.txt" else b"private file",
    )

    student_headers = login(client, "student@example.com", "Student@123")
    teacher_headers = login(client, "teacher@example.com", "Teacher@123")

    student_resources = client.get(
        "/api/resources?subject_id=1",
        headers=student_headers,
    )
    assert student_resources.status_code == 200
    assert {row["id"] for row in student_resources.json()} == {approved_id}

    draft_download = client.get(
        f"/api/resources/{draft_id}/download",
        headers=student_headers,
    )
    assert draft_download.status_code == 403

    approved_download = client.get(
        f"/api/resources/{approved_id}/download",
        headers=student_headers,
    )
    assert approved_download.status_code == 200
    assert approved_download.content == b"approved file"

    approved_chunks = client.get(
        f"/api/resources/{approved_id}/chunks",
        headers=student_headers,
    )
    assert approved_chunks.status_code == 200
    assert approved_chunks.json()[0]["text"] == "Approved chunk"

    private_download = client.get(
        f"/api/resources/{private_id}/download",
        headers=student_headers,
    )
    assert private_download.status_code == 404

    private_teacher_download = client.get(
        f"/api/resources/{private_id}/download",
        headers=teacher_headers,
    )
    assert private_teacher_download.status_code == 404

def test_teacher_cannot_access_unassigned_subject(client):
    headers = login(client, "teacher@example.com", "Teacher@123")

    response = client.get(
        "/api/subjects/2/topics",
        headers=headers,
    )
    assert response.status_code == 403


def test_teacher_cannot_mutate_records_in_unassigned_subject(client):
    db = next(iter(app.dependency_overrides[get_db]()))
    try:
        teacher = db.query(User).filter_by(email="teacher@example.com").one()
        private_resource = Resource(
            subject_id=2,
            uploaded_by=teacher.id,
            title="Private Resource",
            resource_type="REFERENCE",
            status="DRAFT",
            extracted_text="Private material",
        )
        private_content = Content(
            subject_id=2,
            title="Private Draft",
            content_type="NOTES",
            body="Private body",
            status="IN_REVIEW",
            version=1,
            created_by=teacher.id,
        )
        private_topic = Topic(
            subject_id=2,
            unit_number=1,
            topic_name="Private Topic",
            sequence_order=1,
            estimated_hours=2,
        )
        private_quiz = Quiz(
            subject_id=2,
            title="Private Quiz",
            duration_minutes=20,
            status="DRAFT",
        )
        db.add_all([private_resource, private_content, private_topic, private_quiz])
        db.flush()
        private_plan = TeachingPlan(
            subject_id=2,
            topic_id=private_topic.id,
            planned_week=1,
            planned_hours=2,
            status="PLANNED",
        )
        db.add(private_plan)
        db.commit()
        plan_id = private_plan.id
        resource_id = private_resource.id
        content_id = private_content.id
        topic_id = private_topic.id
        quiz_id = private_quiz.id
    finally:
        db.close()

    headers = login(client, "teacher@example.com", "Teacher@123")

    resource_update = client.patch(
        f"/api/resources/{resource_id}/status?status=APPROVED",
        headers=headers,
    )
    assert resource_update.status_code == 404

    content_edit = client.patch(
        f"/api/content/{content_id}",
        headers=headers,
        json={"body": "Unauthorized change"},
    )
    assert content_edit.status_code == 404

    content_publish = client.patch(
        f"/api/content/{content_id}/status",
        headers=headers,
        json={"status": "APPROVED"},
    )
    assert content_publish.status_code == 404

    topic_edit = client.patch(
        f"/api/topics/{topic_id}",
        headers=headers,
        json={"estimated_hours": 99},
    )
    assert topic_edit.status_code == 404

    plan_edit = client.post(
        "/api/teaching-plan/edit/2",
        headers=headers,
        json={"action": "HOURS", "topic_id": topic_id, "value": 99},
    )
    assert plan_edit.status_code == 403

    plan_update = client.post(
        "/api/teaching-plan/2/update",
        headers=headers,
        json={"action": "duration", "topic_id": topic_id, "value": 99},
    )
    assert plan_update.status_code == 403

    quiz_publish = client.patch(
        f"/api/quizzes/{quiz_id}/status?status=PUBLISHED",
        headers=headers,
    )
    assert quiz_publish.status_code == 404

    verify = next(iter(app.dependency_overrides[get_db]()))
    try:
        assert verify.get(Resource, resource_id).status == "DRAFT"
        assert verify.get(Content, content_id).body == "Private body"
        assert verify.get(Content, content_id).status == "IN_REVIEW"
        assert verify.get(Topic, topic_id).estimated_hours == 2
        assert verify.get(Quiz, quiz_id).status == "DRAFT"
        assert verify.get(TeachingPlan, plan_id).planned_hours == 2
    finally:
        verify.close()
