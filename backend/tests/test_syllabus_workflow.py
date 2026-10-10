import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Department, Semester, Subject, User, Resource


@pytest.fixture()
def client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="SYL", name="Syllabus Test")
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
        code="SYL801",
        name="Syllabus Sync",
        weeks=16,
        hours_per_week=4,
        lecture_duration_minutes=60,
    )
    admin = User(
        full_name="Syllabus Admin",
        email="syllabus-admin@example.com",
        password_hash=pwd.hash("Admin@123"),
        role="ADMIN",
    )
    db.add_all([subject, admin])
    db.flush()
    subject_id = subject.id
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
        yield test_client, subject_id

    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def login(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "syllabus-admin@example.com", "password": "Admin@123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_syllabus_compare_creates_and_versions_topics(client):
    test_client, subject_id = client
    headers = login(test_client)

    first = test_client.post(
        "/api/syllabus/compare-v2",
        headers=headers,
        json={
            "subject_id": subject_id,
            "topic_names": ["Unit 1 - Introduction", "Unit 2 - Architecture"],
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1

    topics = test_client.get(
        f"/api/subjects/{subject_id}/topics",
        headers=headers,
    )
    assert topics.status_code == 200, topics.text
    assert [row["name"] for row in topics.json()] == [
        "Unit 1 - Introduction",
        "Unit 2 - Architecture",
    ]

    second = test_client.post(
        "/api/syllabus/compare-v2",
        headers=headers,
        json={
            "subject_id": subject_id,
            "topic_names": ["Unit 1 - Introduction", "Unit 3 - Deployment"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2
    assert "Unit 3 - Deployment" in second.json()["added"]
    assert "Unit 2 - Architecture" in second.json()["removed"]

    topics = test_client.get(
        f"/api/subjects/{subject_id}/topics",
        headers=headers,
    )
    assert topics.status_code == 200, topics.text
    assert [row["name"] for row in topics.json()] == [
        "Unit 1 - Introduction",
        "Unit 3 - Deployment",
    ]


def test_syllabus_compare_rejects_foreign_resource_and_invalid_version(client):
    test_client, subject_id = client
    headers = login(test_client)
    session = next(app.dependency_overrides[get_db]())
    try:
        subject = session.get(Subject, subject_id)
        admin = session.query(User).filter_by(email="syllabus-admin@example.com").one()
        other_subject = Subject(
            semester_id=subject.semester_id,
            code="SYLOTHER",
            name="Other Syllabus Subject",
            weeks=16,
            hours_per_week=4,
            lecture_duration_minutes=60,
        )
        session.add(other_subject)
        session.flush()
        resource = Resource(
            subject_id=other_subject.id,
            uploaded_by=admin.id,
            title="Foreign Syllabus",
            resource_type="SYLLABUS",
            status="DRAFT",
        )
        session.add(resource)
        session.commit()
        foreign_resource_id = resource.id
    finally:
        session.close()

    foreign_source = test_client.post(
        "/api/syllabus/compare-v2",
        headers=headers,
        json={
            "subject_id": subject_id,
            "topic_names": ["Unit 1 - Intro"],
            "source_resource_id": foreign_resource_id,
        },
    )
    assert foreign_source.status_code == 400

    invalid_version = test_client.post(
        "/api/syllabus/compare-v2",
        headers=headers,
        json={
            "subject_id": subject_id,
            "topic_names": ["Unit 1 - Intro"],
            "version": 3,
        },
    )
    assert invalid_version.status_code == 409
