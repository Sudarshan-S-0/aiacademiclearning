import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Department, Enrollment, Semester, Subject, User, Topic


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
    second_student = User(
        full_name="Second Quiz Student",
        email="quiz-student-2@example.com",
        password_hash=pwd.hash("Student2@123"),
        role="STUDENT",
    )
    db.add_all([subject, admin, student, second_student])
    db.flush()
    topic = Topic(subject_id=subject.id, unit_number=1, topic_name='Arrays', sequence_order=1, estimated_hours=2, status='ACTIVE')
    db.add(topic)
    db.flush()
    db.add_all([
        Enrollment(
            student_id=student.id,
            subject_id=subject.id,
            academic_year="2026-27",
        ),
        Enrollment(
            student_id=second_student.id,
            subject_id=subject.id,
            academic_year="2026-27",
        ),
    ])
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

    invalid_options = test_client.post(
        f"/api/quizzes/{quiz_id}/questions",
        headers=admin_headers,
        json={
            "question_text": "Invalid question with duplicate options?",
            "marks": 1,
            "correct_answer": "A",
            "options": ["A", "A", "B", "C"],
            "topic_id": 1,
        },
    )
    assert invalid_options.status_code == 400

    invalid_answer = test_client.post(
        f"/api/quizzes/{quiz_id}/questions",
        headers=admin_headers,
        json={
            "question_text": "Correct answer is not an option?",
            "marks": 1,
            "correct_answer": "Z",
            "options": ["A", "B", "C", "D"],
            "topic_id": 1,
        },
    )
    assert invalid_answer.status_code == 400

    question = test_client.post(
        f"/api/quizzes/{quiz_id}/questions",
        headers=admin_headers,
        json={
            "question_text": "What is the index of the first array element?",
            "marks": 2,
            "correct_answer": "0",
            "options": ["0", "1", "2", "3"],
            "topic_id": 1,
        },
    )
    assert question.status_code == 200, question.text
    question_id = question.json()["id"]

    published = test_client.patch(
        f"/api/quizzes/{quiz_id}/status?status=PUBLISHED",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text

    # Published assessments are immutable: generation must not replace their questions.
    regenerate_published = test_client.post(
        f"/api/quizzes/{quiz_id}/generate",
        headers=admin_headers,
    )
    assert regenerate_published.status_code == 409
    unchanged = test_client.get(f"/api/quizzes/{quiz_id}", headers=admin_headers)
    assert unchanged.status_code == 200, unchanged.text
    assert [item["id"] for item in unchanged.json()["questions"]] == [question_id]

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

    foreign_answer = test_client.post(
        "/api/quizzes/attempt",
        headers=student_headers,
        json={
            "quiz_id": quiz_id,
            "answers": [{"question_id": 999999, "answer": "0"}],
        },
    )
    assert foreign_answer.status_code == 400

    duplicate_answers = test_client.post(
        "/api/quizzes/attempt",
        headers=student_headers,
        json={
            "quiz_id": quiz_id,
            "answers": [
                {"question_id": question_id, "answer": "0"},
                {"question_id": question_id, "answer": "0"},
            ],
        },
    )
    assert duplicate_answers.status_code == 400

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

    # Assessment results must be scoped to the authenticated student, even
    # when another student is enrolled in the same subject and quiz.
    second_student_headers = login(
        test_client, "quiz-student-2@example.com", "Student2@123"
    )
    second_student_progress = test_client.get(
        "/api/student/progress", headers=second_student_headers
    )
    assert second_student_progress.status_code == 200, second_student_progress.text
    assert second_student_progress.json() == []

    second_student_analytics = test_client.get(
        "/api/analytics/student-v2", headers=second_student_headers
    )
    assert second_student_analytics.status_code == 200, second_student_analytics.text
    second_subject = next(
        item for item in second_student_analytics.json()["subjects"]
        if item["subject"] == "Quiz Subject"
    )
    assert second_subject["activities"] == 0
    assert second_subject["completed"] == 0
    assert second_subject["score"] == 0
    assert second_subject["max_score"] == 0

    weak = test_client.get('/api/student/weak-topics', headers=student_headers)
    assert weak.status_code == 200, weak.text
    weak_rows = weak.json()
    assert weak_rows
    assert weak_rows[0]['topic'] == 'Arrays'
    assert weak_rows[0]['percentage'] == 100
    assert weak_rows[0]['recommendation'].startswith('Review the approved resources')

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


def test_invalid_ai_questions_do_not_delete_existing_draft_questions(client, monkeypatch):
    from app.api import extended_routes

    test_client, subject_id = client
    admin_headers = login(test_client, "quiz-admin@example.com", "Admin@123")
    created = test_client.post(
        "/api/quizzes",
        headers=admin_headers,
        json={"subject_id": subject_id, "title": "Draft Quiz", "duration_minutes": 20},
    )
    assert created.status_code == 200, created.text
    quiz_id = created.json()["id"]
    question = test_client.post(
        f"/api/quizzes/{quiz_id}/questions",
        headers=admin_headers,
        json={
            "question_text": "Existing question?",
            "marks": 1,
            "correct_answer": "Yes",
            "options": ["Yes", "No", "Maybe", "Unknown"],
            "topic_id": 1,
        },
    )
    assert question.status_code == 200, question.text
    question_id = question.json()["id"]

    monkeypatch.setattr(
        extended_routes,
        "approved_contexts",
        lambda *args, **kwargs: [{"status": "APPROVED", "source": "Notes", "text": "Grounded context."}],
    )
    monkeypatch.setattr(
        extended_routes,
        "generate_structured",
        lambda *args, **kwargs: {"questions": [{"question": "Invalid question?", "answer": "A", "options": ["A", "B"]}]},
    )

    generated = test_client.post(
        f"/api/quizzes/{quiz_id}/generate",
        headers=admin_headers,
    )
    assert generated.status_code == 502

    detail = test_client.get(f"/api/quizzes/{quiz_id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert [item["id"] for item in detail.json()["questions"]] == [question_id]
