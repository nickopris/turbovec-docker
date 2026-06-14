"""Tests for bearer token authentication."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint_works_without_auth(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200


def test_protected_endpoint_requires_auth_when_token_configured(authed_client: TestClient) -> None:
    r = authed_client.post("/v2/vectordb/collections/list", json={})
    assert r.status_code == 401


def test_protected_endpoint_accepts_valid_token(authed_client: TestClient) -> None:
    r = authed_client.post(
        "/v2/vectordb/collections/list",
        json={},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert r.status_code == 200


def test_wrong_token_is_rejected(authed_client: TestClient) -> None:
    r = authed_client.post(
        "/v2/vectordb/collections/list",
        json={},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401


def test_no_auth_required_when_token_not_set(client: TestClient) -> None:
    r = client.post("/v2/vectordb/collections/list", json={})
    assert r.status_code == 200
