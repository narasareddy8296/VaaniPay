"""Tests for health check endpoints and interactive OpenAPI documentation."""

from fastapi.testclient import TestClient


def test_root_health_endpoint(client: TestClient):
    """Verifies that GET /health returns status healthy with application metadata."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "VaaniPay"
    assert "version" in data
    assert "environment" in data


def test_api_v1_health_endpoint(client: TestClient):
    """Verifies that GET /api/v1/health returns consistent status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "VaaniPay"


def test_openapi_docs_endpoint(client: TestClient):
    """Verifies that FastAPI interactive documentation (/docs) is served."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower() or "html" in response.headers.get("content-type", "")


def test_root_index_endpoint(client: TestClient):
    """Verifies that GET / returns service information and navigation links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "VaaniPay"
    assert data["docs"] == "/docs"
    assert data["health"] == "/health"
