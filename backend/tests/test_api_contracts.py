from app.main import app


def test_extended_workflow_routes_are_registered():
    paths = {route.path for route in app.routes}
    required = {
        "/api/departments",
        "/api/semesters",
        "/api/sections",
        "/api/analytics/admin",
        "/api/quizzes/{quiz_id}/generate",
        "/api/assignments/submissions/{content_id}",
        "/api/assignments/submissions/{submission_id}/grade",
        "/api/ai/ask-v2",
    }
    assert required.issubset(paths)


def test_role_and_grounding_helpers_are_importable():
    from app.api.extended_routes import normalize_key, approved_contexts, rebuild_plan, pyq_reanalyze
    assert normalize_key("Data Structures & Algorithms") == "data structures algorithms"
    assert callable(approved_contexts)
    assert callable(rebuild_plan)
    assert callable(pyq_reanalyze)
