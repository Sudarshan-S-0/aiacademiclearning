import json
import math

import pytest
from pydantic import ValidationError

from app.main import _json_safe_validation_value
from app.api.routes import (
    AIContentRequest,
    Answer,
    AskRequest,
    AssignmentCreate,
    AttemptCreate,
    ContentCreate,
    EnrollmentCreate,
    PlanAction,
    PYQCreate,
    SubjectCreate,
    TopicCreate,
    TopicUpdate,
    UserCreate,
)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (AssignmentCreate, {"teacher_id": 0, "subject_id": 1, "academic_year": "2026-27"}),
        (UserCreate, {"full_name": "Test User", "email": "test@example.com", "password": "Password123", "role": "R" * 21}),
        (AssignmentCreate, {"teacher_id": 1, "subject_id": 1, "academic_year": "x" * 21}),
        (EnrollmentCreate, {"student_id": 1, "subject_id": 0, "academic_year": "2026-27"}),
        (SubjectCreate, {"semester_id": 1, "code": "CS", "name": "Computer Science", "description": "x" * 5001}),
        (TopicCreate, {"subject_id": 1, "unit_number": 1, "topic_name": "T" * 201, "sequence_order": 1}),
        (TopicUpdate, {"sequence_order": 10001}),
        (TopicUpdate, {"estimated_hours": 1001}),
        (ContentCreate, {"subject_id": 0, "title": "Notes", "content_type": "NOTES", "body": "body"}),
        (PYQCreate, {"subject_id": 1, "question_text": "Q" * 20001}),
        (PYQCreate, {"subject_id": 1, "question_text": "Question", "marks": float("inf")}),
        (PlanAction, {"action": "UPDATE", "topic_id": 1, "value": float("nan")}),
        (Answer, {"question_id": 1, "answer": "A" * 5001}),
        (AttemptCreate, {"quiz_id": 1, "answers": []}),
        (AttemptCreate, {"quiz_id": 1, "answers": [{"question_id": 1, "answer": "A"}] * 201}),
        (AIContentRequest, {"subject_id": 1, "content_type": "NOTES", "instructions": "x" * 10001}),
        (AskRequest, {"subject_id": 1, "question": " " * 10001}),
    ],
)
def test_core_academic_request_models_reject_invalid_or_oversized_inputs(model, payload):
    with pytest.raises(ValidationError):
        model(**payload)


def test_core_academic_request_models_accept_valid_minimal_inputs():
    assert AssignmentCreate(teacher_id=1, subject_id=1, academic_year="2026-27")
    assert EnrollmentCreate(student_id=1, subject_id=1, academic_year="2026-27")
    assert ContentCreate(subject_id=1, title="Notes", content_type="NOTES", body="Content")
    assert PYQCreate(subject_id=1, question_text="Explain arrays").marks == 1
    assert AttemptCreate(quiz_id=1, answers=[{"question_id": 1, "answer": "A"}])
    assert AIContentRequest(subject_id=1, content_type="NOTES")
    assert AskRequest(subject_id=1, question="Explain arrays")



def test_validation_error_payloads_are_json_safe_for_non_finite_values():
    sanitized = _json_safe_validation_value(
        {"detail": [{"input": float("nan")}, {"input": float("inf")}, {"input": float("-inf")}]}
    )
    encoded = json.dumps(sanitized, allow_nan=False)
    assert "nan" in encoded
    assert "inf" in encoded
