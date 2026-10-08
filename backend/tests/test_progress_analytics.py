import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Department, Enrollment, Progress, Semester, Subject, Topic, User


@pytest.fixture()
def client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="PROG", name="Progress Test")
    db.add(department)
    db.flush()
    semester = Semester(
        department_id=department.id,
        academic_year="2026-27",
        semester_number=8,
        regulation="TEST",
    )
    db.add(semester)
    db.flush()

    subject_a = Subject(semester_id=semester.id, code="PROG801", name="Algorithms")
    subject_b = Subject(semester_id=semester.id, code="PROG802", name="Databases")
    outsider_subject = Subject(semester_id=semester.id, code="PROG803", name="Networks")
    db.add_all([subject_a, subject_b, outsider_subject])
    db.flush()

    topic_a = Topic(
        subject_id=subject_a.id,
        unit_number=1,
        topic_name="Arrays",
        sequence_order=1,
        estimated_hours=2,
    )
    topic_b = Topic(
        subject_id=subject_a.id,
        unit_number=2,
        topic_name="Graphs",
        sequence_order=2,
        estimated_hours=2,
    )
    topic_outsider = Topic(
        subject_id=outsider_subject.id,
        unit_number=1,
        topic_name="Routing",
        sequence_order=1,
        estimated_hours=2,
    )
    admin = User(
        full_name="Progress Admin",
        email="progress-admin@example.com",
        password_hash=pwd.hash("Admin@123"),
        role="ADMIN",
    )
    student = User(
        full_name="Progress Student",
        email="progress-student@example.com",
        password_hash=pwd.hash("Student@123"),
        role="STUDENT",
    )
    other_student = User(
        full_name="Other Student",
        email="other-student@example.com",
        password_hash=pwd.hash("Student@123"),
        role="STUDENT",
    )
    db.add_all([topic_a, topic_b, topic_outsider, admin, student, other_student])
    db.flush()
    db.add_all([
        Enrollment(student_id=student.id, subject_id=subject_a.id, academic_year="2026-27"),
        Enrollment(student_id=student.id, subject_id=subject_b.id, academic_year="2026-27"),
        Enrollment(student_id=other_student.id, subject_id=outsider_subject.id, academic_year="2026-27"),
        Progress(student_id=student.id, subject_id=subject_a.id, topic_id=topic_a.id, activity_type="QUIZ", score=8, max_score=10, completed=True),
        Progress(student_id=student.id, subject_id=subject_a.id, topic_id=topic_a.id, activity_type="ASSIGNMENT", score=4, max_score=10, completed=True),
        Progress(student_id=student.id, subject_id=subject_a.id, topic_id=topic_b.id, activity_type="QUIZ", score=9, max_score=10, completed=True),
        Progress(student_id=other_student.id, subject_id=outsider_subject.id, topic_id=topic_outsider.id, activity_type="QUIZ", score=0, max_score=10, completed=True),
    ])
    db.commit()
    db.close()

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def login(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "progress-student@example.com", "password": "Student@123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_student_progress_analytics_is_subject_and_user_isolated(client):
    headers = login(client)
    response = client.get("/api/analytics/student-v2", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()

    assert {item["subject"] for item in payload["subjects"]} == {"Algorithms", "Databases"}
    assert all(item["subject"] != "Networks" for item in payload["subjects"])

    algorithms = next(item for item in payload["subjects"] if item["subject"] == "Algorithms")
    assert algorithms["activities"] == 3
    assert algorithms["completed"] == 3
    assert algorithms["percentage"] == 70

    topics = payload["topics"]
    arrays = next(item for item in topics if item["topic"] == "Arrays")
    graphs = next(item for item in topics if item["topic"] == "Graphs")

    assert arrays["percentage"] == 60
    assert arrays["is_weak"] is True
    assert arrays["recommendation"].startswith("Priority revision")

    assert graphs["percentage"] == 90
    assert graphs["is_weak"] is False

    assert payload["overall"]["activities"] == 3
    assert payload["overall"]["score"] == 21
    assert payload["overall"]["max_score"] == 30
    assert payload["overall"]["percentage"] == 70


def test_student_progress_endpoint_does_not_expose_another_students_progress(client):
    headers = login(client)
    response = client.get("/api/student/progress", headers=headers)

    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 3
    assert all(row["score"] >= 0 for row in rows)
