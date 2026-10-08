import os
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Department, Enrollment, Semester, Subject, TeacherSubject, User


def test_admin_only_user_and_academic_management():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="SEC", name="Security")
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

    admin = User(full_name="Sec Admin", email="sec-admin@example.com",
                 password_hash=pwd.hash("Admin@123"), role="ADMIN")
    teacher = User(full_name="Sec Teacher", email="sec-teacher@example.com",
                   password_hash=pwd.hash("Teacher@123"), role="TEACHER")
    student = User(full_name="Sec Student", email="sec-student@example.com",
                   password_hash=pwd.hash("Student@123"), role="STUDENT")
    db.add_all([admin, teacher, student])
    db.commit()
    db.close()

    def override():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        def login(email, password):
            response = client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )
            assert response.status_code == 200, response.text
            return {"Authorization": f"Bearer {response.json()['access_token']}"}

        admin_headers = login("sec-admin@example.com", "Admin@123")
        teacher_headers = login("sec-teacher@example.com", "Teacher@123")
        student_headers = login("sec-student@example.com", "Student@123")

        user_payload = {
            "full_name": "Created Teacher",
            "email": "created-teacher@example.com",
            "password": "Teacher@123",
            "role": "TEACHER",
        }

        assert client.post("/api/users", headers=teacher_headers, json=user_payload).status_code == 403
        assert client.post("/api/users", headers=student_headers, json=user_payload).status_code == 403

        created = client.post("/api/users", headers=admin_headers, json=user_payload)
        assert created.status_code == 200, created.text

        department_payload = {"code": "SEC2", "name": "Security Two"}
        assert client.post("/api/departments", headers=teacher_headers, json=department_payload).status_code == 403
        assert client.post("/api/departments", headers=student_headers, json=department_payload).status_code == 403

        semester_payload = {
            "department_id": department.id,
            "academic_year": "2026-27",
            "semester_number": 2,
            "regulation": "TEST",
        }
        assert client.post("/api/semesters", headers=teacher_headers, json=semester_payload).status_code == 403
        assert client.post("/api/semesters", headers=student_headers, json=semester_payload).status_code == 403

        section_payload = {"semester_id": semester.id, "name": "A"}
        assert client.post("/api/sections", headers=teacher_headers, json=section_payload).status_code == 403
        assert client.post("/api/sections", headers=student_headers, json=section_payload).status_code == 403

        subject_payload = {
            "semester_id": semester.id,
            "code": "SEC101",
            "name": "Security Subject",
            "weeks": 16,
            "hours_per_week": 4,
            "lecture_duration_minutes": 60,
        }
        assert client.post("/api/subjects", headers=teacher_headers, json=subject_payload).status_code == 403
        assert client.post("/api/subjects", headers=student_headers, json=subject_payload).status_code == 403

    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_teacher_and_student_cannot_assign_or_enroll():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="SECX", name="Security X")
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
    subject = Subject(semester_id=semester.id, code="SECX101", name="Secure Systems")
    teacher = User(full_name="Teacher X", email="teacher-x@example.com",
                   password_hash=pwd.hash("Teacher@123"), role="TEACHER")
    student = User(full_name="Student X", email="student-x@example.com",
                   password_hash=pwd.hash("Student@123"), role="STUDENT")
    db.add_all([subject, teacher, student])
    db.commit()
    subject_id, teacher_id, student_id = subject.id, teacher.id, student.id
    db.close()

    def override():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        def login(email, password):
            response = client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )
            assert response.status_code == 200, response.text
            return {"Authorization": f"Bearer {response.json()['access_token']}"}

        for headers in [
            login("teacher-x@example.com", "Teacher@123"),
            login("student-x@example.com", "Student@123"),
        ]:
            assert client.post(
                "/api/assignments",
                headers=headers,
                json={
                    "teacher_id": teacher_id,
                    "subject_id": subject_id,
                    "academic_year": "2026-27",
                },
            ).status_code == 403
            assert client.post(
                "/api/enrollments",
                headers=headers,
                json={
                    "student_id": student_id,
                    "subject_id": subject_id,
                    "academic_year": "2026-27",
                },
            ).status_code == 403

    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)
