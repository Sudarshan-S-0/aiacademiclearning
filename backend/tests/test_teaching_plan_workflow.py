import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Department, Semester, Subject, Topic, User, TeacherSubject


@pytest.fixture()
def client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="PLAN", name="Plan Test")
    db.add(department)
    db.flush()
    semester = Semester(department_id=department.id, academic_year="2026-27",
                        semester_number=8, regulation="TEST")
    db.add(semester)
    db.flush()
    subject = Subject(semester_id=semester.id, code="PLAN801", name="Plan Subject",
                      weeks=2, hours_per_week=4, lecture_duration_minutes=60)
    teacher = User(full_name="Plan Teacher", email="plan-teacher@example.com",
                   password_hash=pwd.hash("Teacher@123"), role="TEACHER")
    db.add_all([subject, teacher])
    db.flush()
    db.add(TeacherSubject(teacher_id=teacher.id, subject_id=subject.id, academic_year="2026-27"))
    db.add_all([
        Topic(subject_id=subject.id, unit_number=1, topic_name="Arrays",
              sequence_order=1, estimated_hours=4, status="ACTIVE"),
        Topic(subject_id=subject.id, unit_number=2, topic_name="Linked Lists",
              sequence_order=2, estimated_hours=4, status="ACTIVE"),
        Topic(subject_id=subject.id, unit_number=3, topic_name="Trees",
              sequence_order=3, estimated_hours=4, status="ACTIVE"),
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


def login(client):
    response = client.post("/api/auth/login",
                           json={"email": "plan-teacher@example.com", "password": "Teacher@123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_teaching_plan_generates_with_weekly_capacity(client):
    test_client, subject_id = client
    headers = login(test_client)
    response = test_client.post("/api/teaching-plan/generate",
                                headers=headers, json={"subject_id": subject_id})
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 2
    assert [row["week"] for row in rows] == [1, 2]
    assert [row["planned_hours"] for row in rows] == [4, 4]


def test_completed_topic_is_preserved_when_plan_is_regenerated(client):
    test_client, subject_id = client
    headers = login(test_client)
    generated = test_client.post("/api/teaching-plan/generate",
                                 headers=headers, json={"subject_id": subject_id})
    assert generated.status_code == 200, generated.text
    first_topic = generated.json()[0]["topic_id"]

    completed = test_client.post(f"/api/teaching-plan/{subject_id}/update",
                                 headers=headers,
                                 json={"topic_id": first_topic, "action": "complete", "value": 2})
    assert completed.status_code == 200, completed.text

    regenerated = test_client.post("/api/teaching-plan/generate",
                                   headers=headers, json={"subject_id": subject_id})
    assert regenerated.status_code == 200, regenerated.text
    rows = regenerated.json()
    assert any(row["topic_id"] == first_topic and row["status"] == "COMPLETED" for row in rows)


def test_duration_change_updates_plan_item(client):
    test_client, subject_id = client
    headers = login(test_client)
    generated = test_client.post("/api/teaching-plan/generate",
                                 headers=headers, json={"subject_id": subject_id})
    assert generated.status_code == 200, generated.text
    target_topic = generated.json()[0]["topic_id"]

    response = test_client.post(f"/api/teaching-plan/{subject_id}/update",
                                headers=headers,
                                json={"topic_id": target_topic, "action": "duration", "value": 3})
    assert response.status_code == 200, response.text
    rows = response.json()
    target = [row for row in rows if row["topic_id"] == target_topic]
    assert target
    assert target[0]["planned_hours"] == 3
