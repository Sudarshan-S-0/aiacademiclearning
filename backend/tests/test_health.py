import os
os.environ["DATABASE_URL"]="sqlite:///./test.db"
from fastapi.testclient import TestClient
from app.main import app
def test_health():
    r=TestClient(app).get("/api/health");assert r.status_code==200;assert r.json()["status"]=="ok"
