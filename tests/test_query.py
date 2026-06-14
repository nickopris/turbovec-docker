"""Tests for /v2/vectordb/entities/query — metadata filtering without a vector."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import NODES, build_entity


def _seed(client: TestClient) -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": "nodes", "dimension": 64})
    entities = [build_entity(n) for n in NODES]
    client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": entities})


def test_query_by_drupal_entity_id(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/query",
        json={
            "collectionName": "nodes",
            "filter": {"drupal_entity_id": ["node:1001:en"]},
            "outputFields": ["title", "drupal_entity_id"],
        },
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Regional food in Italy"
    assert data[0]["drupal_entity_id"] == "node:1001:en"


def test_query_by_multiple_entity_ids(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/query",
        json={
            "collectionName": "nodes",
            "filter": {"drupal_entity_id": ["node:1001:en", "node:1002:en"]},
            "outputFields": ["title"],
        },
    )
    titles = {row["title"] for row in r.json()["data"]}
    assert titles == {"Regional food in Italy", "European car makers"}


def test_query_empty_filter_returns_all(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "nodes", "filter": {}, "limit": 100},
    )
    assert len(r.json()["data"]) == 5


def test_query_no_match_returns_empty_list(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "nodes", "filter": {"drupal_entity_id": ["node:9999:en"]}},
    )
    assert r.json()["data"] == []


def test_query_by_type_field(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "nodes", "filter": {"type": ["article"]}, "limit": 100},
    )
    assert len(r.json()["data"]) == 5


def test_query_output_fields_restricts_response(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/query",
        json={
            "collectionName": "nodes",
            "filter": {"drupal_entity_id": ["node:1001:en"]},
            "outputFields": ["title"],
        },
    )
    row = r.json()["data"][0]
    assert "title" in row
    assert "body" not in row
    assert "drupal_entity_id" not in row


def test_query_pagination_limit_and_offset(client: TestClient) -> None:
    _seed(client)
    r_all = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "nodes", "filter": {}, "limit": 100},
    )
    all_ids = [row["id"] for row in r_all.json()["data"]]

    r_page = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "nodes", "filter": {}, "limit": 2, "offset": 2},
    )
    page_ids = [row["id"] for row in r_page.json()["data"]]
    assert page_ids == all_ids[2:4]


def test_query_missing_collection_returns_404(client: TestClient) -> None:
    r = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "ghost", "filter": {}},
    )
    assert r.status_code == 404


def test_query_result_always_includes_id_field(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "nodes", "filter": {"drupal_entity_id": ["node:1003:en"]}},
    )
    row = r.json()["data"][0]
    assert "id" in row
    assert isinstance(row["id"], int)
