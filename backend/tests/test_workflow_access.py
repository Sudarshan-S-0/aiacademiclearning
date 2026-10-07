import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import tempfile

from app.main import app
from app.db.session import Base, get_db
from app.models.models import User, Department, Semester, Subject, TeacherSubject, Enrollment, Content
from app.api.routes import pwd


@pytest.fixture()
def client():
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


def test_teacher_cannot_access_unassigned_subject(client):
    headers = login(client, "teacher@example.com", "Teacher@123")

    response = client.get(
        "/api/subjects/2/topics",
        headers=headers,
    )
    assert response.status_code == 403
