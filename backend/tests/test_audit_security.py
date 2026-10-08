import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import User


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
