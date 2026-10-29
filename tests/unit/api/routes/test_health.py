from fastapi import FastAPI
from fastapi.testclient import TestClient

from evaluation.api.routes.health import router


def create_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)

    return TestClient(app)


def test_health():
    client = create_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}