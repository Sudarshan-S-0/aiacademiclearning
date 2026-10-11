import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import pwd
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Department, Semester, Subject, Topic, User


@pytest.fixture()
def client():
    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    department = Department(code="PYQ", name="PYQ Test")
    db.add(department)
    db.flush()
    semester = Semester(department_id=department.id, academic_year="2026-27",
                        semester_number=8, regulation="TEST")
    db.add(semester)
    db.flush()
    subject = Subject(semester_id=semester.id, code="PYQ801", name="PYQ Subject",
                      weeks=16, hours_per_week=4, lecture_duration_minutes=60)
    admin = User(full_name="PYQ Admin", email="pyq-admin@example.com",
                 password_hash=pwd.hash("Admin@123"), role="ADMIN")
    db.add_all([subject, admin])
    db.flush()
    subject_id = subject.id
    db.add_all([
        Topic(subject_id=subject_id, unit_number=1, topic_name="Arrays and Searching",
              sequence_order=1, estimated_hours=2, status="ACTIVE"),
        Topic(subject_id=subject_id, unit_number=2, topic_name="Linked Lists",
              sequence_order=2, estimated_hours=2, status="ACTIVE"),
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
        yield test_client, subject_id
    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def login(client):
    response = client.post("/api/auth/login",
                           json={"email": "pyq-admin@example.com", "password": "Admin@123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_bulk_pyq_import_maps_questions_and_recalculates_weightage(client):
    test_client, subject_id = client
    headers = login(test_client)

    response = test_client.post(
        "/api/pyq/questions/bulk",
        headers=headers,
        json={
            "subject_id": subject_id,
            "questions": [
                {"year": 2024, "question_no": "1", "question_text": "Explain arrays and searching", "marks": 10},
                {"year": 2025, "question_no": "2", "question_text": "Explain linked lists", "marks": 5},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 2
    assert response.json()["reanalyzed"] == 2

    analytics = test_client.get(f"/api/pyq/analytics-v2/{subject_id}", headers=headers)
    assert analytics.status_code == 200, analytics.text
    data = analytics.json()
    assert data["questions"] == 2
    assert len(data["unit_weightage"]) == 2
    assert all(row["topic"] for row in data["mapping"])


def test_pyq_analytics_exposes_evidence_based_weightage_and_trends(client):
    test_client, subject_id = client
    headers = login(test_client)
    first = test_client.post("/api/pyq/questions", headers=headers, json={
        "subject_id": subject_id,
        "year": 2024,
        "question_no": "1",
        "question_text": "Explain arrays and searching",
        "marks": 10,
    })
    assert first.status_code == 200, first.text
    second = test_client.post("/api/pyq/questions", headers=headers, json={
        "subject_id": subject_id,
        "year": 2025,
        "question_no": "1",
        "question_text": "Explain arrays and searching",
        "marks": 10,
    })
    assert second.status_code == 200, second.text

    response = test_client.get(f"/api/pyq/analytics-v2/{subject_id}", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_marks"] == 20
    assert data["unit_weightage"]
    assert data["unit_weightage"][0]["percentage"] == 100
    assert data["year_trend"] == [
        {"year": 2024, "marks": 10, "questions": 1},
        {"year": 2025, "marks": 10, "questions": 1},
    ]
    assert data["repeated"][0]["count"] == 2
    assert data["repeated"][0]["years"] == [2024, 2025]
    assert any("high priority" in item for item in data["recommendations"])


def test_pyq_rejects_topic_from_another_subject(client):
    test_client, subject_id = client
    headers = login(test_client)
    session = next(app.dependency_overrides[get_db]())
    try:
        current_subject = session.get(Subject, subject_id)
        other_subject = Subject(
            semester_id=current_subject.semester_id,
            code="PYQOTHER",
            name="Other PYQ Subject",
            weeks=16,
            hours_per_week=4,
            lecture_duration_minutes=60,
        )
        session.add(other_subject)
        session.flush()
        foreign_topic = Topic(
            subject_id=other_subject.id,
            unit_number=1,
            topic_name="Foreign Topic",
            sequence_order=1,
            estimated_hours=1,
            status="ACTIVE",
        )
        session.add(foreign_topic)
        session.commit()
        foreign_topic_id = foreign_topic.id
    finally:
        session.close()

    response = test_client.post(
        "/api/pyq/questions",
        headers=headers,
        json={
            "subject_id": subject_id,
            "question_text": "A question with no matching foreign topic.",
            "topic_id": foreign_topic_id,
        },
    )
    assert response.status_code == 400


def test_reanalysis_preserves_explicit_topic_selection(client):
    test_client, subject_id = client
    headers = login(test_client)

    # Deliberately select Linked Lists for a question whose wording strongly
    # matches Arrays and Searching; explicit teacher mapping must win.
    session = next(app.dependency_overrides[get_db]())
    try:
        topics = session.query(Topic).filter(Topic.subject_id == subject_id).all()
        linked_lists = next(topic for topic in topics if topic.topic_name == "Linked Lists")
        selected_topic_id = linked_lists.id
    finally:
        session.close()

    created = test_client.post("/api/pyq/questions", headers=headers, json={
        "subject_id": subject_id,
        "question_text": "Explain arrays and searching techniques",
        "topic_id": selected_topic_id,
        "marks": 5,
    })
    assert created.status_code == 200, created.text
    question_id = created.json()["id"]

    reanalyzed = test_client.post(
        f"/api/pyq/reanalyze-v2/{subject_id}", headers=headers
    )
    assert reanalyzed.status_code == 200, reanalyzed.text

    session = next(app.dependency_overrides[get_db]())
    try:
        from app.models.models import PYQQuestion
        question = session.get(PYQQuestion, question_id)
        assert question is not None
        assert question.topic_id == selected_topic_id
        assert question.unit_number == 2
        assert question.mapping_confidence == 1.0
        arrays_topic_id = next(
            topic.id for topic in session.query(Topic).filter(Topic.subject_id == subject_id).all()
            if topic.topic_name == "Arrays and Searching"
        )
    finally:
        session.close()

    archived = test_client.patch(
        f"/api/topics/{selected_topic_id}",
        headers=headers,
        json={"status": "ARCHIVED"},
    )
    assert archived.status_code == 200, archived.text

    legacy_reanalysis = test_client.post(
        f"/api/pyq/reanalyze/{subject_id}",
        headers=headers,
    )
    assert legacy_reanalysis.status_code == 200, legacy_reanalysis.text

    session = next(app.dependency_overrides[get_db]())
    try:
        question = session.get(PYQQuestion, question_id)
        assert question.topic_id == arrays_topic_id
        assert question.unit_number == 1
        assert question.mapping_confidence != 1.0
    finally:
        session.close()
