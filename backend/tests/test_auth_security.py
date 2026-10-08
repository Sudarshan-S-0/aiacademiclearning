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
