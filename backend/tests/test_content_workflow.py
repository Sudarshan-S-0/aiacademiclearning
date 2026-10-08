import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Content, Department, Enrollment, Semester, Subject, User, TeacherSubject, Topic


@pytest.fixture()
def client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="CNT", name="Content Test")
    db.add(department)
    db.flush()
    semester = Semester(department_id=department.id, academic_year="2026-27",
                        semester_number=8, regulation="TEST")
    db.add(semester)
    db.flush()
    subject = Subject(semester_id=semester.id, code="CNT801", name="Content Subject",
                      weeks=16, hours_per_week=4, lecture_duration_minutes=60)
    admin = User(full_name="Content Admin", email="content-admin@example.com",
                 password_hash=pwd.hash("Admin@123"), role="ADMIN")
    student = User(full_name="Content Student", email="content-student@example.com",
                   password_hash=pwd.hash("Student@123"), role="STUDENT")
    teacher = User(full_name="Content Teacher", email="content-teacher@example.com",
                   password_hash=pwd.hash("Teacher@123"), role="TEACHER")
    db.add_all([subject, admin, student, teacher])
    db.flush()
    db.add(Enrollment(student_id=student.id, subject_id=subject.id,
                      academic_year="2026-27"))
    db.add(TeacherSubject(teacher_id=teacher.id, subject_id=subject.id, academic_year="2026-27"))
    db.add(Topic(subject_id=subject.id, unit_number=1, topic_name="Arrays", sequence_order=1, estimated_hours=4))
    db.commit()
    subject_id = subject.id
    db.close()

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, subject_id
    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_content_review_publish_and_student_isolation(client):
    test_client, subject_id = client
    admin_headers = login(test_client, "content-admin@example.com", "Admin@123")
    student_headers = login(test_client, "content-student@example.com", "Student@123")

    response = test_client.post(
        "/api/ai/generate",
        headers=admin_headers,
        json={
            "subject_id": subject_id,
            "content_type": "NOTES",
            "title": "Approved Notes",
            "instructions": "Explain arrays clearly.",
        },
    )
    # AI generation requires approved source context; create the lifecycle record
    # directly for this workflow test so it remains deterministic and offline.
    if response.status_code == 409:
        # The test database intentionally has no external AI/resource dependency.
        # Use a direct database insert through the test dependency.
        session = next(app.dependency_overrides[get_db]())
        try:
            content = Content(subject_id=subject_id, title="Draft Notes", content_type="NOTES",
                              body="Arrays are ordered collections.", status="IN_REVIEW",
                              version=1, generated_by_ai=True)
            session.add(content)
            session.commit()
            content_id = content.id
        finally:
            session.close()
    else:
        assert response.status_code == 200, response.text
        content_id = response.json()["id"]

    approved = test_client.patch(f"/api/content/{content_id}/status", headers=admin_headers,
                                 json={"status": "APPROVED"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"

    edited = test_client.patch(f"/api/content/{content_id}", headers=admin_headers,
                               json={"body": "Arrays store elements in indexed order."})
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "IN_REVIEW"
    assert edited.json()["version"] == 2

    republish = test_client.patch(f"/api/content/{content_id}/status", headers=admin_headers,
                                  json={"status": "APPROVED"})
    assert republish.status_code == 200, republish.text
    published = test_client.patch(f"/api/content/{content_id}/status", headers=admin_headers,
                                  json={"status": "PUBLISHED"})
    assert published.status_code == 200, published.text

    visible = test_client.get("/api/student/content", headers=student_headers)
    assert visible.status_code == 200, visible.text
    rows = visible.json()
    assert any(row["id"] == content_id and row["status"] == "PUBLISHED" for row in rows)

    archived = test_client.patch(f"/api/content/{content_id}/status", headers=admin_headers,
                                 json={"status": "ARCHIVED"})
    assert archived.status_code == 200, archived.text
    hidden = test_client.get("/api/student/content", headers=student_headers)
    assert hidden.status_code == 200, hidden.text
    assert all(row["id"] != content_id for row in hidden.json())


def test_student_cannot_read_unpublished_content(client):
    test_client, subject_id = client
    admin_headers = login(test_client, "content-admin@example.com", "Admin@123")
    student_headers = login(test_client, "content-student@example.com", "Student@123")

    session = next(app.dependency_overrides[get_db]())
    try:
        content = Content(subject_id=subject_id, title="Private Draft", content_type="NOTES",
                          body="Not published.", status="IN_REVIEW", version=1)
        session.add(content)
        session.commit()
        content_id = content.id
    finally:
        session.close()

    direct = test_client.get(f"/api/content/{content_id}", headers=student_headers)
    assert direct.status_code == 404
    listed = test_client.get("/api/student/content", headers=student_headers)
    assert listed.status_code == 200
    assert all(row["id"] != content_id for row in listed.json())

    invalid = test_client.patch(f"/api/content/{content_id}/status", headers=admin_headers,
                                json={"status": "PUBLISHED"})
    assert invalid.status_code == 409


def test_teacher_can_approve_and_publish_but_student_cannot_change_lifecycle(client):
    test_client, subject_id = client
    teacher_headers = login(test_client, "content-teacher@example.com", "Teacher@123")
    student_headers = login(test_client, "content-student@example.com", "Student@123")

    session = next(app.dependency_overrides[get_db]())
    try:
        content = Content(subject_id=subject_id, title="Teacher Review Notes",
                          content_type="NOTES", body="Reviewed academic notes.",
                          status="IN_REVIEW", version=1)
        session.add(content)
        session.commit()
        content_id = content.id
    finally:
        session.close()

    approved = test_client.patch(f"/api/content/{content_id}/status",
                                 headers=teacher_headers, json={"status": "APPROVED"})
    assert approved.status_code == 200, approved.text

    published = test_client.patch(f"/api/content/{content_id}/status",
                                   headers=teacher_headers, json={"status": "PUBLISHED"})
    assert published.status_code == 200, published.text

    forbidden = test_client.patch(f"/api/content/{content_id}/status",
                                  headers=student_headers, json={"status": "ARCHIVED"})
    assert forbidden.status_code == 403

    student_view = test_client.get(f"/api/content/{content_id}", headers=student_headers)
    assert student_view.status_code == 200
    assert student_view.json()["status"] == "PUBLISHED"


def test_content_status_transitions_reject_skipping_review(client):
    test_client, subject_id = client
    admin_headers = login(test_client, "content-admin@example.com", "Admin@123")

    session = next(app.dependency_overrides[get_db]())
    try:
        content = Content(subject_id=subject_id, title="Lifecycle Test",
                          content_type="NOTES", body="Draft.",
                          status="DRAFT", version=1)
        session.add(content)
        session.commit()
        content_id = content.id
    finally:
        session.close()

    skipped = test_client.patch(f"/api/content/{content_id}/status",
                                headers=admin_headers, json={"status": "PUBLISHED"})
    assert skipped.status_code == 409

    reviewed = test_client.patch(f"/api/content/{content_id}/status",
                                  headers=admin_headers, json={"status": "IN_REVIEW"})
    assert reviewed.status_code == 200

    approved = test_client.patch(f"/api/content/{content_id}/status",
                                 headers=admin_headers, json={"status": "APPROVED"})
    assert approved.status_code == 200
