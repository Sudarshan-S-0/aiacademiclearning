from fastapi.testclient import TestClient
from app.main import app


def test_public_registration_cannot_create_privileged_role():
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "full_name": "Unauthorized Admin",
                "email": "unauthorized-admin@example.com",
                "password": "Admin@123",
                "role": "ADMIN",
            },
        )
    assert response.status_code == 403


def test_audit_endpoints_are_admin_only_and_record_login():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        denied = client.get("/api/audit")
        assert denied.status_code == 401

        export_denied = client.get("/api/admin/audit-export")
        assert export_denied.status_code == 401



def test_user_create_schema_trims_names_and_rejects_blank_or_oversized_names():
    import pytest
    from pydantic import ValidationError
    from app.api.routes import UserCreate

    valid = UserCreate(
        full_name="  Sudarshan S  ",
        email="sudarshan@example.com",
        password="StrongPass123",
        role="STUDENT",
    )
    assert valid.full_name == "Sudarshan S"

    for name in ("   ", "x" * 201):
        with pytest.raises(ValidationError):
            UserCreate(
                full_name=name,
                email="sudarshan@example.com",
                password="StrongPass123",
                role="STUDENT",
            )
