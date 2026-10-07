from app.main import app


def test_extended_workflow_routes_are_registered():
    # FastAPI 0.137+ may keep included routers as lazy _IncludedRouter
    # objects in app.routes. OpenAPI resolves that route tree to the
    # effective application paths, so it is the correct public contract
    # to test instead of assuming every app.routes item has .path.
    paths = set(app.openapi().get("paths", {}))
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
    missing = required - paths
    assert not missing, f"Missing registered API routes: {sorted(missing)}"


def test_role_and_grounding_helpers_are_importable():
    from app.api.extended_routes import normalize_key, approved_contexts, rebuild_plan, pyq_reanalyze
    assert normalize_key("Data Structures & Algorithms") == "data structures algorithms"
    assert callable(approved_contexts)
    assert callable(rebuild_plan)
    assert callable(pyq_reanalyze)
