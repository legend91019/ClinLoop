"""Health and OpenAPI surface tests (Task 4)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_openapi_document_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    # Every frozen foundation route must be described.
    for path in (
        "/healthz",
        "/api/v1/events",
        "/api/v1/patients/{patient_id}/timeline",
        "/api/v1/patients/{patient_id}/loops",
        "/api/v1/loops/{loop_id}",
        "/api/v1/findings/{finding_id}",
    ):
        assert path in schema["paths"], f"missing from OpenAPI: {path}"


def test_openapi_records_the_event_request_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    post_event = schema["paths"]["/api/v1/events"]["post"]
    assert "202" in post_event["responses"], "duplicate-safe ingest must document 202"
    assert "409" in post_event["responses"], "duplicate event must document 409"


def test_business_routes_are_versioned(client: TestClient) -> None:
    """Every business route lives under /api/v1.

    Infrastructure probes (``/healthz``, ``/readyz``) are deliberately
    unversioned — they are consumed by orchestrators, not by the console.
    """
    infrastructure = {"/healthz", "/readyz"}
    schema = client.get("/openapi.json").json()
    for path in schema["paths"]:
        if path in infrastructure:
            continue
        assert path.startswith("/api/v1/"), f"unversioned business route: {path}"
