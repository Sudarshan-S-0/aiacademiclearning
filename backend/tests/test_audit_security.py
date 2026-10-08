import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import User, Department, Semester, Subject, TeacherSubject, Resource


@pytest.fixture()
def audit_client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    admin = User(
        full_name="Audit Admin",
        email="audit-admin@example.com",
        password_hash=pwd.hash("Admin@123"),
        role="ADMIN",
    )
    teacher = User(
        full_name="Audit Teacher",
        email="audit-teacher@example.com",
        password_hash=pwd.hash("Teacher@123"),
        role="TEACHER",
    )
    student = User(
        full_name="Audit Student",
        email="audit-student@example.com",
        password_hash=pwd.hash("Student@123"),
        role="STUDENT",
    )
    db.add_all([admin, teacher, student])
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


def login(client, email, password):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_audit_log_is_admin_only_and_records_login(audit_client):
    admin_headers = login(audit_client, "audit-admin@example.com", "Admin@123")
    teacher_headers = login(audit_client, "audit-teacher@example.com", "Teacher@123")
    student_headers = login(audit_client, "audit-student@example.com", "Student@123")

    admin_logs = audit_client.get("/api/audit", headers=admin_headers)
    assert admin_logs.status_code == 200, admin_logs.text
    logs = admin_logs.json()
    assert any(
        row["action"] == "LOGIN" and row["entity"] == "AUTH"
        for row in logs
    )

    teacher_logs = audit_client.get("/api/audit", headers=teacher_headers)
    assert teacher_logs.status_code == 403

    student_logs = audit_client.get("/api/audit", headers=student_headers)
    assert student_logs.status_code == 403

    export = audit_client.get("/api/admin/audit-export", headers=admin_headers)
    assert export.status_code == 200, export.text
    assert any(row["action"] == "LOGIN" for row in export.json())

    teacher_export = audit_client.get(
        "/api/admin/audit-export", headers=teacher_headers
    )
    assert teacher_export.status_code == 403


def test_resource_status_change_is_audited(audit_client):
    admin_headers = login(audit_client, "audit-admin@example.com", "Admin@123")

    session = next(app.dependency_overrides[get_db]())
    try:
        department = Department(code="AUD2", name="Audit Department 2")
        session.add(department)
        session.flush()
        semester = Semester(
            department_id=department.id,
            academic_year="2026-27",
            semester_number=8,
            regulation="TEST",
        )
        session.add(semester)
        session.flush()
        subject = Subject(
            semester_id=semester.id,
            code="AUD802",
            name="Audit Subject 2",
        )
        session.add(subject)
        session.flush()
        resource = Resource(
            subject_id=subject.id,
            uploaded_by=1,
            title="Audited Resource",
            resource_type="PDF",
            status="DRAFT",
            version=1,
            extracted_text="audit",
        )
        session.add(resource)
        session.commit()
        subject_id = subject.id
        resource_id = resource.id
    finally:
        session.close()

    updated = audit_client.patch(
        f"/api/resources/{resource_id}/status?status=APPROVED",
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text

    logs = audit_client.get("/api/audit", headers=admin_headers)
    assert logs.status_code == 200, logs.text
    assert any(
        row["action"] == "RESOURCE_APPROVED"
        and row["entity"] == "RESOURCE"
        and row["entity_id"] == resource_id
        for row in logs.json()
    )
