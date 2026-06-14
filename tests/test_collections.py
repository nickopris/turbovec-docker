"""Tests for /v2/vectordb/collections/* endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_collection(client: TestClient) -> None:
    r = client.post("/v2/vectordb/collections/create", json={"collectionName": "nodes", "dimension": 64})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "nodes"


def test_create_collection_duplicate_returns_409(client: TestClient) -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": "nodes", "dimension": 64})
    r = client.post("/v2/vectordb/collections/create", json={"collectionName": "nodes", "dimension": 64})
    assert r.status_code == 409


def test_create_collection_invalid_name(client: TestClient) -> None:
    r = client.post("/v2/vectordb/collections/create", json={"collectionName": "bad name!", "dimension": 64})
    assert r.status_code == 422


def test_create_collection_dimension_not_multiple_of_8(client: TestClient) -> None:
    r = client.post("/v2/vectordb/collections/create", json={"collectionName": "col", "dimension": 63})
    assert r.status_code == 422


def test_list_collections_empty(client: TestClient) -> None:
    r = client.post("/v2/vectordb/collections/list", json={})
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_list_collections_after_create(client: TestClient) -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": "alpha", "dimension": 8})
    client.post("/v2/vectordb/collections/create", json={"collectionName": "beta", "dimension": 8})
    r = client.post("/v2/vectordb/collections/list", json={})
    names = [item["name"] for item in r.json()["data"]]
    assert "alpha" in names
    assert "beta" in names


def test_describe_collection(client: TestClient) -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": "nodes", "dimension": 64})
    r = client.post("/v2/vectordb/collections/describe", json={"collectionName": "nodes"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["collectionName"] == "nodes"
    assert data["dimension"] == 64
    assert data["numEntities"] == 0


def test_describe_missing_collection_returns_404(client: TestClient) -> None:
    r = client.post("/v2/vectordb/collections/describe", json={"collectionName": "missing"})
    assert r.status_code == 404


def test_drop_collection(client: TestClient) -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": "temp", "dimension": 8})
    r = client.post("/v2/vectordb/collections/drop", json={"collectionName": "temp"})
    assert r.status_code == 200
    r2 = client.post("/v2/vectordb/collections/describe", json={"collectionName": "temp"})
    assert r2.status_code == 404


def test_drop_missing_collection_returns_404(client: TestClient) -> None:
    r = client.post("/v2/vectordb/collections/drop", json={"collectionName": "ghost"})
    assert r.status_code == 404
