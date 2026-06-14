"""Tests for /v2/vectordb/entities/delete — mimics the Drupal deleteFromCollection() call."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import NODES, build_entity, drupal_id_to_vdb_id


def _seed(client: TestClient) -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": "nodes", "dimension": 64})
    entities = [build_entity(n) for n in NODES]
    client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": entities})


def test_delete_single_entity_by_id(client: TestClient) -> None:
    _seed(client)
    vdb_id = drupal_id_to_vdb_id("node:1001:en")
    r = client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "nodes", "filter": f"id in [{vdb_id}]"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["deleteCount"] == 1


def test_deleted_entity_is_not_returned_by_query(client: TestClient) -> None:
    _seed(client)
    vdb_id = drupal_id_to_vdb_id("node:1001:en")
    client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "nodes", "filter": f"id in [{vdb_id}]"},
    )
    r = client.post(
        "/v2/vectordb/entities/query",
        json={"collectionName": "nodes", "filter": {"drupal_entity_id": ["node:1001:en"]}},
    )
    assert r.json()["data"] == []


def test_deleted_entity_is_not_returned_by_search(client: TestClient) -> None:
    from tests.conftest import bag_of_words_vector
    _seed(client)
    vdb_id = drupal_id_to_vdb_id("node:1001:en")
    client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "nodes", "filter": f"id in [{vdb_id}]"},
    )
    query = bag_of_words_vector("pasta parmesan italy")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 5},
    )
    entity_ids = [h["entity"].get("drupal_entity_id") for h in r.json()["data"][0]]
    assert "node:1001:en" not in entity_ids


def test_delete_multiple_entities(client: TestClient) -> None:
    _seed(client)
    ids = [drupal_id_to_vdb_id(f"node:{nid}:en") for nid in [1001, 1002]]
    filter_str = f"id in [{','.join(str(i) for i in ids)}]"
    r = client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "nodes", "filter": filter_str},
    )
    assert r.json()["data"]["deleteCount"] == 2

    r2 = client.post("/v2/vectordb/entities/query", json={"collectionName": "nodes", "filter": {}, "limit": 100})
    assert len(r2.json()["data"]) == 3


def test_delete_nonexistent_entity_returns_zero(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "nodes", "filter": "id in [999999999]"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["deleteCount"] == 0


def test_delete_empty_id_list_returns_zero(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "nodes", "filter": "id in []"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["deleteCount"] == 0


def test_delete_invalid_filter_format_returns_422(client: TestClient) -> None:
    _seed(client)
    r = client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "nodes", "filter": "drupal_entity_id = 'node:1001:en'"},
    )
    assert r.status_code == 422


def test_delete_missing_collection_returns_404(client: TestClient) -> None:
    r = client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": "ghost", "filter": "id in [1]"},
    )
    assert r.status_code == 404


def test_delete_then_reinsert_works(client: TestClient) -> None:
    """A node deleted and re-indexed should be searchable again."""
    from tests.conftest import bag_of_words_vector
    _seed(client)
    vdb_id = drupal_id_to_vdb_id("node:1001:en")

    client.post("/v2/vectordb/entities/delete", json={"collectionName": "nodes", "filter": f"id in [{vdb_id}]"})

    # Re-insert
    entity = build_entity(NODES[0])
    client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": [entity]})

    query = bag_of_words_vector("pasta parmesan italy")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 1},
    )
    top = r.json()["data"][0][0]
    assert "Italy" in top["entity"]["title"]
