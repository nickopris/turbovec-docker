"""Tests for /v2/vectordb/entities/search — mimics the Drupal vectorSearch() call."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import NODES, bag_of_words_vector, build_entity


def _seed(client: TestClient, collection: str = "nodes") -> None:
    client.post("/v2/vectordb/collections/create", json={"collectionName": collection, "dimension": 64})
    entities = [build_entity(n) for n in NODES]
    client.post("/v2/vectordb/entities/insert", json={"collectionName": collection, "data": entities})


def test_search_italy_food_returns_correct_node_first(client: TestClient) -> None:
    _seed(client)
    query = bag_of_words_vector("pasta parmesan italy")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 3},
    )
    assert r.status_code == 200
    hits = r.json()["data"][0]
    assert len(hits) == 3
    top = hits[0]["entity"]
    assert "Italy" in top["title"] or "italy" in top.get("body", "").lower()


def test_search_cars_returns_car_node_first(client: TestClient) -> None:
    _seed(client)
    query = bag_of_words_vector("ferrari porsche electric")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 3},
    )
    hits = r.json()["data"][0]
    top_title = hits[0]["entity"]["title"]
    assert "car" in top_title.lower() or "ferrari" in hits[0]["entity"].get("body", "").lower()


def test_search_whisky_does_not_appear_in_italy_results_at_high_threshold(client: TestClient) -> None:
    """Whisky should have a much lower score than Italy-food when querying for Italy."""
    _seed(client)
    query = bag_of_words_vector("pasta parmesan rome italy")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 5},
    )
    hits = r.json()["data"][0]
    titles = [h["entity"]["title"] for h in hits]
    # Italy node must rank above whisky
    italy_idx = next((i for i, t in enumerate(titles) if "Italy" in t), None)
    whisky_idx = next((i for i, t in enumerate(titles) if "whisky" in t.lower()), None)
    assert italy_idx is not None, "Italy node not found in results"
    if whisky_idx is not None:
        assert italy_idx < whisky_idx, "Italy food should rank above whisky for a Rome/pasta query"


def test_search_returns_distance_score(client: TestClient) -> None:
    _seed(client)
    query = bag_of_words_vector("solar wind battery")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 2},
    )
    hit = r.json()["data"][0][0]
    assert "distance" in hit
    assert isinstance(hit["distance"], float)
    assert 0.0 <= hit["distance"] <= 1.0


def test_search_output_fields_filters_metadata(client: TestClient) -> None:
    _seed(client)
    query = bag_of_words_vector("espresso beans grinder")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 1, "outputFields": ["title"]},
    )
    entity = r.json()["data"][0][0]["entity"]
    assert "title" in entity
    assert "body" not in entity


def test_search_with_offset_skips_top_results(client: TestClient) -> None:
    _seed(client)
    query = bag_of_words_vector("pasta parmesan italy")
    r_no_offset = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 3, "offset": 0},
    )
    r_offset = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 3, "offset": 1},
    )
    hits_base = r_no_offset.json()["data"][0]
    hits_shifted = r_offset.json()["data"][0]
    # Result at position 0 of the offset response should be position 1 of base
    assert hits_base[1]["id"] == hits_shifted[0]["id"]


def test_search_with_filter_ids_allowlist(client: TestClient) -> None:
    """filterIds restricts results to only those entity IDs."""
    from tests.conftest import drupal_id_to_vdb_id
    _seed(client)
    # Only allow the coffee node
    coffee_vdb_id = drupal_id_to_vdb_id("node:1004:en")
    query = bag_of_words_vector("pasta parmesan italy")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 5, "filterIds": [coffee_vdb_id]},
    )
    hits = r.json()["data"][0]
    assert len(hits) == 1
    assert hits[0]["entity"]["title"] == "Coffee brewing methods"


def test_search_entity_metadata_is_at_top_level_entity_key(client: TestClient) -> None:
    """The Drupal provider reads drupal_entity_id from hit['entity']; verify shape."""
    _seed(client)
    query = bag_of_words_vector("pasta parmesan italy")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 1},
    )
    hit = r.json()["data"][0][0]
    assert "entity" in hit
    assert "drupal_entity_id" in hit["entity"]
    assert "drupal_long_id" in hit["entity"]


def test_search_missing_collection_returns_404(client: TestClient) -> None:
    query = bag_of_words_vector("test")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "ghost", "data": [query], "limit": 1},
    )
    assert r.status_code == 404


def test_search_extra_field_in_body_returns_422(client: TestClient) -> None:
    """Extra fields are forbidden — protects against silent misuse."""
    _seed(client)
    query = bag_of_words_vector("test")
    r = client.post(
        "/v2/vectordb/entities/search",
        json={"collectionName": "nodes", "data": [query], "limit": 1, "unknownField": "x"},
    )
    assert r.status_code == 422
