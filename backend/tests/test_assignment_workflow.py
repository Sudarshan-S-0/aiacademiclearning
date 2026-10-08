import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import (
    Content,
    Department,
    Enrollment,
    Semester,
    Subject,
    TeacherSubject,
    Topic,
    User,
)


@pytest.fixture()
def client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="ASSIGN", name="Assignment Test")
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
        code="ASSIGN801",
        name="Assignment Subject",
        weeks=16,
        hours_per_week=4,
        lecture_duration_minutes=60,
    )
    db.add(subject)
    db.flush()

    topic = Topic(
        subject_id=subject.id,
        unit_number=1,
        topic_name="Arrays",
        sequence_order=1,
        estimated_hours=2,
        version=1,
        status="ACTIVE",
    )
    admin = User(
        full_name="Assignment Admin",
        email="assignment-admin@example.com",
        password_hash=pwd.hash("Admin@123"),
        role="ADMIN",
    )
    teacher = User(
        full_name="Assignment Teacher",
        email="assignment-teacher@example.com",
        password_hash=pwd.hash("Teacher@123"),
        role="TEACHER",
    )
    outsider_teacher = User(
        full_name="Outsider Teacher",
        email="outsider-teacher@example.com",
        password_hash=pwd.hash("Teacher@123"),
        role="TEACHER",
    )
    student = User(
        full_name="Assignment Student",
        email="assignment-student@example.com",
        password_hash=pwd.hash("Student@123"),
        role="STUDENT",
    )
    outsider_student = User(
        full_name="Outsider Student",
        email="outsider-student@example.com",
        password_hash=pwd.hash("Student@123"),
        role="STUDENT",
    )
    db.add_all([subject, topic, admin, teacher, outsider_teacher, student, outsider_student])
    db.flush()

    db.add(
        TeacherSubject(
            teacher_id=teacher.id,
            subject_id=subject.id,
            academic_year="2026-27",
        )
    )
    db.add(
        Enrollment(
            student_id=student.id,
            subject_id=subject.id,
            academic_year="2026-27",
        )
    )
    assignment = Content(
        subject_id=subject.id,
        topic_id=topic.id,
        title="Array Assignment",
        content_type="ASSIGNMENT",
        body="Explain how arrays support indexed access.",
        status="PUBLISHED",
        version=1,
        generated_by_ai=False,
        created_by=teacher.id,
    )
    db.add(assignment)
    db.commit()

    subject_id = subject.id
    assignment_id = assignment.id
    db.close()

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, subject_id, assignment_id
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


def test_assignment_submission_grading_and_object_isolation(client):
    test_client, subject_id, assignment_id = client
    student_headers = login(
        test_client, "assignment-student@example.com", "Student@123"
    )
    teacher_headers = login(
        test_client, "assignment-teacher@example.com", "Teacher@123"
    )
    outsider_teacher_headers = login(
        test_client, "outsider-teacher@example.com", "Teacher@123"
    )
    outsider_student_headers = login(
        test_client, "outsider-student@example.com", "Student@123"
    )

    empty = test_client.post(
        "/api/assignments/submit",
        headers=student_headers,
        json={"content_id": assignment_id, "answer_text": "   "},
    )
    assert empty.status_code == 400

    submitted = test_client.post(
        "/api/assignments/submit",
        headers=student_headers,
        json={
            "content_id": assignment_id,
            "answer_text": "Arrays store elements in indexed positions.",
        },
    )
    assert submitted.status_code == 200, submitted.text
    submission_id = submitted.json()["submission_id"]

    duplicate = test_client.post(
        "/api/assignments/submit",
        headers=student_headers,
        json={
            "content_id": assignment_id,
            "answer_text": "This duplicate submission must be rejected.",
        },
    )
    assert duplicate.status_code == 409

    outsider_submit = test_client.post(
        "/api/assignments/submit",
        headers=outsider_student_headers,
        json={
            "content_id": assignment_id,
            "answer_text": "I am not enrolled in this subject.",
        },
    )
    assert outsider_submit.status_code == 404

    outsider_list = test_client.get(
        f"/api/assignments/submissions/{assignment_id}",
        headers=outsider_teacher_headers,
    )
    assert outsider_list.status_code == 404

    submissions = test_client.get(
        f"/api/assignments/submissions/{assignment_id}",
        headers=teacher_headers,
    )
    assert submissions.status_code == 200, submissions.text
    rows = submissions.json()
    assert len(rows) == 1
    assert rows[0]["student_id"] is not None
    assert rows[0]["answer"] == "Arrays store elements in indexed positions."

    invalid_score = test_client.patch(
        f"/api/assignments/submissions/{submission_id}/grade",
        headers=teacher_headers,
        json={"score": 101, "feedback": "Invalid"},
    )
    assert invalid_score.status_code == 400

    outsider_grade = test_client.patch(
        f"/api/assignments/submissions/{submission_id}/grade",
        headers=outsider_teacher_headers,
        json={"score": 80, "feedback": "Should be blocked"},
    )
    assert outsider_grade.status_code == 404

    graded = test_client.patch(
        f"/api/assignments/submissions/{submission_id}/grade",
        headers=teacher_headers,
        json={"score": 85, "feedback": "Good explanation."},
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["score"] == 85
    assert graded.json()["feedback"] == "Good explanation."

    progress = test_client.get(
        "/api/student/progress",
        headers=student_headers,
    )
    assert progress.status_code == 200, progress.text
    assignment_rows = [
        row for row in progress.json() if row["activity"] == "ASSIGNMENT"
    ]
    assert len(assignment_rows) == 1
    assert assignment_rows[0]["score"] == 85
    assert assignment_rows[0]["max_score"] == 100

    analytics = test_client.get(
        "/api/analytics/student-v2",
        headers=student_headers,
    )
    assert analytics.status_code == 200, analytics.text
    subject = next(
        item for item in analytics.json()["subjects"]
        if item["subject"] == "Assignment Subject"
    )
    assert subject["activities"] == 1
    assert subject["completed"] == 1
    assert subject["percentage"] == 85

    teacher_analytics = test_client.get(
        f"/api/analytics/teacher-v2/{subject_id}",
        headers=teacher_headers,
    )
    assert teacher_analytics.status_code == 200, teacher_analytics.text
    assert teacher_analytics.json()["students"] == 1

    outsider_teacher_analytics = test_client.get(
        f"/api/analytics/teacher-v2/{subject_id}",
        headers=outsider_teacher_headers,
    )
    assert outsider_teacher_analytics.status_code == 403

    student_teacher_analytics = test_client.get(
        f"/api/analytics/teacher-v2/{subject_id}",
        headers=student_headers,
    )
    assert student_teacher_analytics.status_code == 403

    admin_headers = login(
        test_client, "assignment-admin@example.com", "Admin@123"
    )
    admin_analytics = test_client.get(
        "/api/analytics/admin",
        headers=admin_headers,
    )
    assert admin_analytics.status_code == 200, admin_analytics.text
    assert admin_analytics.json()["academic"]["subjects"] == 1

    student_admin_analytics = test_client.get(
        "/api/analytics/admin",
        headers=student_headers,
    )
    assert student_admin_analytics.status_code == 403
