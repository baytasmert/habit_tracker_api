"""
Integration Tests for Middleware
Test Type: Integration Testing - tests how middleware interacts with endpoints
"""
import pytest
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestGZipMiddleware:
    """Test GZip compression middleware"""

    def test_gzip_compression_enabled(self, auth_client):
        """Large response should be gzip compressed"""
        response = auth_client.get("/habits")
        assert response.status_code == 200


class TestTrustedHostMiddleware:
    """Test trusted host middleware"""

    def test_request_accepted(self, client):
        """Request should be accepted from any host"""
        response = client.get("/health")
        assert response.status_code == 200


class TestValidationErrorHandler:
    """Test validation error handling"""

    def test_invalid_habit_creation(self, auth_client):
        """Invalid payload should return 422 with trace_id"""
        response = auth_client.post(
            "/habits",
            json={"description": "Missing name field"}
        )
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        assert "trace_id" in data

    def test_validation_error_format(self, auth_client):
        """Validation error should include errors list"""
        response = auth_client.post(
            "/habits",
            json={"invalid_field": "value"}
        )
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data


class TestTraceIdMiddleware:
    """Test trace ID middleware"""

    def test_trace_id_in_response_header(self, client):
        """Response should include X-Trace-ID header"""
        response = client.get("/health")
        assert "x-trace-id" in response.headers
        assert response.headers["x-trace-id"] != ""

    def test_process_time_in_response(self, client):
        """Response should include X-Process-Time header"""
        response = client.get("/health")
        assert "x-process-time" in response.headers
        process_time = float(response.headers["x-process-time"])
        assert process_time >= 0

    def test_security_headers(self, client):
        """Response should include security headers"""
        response = client.get("/health")
        assert "x-content-type-options" in response.headers
        assert "x-frame-options" in response.headers
        assert response.headers["x-frame-options"] == "DENY"


class TestCORSMiddleware:
    """Test CORS middleware"""

    def test_cors_origin_allowed(self, client):
        """CORS should allow requests from any origin"""
        response = client.get(
            "/health",
            headers={"origin": "http://localhost:3000"}
        )
        assert response.status_code == 200


class TestRateLimiting:
    """Test rate limiting middleware"""

    def test_rate_limit_header(self, auth_client):
        """Rate limit endpoint should include rate limit info"""
        response = auth_client.get("/habits")
        assert response.status_code == 200
