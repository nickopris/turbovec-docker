"""Tests for /v2/vectordb/entities/insert."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import NODES, build_entity, drupal_id_to_vdb_id


def _create_col(client: TestClient, name: str = "nodes", dim: int = 64) -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": name, "dimension": dim})


def test_insert_single_entity(client: TestClient) -> None:
    _create_col(client)
    entity = build_entity(NODES[0])
    r = client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": [entity]})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["insertCount"] == 1
    assert body["data"]["numEntities"] == 1


def test_insert_all_five_drupal_nodes(client: TestClient) -> None:
    _create_col(client)
    entities = [build_entity(n) for n in NODES]
    r = client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": entities})
    assert r.status_code == 200
    assert r.json()["data"]["insertCount"] == 5


def test_insert_missing_id_returns_422(client: TestClient) -> None:
    _create_col(client)
    entity = build_entity(NODES[0])
    del entity["id"]
    r = client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": [entity]})
    assert r.status_code == 422
    assert "id" in r.json()["detail"]


def test_insert_missing_vector_returns_422(client: TestClient) -> None:
    _create_col(client)
    entity = build_entity(NODES[0])
    del entity["vector"]
    r = client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": [entity]})
    assert r.status_code == 422
    assert "vector" in r.json()["detail"]


def test_insert_duplicate_ids_in_same_request_returns_422(client: TestClient) -> None:
    _create_col(client)
    entity = build_entity(NODES[0])
    r = client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": [entity, entity]})
    assert r.status_code == 422


def test_insert_into_missing_collection_returns_404(client: TestClient) -> None:
    entity = build_entity(NODES[0])
    r = client.post("/v2/vectordb/entities/insert", json={"collectionName": "ghost", "data": [entity]})
    assert r.status_code == 404


def test_insert_updates_entity_count_in_describe(client: TestClient) -> None:
    _create_col(client)
    for node in NODES:
        client.post("/v2/vectordb/entities/insert", json={"collectionName": "nodes", "data": [build_entity(node)]})
    r = client.post("/v2/vectordb/collections/describe", json={"collectionName": "nodes"})
    assert r.json()["data"]["numEntities"] == 5


def test_drupal_id_derivation_is_stable(client: TestClient) -> None:
    """The VDB integer ID for a given drupal_long_id never changes."""
    node = NODES[0]
    vdb_id = drupal_id_to_vdb_id(node["drupal_long_id"])
    assert isinstance(vdb_id, int)
    assert 0 < vdb_id <= 0x7FFFFFFFFFFFFFFF
    assert drupal_id_to_vdb_id(node["drupal_long_id"]) == vdb_id
