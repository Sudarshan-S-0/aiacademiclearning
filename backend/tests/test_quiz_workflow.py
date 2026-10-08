import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Department, Enrollment, Semester, Subject, User


@pytest.fixture()
def client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="QUIZ", name="Quiz Test")
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
    subject = Subject(
        semester_id=semester.id,
        code="QUIZ801",
        name="Quiz Subject",
        weeks=16,
        hours_per_week=4,
        lecture_duration_minutes=60,
    )
    admin = User(
        full_name="Quiz Admin",
        email="quiz-admin@example.com",
        password_hash=pwd.hash("Admin@123"),
        role="ADMIN",
    )
    student = User(
        full_name="Quiz Student",
        email="quiz-student@example.com",
        password_hash=pwd.hash("Student@123"),
        role="STUDENT",
    )
    db.add_all([subject, admin, student])
    db.flush()
    db.add(
        Enrollment(
            student_id=student.id,
            subject_id=subject.id,
            academic_year="2026-27",
        )
    )
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
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_quiz_lifecycle_and_student_publication_gate(client):
    test_client, subject_id = client
    admin_headers = login(test_client, "quiz-admin@example.com", "Admin@123")
    student_headers = login(test_client, "quiz-student@example.com", "Student@123")

    invalid_create = test_client.post(
        "/api/quizzes",
        headers=admin_headers,
        json={
            "subject_id": subject_id,
            "title": "Premature Quiz",
            "duration_minutes": 30,
            "status": "PUBLISHED",
        },
    )
    assert invalid_create.status_code == 400

    created = test_client.post(
        "/api/quizzes",
        headers=admin_headers,
        json={
            "subject_id": subject_id,
            "title": "Arrays Quiz",
            "duration_minutes": 30,
        },
    )
    assert created.status_code == 200, created.text
    quiz_id = created.json()["id"]

    empty_publish = test_client.patch(
        f"/api/quizzes/{quiz_id}/status?status=PUBLISHED",
        headers=admin_headers,
    )
    assert empty_publish.status_code == 400

    question = test_client.post(
        f"/api/quizzes/{quiz_id}/questions",
        headers=admin_headers,
        json={
            "question_text": "What is the index of the first array element?",
            "marks": 2,
            "correct_answer": "0",
            "options": ["0", "1", "2", "3"],
        },
    )
    assert question.status_code == 200, question.text
    question_id = question.json()["id"]

    published = test_client.patch(
        f"/api/quizzes/{quiz_id}/status?status=PUBLISHED",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text

    student_list = test_client.get(
        f"/api/quizzes?subject_id={subject_id}",
        headers=student_headers,
    )
    assert student_list.status_code == 200, student_list.text
    assert any(row["id"] == quiz_id and row["status"] == "PUBLISHED" for row in student_list.json())

    student_detail = test_client.get(
        f"/api/quizzes/{quiz_id}",
        headers=student_headers,
    )
    assert student_detail.status_code == 200, student_detail.text
    payload = student_detail.json()
    assert payload["status"] == "PUBLISHED"
    assert "correct_answer" not in payload["questions"][0]

    edit_after_publish = test_client.post(
        f"/api/quizzes/{quiz_id}/questions",
        headers=admin_headers,
        json={
            "question_text": "This edit must be blocked.",
            "marks": 1,
            "correct_answer": "yes",
        },
    )
    assert edit_after_publish.status_code == 409

    invalid_reverse = test_client.patch(
        f"/api/quizzes/{quiz_id}/status?status=DRAFT",
        headers=admin_headers,
    )
    assert invalid_reverse.status_code == 409

    attempt = test_client.post(
        "/api/quizzes/attempt",
        headers=student_headers,
        json={
            "quiz_id": quiz_id,
            "answers": [{"question_id": question_id, "answer": "0"}],
        },
    )
    assert attempt.status_code == 200, attempt.text
    result = attempt.json()
    assert result["score"] == 2
    assert result["total"] == 2
    assert result["percentage"] == 100

    progress = test_client.get("/api/student/progress", headers=student_headers)
    assert progress.status_code == 200, progress.text
    assert any(
        row["activity"] == "QUIZ"
        and row["score"] == 2
        and row["max_score"] == 2
        for row in progress.json()
    )

    archived = test_client.patch(
        f"/api/quizzes/{quiz_id}/status?status=ARCHIVED",
        headers=admin_headers,
    )
    assert archived.status_code == 200, archived.text

    hidden = test_client.get(
        f"/api/quizzes?subject_id={subject_id}",
        headers=student_headers,
    )
    assert hidden.status_code == 200, hidden.text
    assert all(row["id"] != quiz_id for row in hidden.json())

    unavailable_attempt = test_client.post(
        "/api/quizzes/attempt",
        headers=student_headers,
        json={
            "quiz_id": quiz_id,
            "answers": [{"question_id": question_id, "answer": "0"}],
        },
    )
    assert unavailable_attempt.status_code == 404

    invalid_republish = test_client.patch(
        f"/api/quizzes/{quiz_id}/status?status=PUBLISHED",
        headers=admin_headers,
    )
    assert invalid_republish.status_code == 409
