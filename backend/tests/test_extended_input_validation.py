import pytest
from pydantic import ValidationError

from app.api.extended_routes import (
    AssignmentSubmit,
    ContentStatusUpdate,
    GenerateRequest,
    GradeSubmission,
    PYQBulkRequest,
    PYQQuestionInput,
    PlanEdit,
    SyllabusCompareRequest,
)


def test_extended_workflow_models_bound_large_or_invalid_payloads():
    valid_question = {"question_text": "Explain normalization", "marks": 5}
    assert PYQQuestionInput(**valid_question).marks == 5

    invalid_models = [
        (PYQQuestionInput, {"question_text": "Q" * 20001}),
        (PYQBulkRequest, {"subject_id": 1, "questions": [valid_question] * 501}),
        (PYQBulkRequest, {"subject_id": 1, "questions": []}),
        (AssignmentSubmit, {"content_id": 1, "answer_text": "A" * 100001}),
        (AssignmentSubmit, {"content_id": 0, "answer_text": "answer"}),
        (GenerateRequest, {"subject_id": 1, "content_type": "NOTES", "instructions": "x" * 10001}),
        (GradeSubmission, {"score": float("inf")}),
        (GradeSubmission, {"score": -1}),
        (GradeSubmission, {"score": 1, "feedback": "x" * 5001}),
        (ContentStatusUpdate, {"status": "S" * 21}),
        (SyllabusCompareRequest, {"subject_id": 1, "topic_names": ["topic"] * 501}),
        (PlanEdit, {"action": "UPDATE", "topic_id": 1, "value": float("nan")}),
    ]
    for model, payload in invalid_models:
        with pytest.raises(ValidationError):
            model(**payload)
