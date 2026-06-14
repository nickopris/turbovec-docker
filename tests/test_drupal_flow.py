"""End-to-end flow tests mirroring real Drupal Search API AI usage.

These tests simulate:
1. Index created by the Drupal AI module when a search index is configured
2. Nodes indexed via insertIntoCollection() (called during node save/index)
3. vectorSearch() called by search_api_ai_search backend
4. deleteFromCollection() called when a node is deleted
5. getVdbIds() called to resolve Drupal entity IDs to turbovec IDs

The PHP TurbovecProvider derives the integer `id` from a SHA-256 hash of
`drupal_long_id`, so we mirror that here via drupal_id_to_vdb_id().
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import NODES, bag_of_words_vector, build_entity, drupal_id_to_vdb_id


COLLECTION = "drupal-nodes"


def _full_setup(client: TestClient) -> None:
    """Create collection and insert all 5 nodes as Drupal would."""
    client.post(
        "/v2/vectordb/collections/create",
        json={"collectionName": COLLECTION, "dimension": 64},
    )
    entities = [build_entity(n) for n in NODES]
    client.post(
        "/v2/vectordb/entities/insert",
        json={"collectionName": COLLECTION, "data": entities},
    )


def test_full_drupal_index_and_search_flow(client: TestClient) -> None:
    """Create → Insert 5 nodes → Search → verify top hit matches query topic."""
    _full_setup(client)

    query = bag_of_words_vector("pasta parmesan italy rome")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={
            "collectionName": COLLECTION,
            "data": [query],
            "limit": 5,
            "outputFields": ["drupal_entity_id", "drupal_long_id", "title"],
        },
    )
    assert r.status_code == 200
    hits = r.json()["data"][0]
    assert hits, "Expected at least one search result"

    # Top hit must be the Italy food node
    top = hits[0]["entity"]
    assert top["drupal_entity_id"] == "node:1001:en"
    assert "Italy" in top["title"]


def test_drupal_search_result_shape_for_base_class(client: TestClient) -> None:
    """The base class reads drupal_entity_id from hit['entity']; confirm the key exists."""
    _full_setup(client)

    query = bag_of_words_vector("espresso coffee")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": COLLECTION, "data": [query], "limit": 1},
    )
    hit = r.json()["data"][0][0]
    # TurbovecProvider.vectorSearch() merges entity into the hit — the raw API
    # must expose the entity sub-object with drupal_entity_id inside.
    assert "entity" in hit
    entity = hit["entity"]
    assert "drupal_entity_id" in entity
    assert "drupal_long_id" in entity
    assert isinstance(hit["id"], int)
    assert isinstance(hit["distance"], float)


def test_drupal_getvdbids_flow(client: TestClient) -> None:
    """Simulate getVdbIds(): query by drupal_entity_id to get turbovec integer IDs."""
    _full_setup(client)

    drupal_ids = ["node:1001:en", "node:1003:en"]
    r = client.post(
        "/v2/vectordb/entities/query",
        json={
            "collectionName": COLLECTION,
            "filter": {"drupal_entity_id": drupal_ids},
            "outputFields": ["id"],
            "limit": 10000,
        },
    )
    rows = r.json()["data"]
    returned_ids = {row["id"] for row in rows}
    expected_ids = {drupal_id_to_vdb_id(d) for d in drupal_ids}
    assert returned_ids == expected_ids


def test_drupal_delete_node_flow(client: TestClient) -> None:
    """Simulate deleteFromCollection(): resolve drupal_entity_id → vdb IDs → delete."""
    _full_setup(client)

    # Step 1: resolve drupal entity ID to turbovec ID (getVdbIds)
    drupal_entity_id = "node:1003:en"
    r = client.post(
        "/v2/vectordb/entities/query",
        json={
            "collectionName": COLLECTION,
            "filter": {"drupal_entity_id": [drupal_entity_id]},
            "outputFields": ["id"],
        },
    )
    vdb_id = r.json()["data"][0]["id"]
    assert vdb_id == drupal_id_to_vdb_id(drupal_entity_id)

    # Step 2: delete by vdb ID
    r2 = client.post(
        "/v2/vectordb/entities/delete",
        json={"collectionName": COLLECTION, "filter": f"id in [{vdb_id}]"},
    )
    assert r2.json()["data"]["deleteCount"] == 1

    # Step 3: confirm node is gone from search
    query = bag_of_words_vector("peat whisky distillery barley")
    r3 = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": COLLECTION, "data": [query], "limit": 5},
    )
    entity_ids = [h["entity"].get("drupal_entity_id") for h in r3.json()["data"][0]]
    assert "node:1003:en" not in entity_ids


def test_search_with_filter_ids_excludes_other_nodes(client: TestClient) -> None:
    """Simulate vectorSearch with prepareFilters → querySearch allowlist."""
    _full_setup(client)

    # filterIds restricts to energy + coffee nodes only
    allowed_vdb_ids = [
        drupal_id_to_vdb_id("node:1004:en"),
        drupal_id_to_vdb_id("node:1005:en"),
    ]
    query = bag_of_words_vector("pasta parmesan italy")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={
            "collectionName": COLLECTION,
            "data": [query],
            "limit": 5,
            "filterIds": allowed_vdb_ids,
        },
    )
    hits = r.json()["data"][0]
    returned_drupal_ids = {h["entity"]["drupal_entity_id"] for h in hits}
    assert returned_drupal_ids.issubset({"node:1004:en", "node:1005:en"})
    assert "node:1001:en" not in returned_drupal_ids


def test_offset_pagination_in_search(client: TestClient) -> None:
    """Simulate the offset parameter passed by the search_api_ai_search backend."""
    _full_setup(client)

    query = bag_of_words_vector("pasta parmesan italy")
    r0 = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": COLLECTION, "data": [query], "limit": 5, "offset": 0},
    )
    r1 = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": COLLECTION, "data": [query], "limit": 5, "offset": 1},
    )
    hits_0 = r0.json()["data"][0]
    hits_1 = r1.json()["data"][0]
    assert hits_0[1]["id"] == hits_1[0]["id"]


def test_collection_persists_entity_count(client: TestClient) -> None:
    _full_setup(client)
    r = client.post("/v2/vectordb/collections/describe", json={"collectionName": COLLECTION})
    assert r.json()["data"]["numEntities"] == 5


def test_drop_collection_removes_all_data(client: TestClient) -> None:
    _full_setup(client)
    client.post("/v2/vectordb/collections/drop", json={"collectionName": COLLECTION})
    r = client.post("/v2/vectordb/collections/describe", json={"collectionName": COLLECTION})
    assert r.status_code == 404
