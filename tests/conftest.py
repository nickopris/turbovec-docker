"""Shared fixtures for turbovec-api tests."""
from __future__ import annotations

import hashlib
import os
import struct
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Each test gets its own empty data directory so indexes never leak."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("API_BEARER_TOKEN", raising=False)


@pytest.fixture()
def client(isolated_data_dir) -> Generator[TestClient, None, None]:
    # Import app after env vars are patched so DATA_DIR and API_BEARER_TOKEN
    # are picked up correctly.
    import importlib
    import app.main as main_module
    importlib.reload(main_module)
    from app.main import app, registry
    registry._indexes.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def authed_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("API_BEARER_TOKEN", "secret-token")
    import importlib
    import app.main as main_module
    importlib.reload(main_module)
    from app.main import app, registry
    registry._indexes.clear()
    with TestClient(app) as c:
        yield c


def drupal_id_to_vdb_id(drupal_long_id: str) -> int:
    """Mirror the PHP SHA-256 hash → uint64 → int63 derivation used by TurbovecProvider."""
    digest = hashlib.sha256(drupal_long_id.encode()).digest()
    value = struct.unpack(">Q", digest[:8])[0]
    return value & 0x7FFFFFFFFFFFFFFF


def bag_of_words_vector(text: str, dim: int = 64) -> list[float]:
    """Deterministic bag-of-words vector matching examples/drupal_node_vector_test.py."""
    import re
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    vec = [0.0] * dim
    for token in tokens:
        h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    magnitude = sum(v * v for v in vec) ** 0.5
    if magnitude > 0:
        vec = [v / magnitude for v in vec]
    return vec


# Five Drupal-style test nodes matching the example script topics.
NODES = [
    {
        "nid": 1001,
        "drupal_long_id": "node:1001:en",
        "drupal_entity_id": "node:1001:en",
        "title": "Regional food in Italy",
        "body": "Pasta, risotto, olive oil, tomatoes, pizza, parmesan and Tuscan cooking.",
        "type": "article",
    },
    {
        "nid": 1002,
        "drupal_long_id": "node:1002:en",
        "drupal_entity_id": "node:1002:en",
        "title": "European car makers",
        "body": "Ferrari, Fiat, Alfa Romeo, BMW, Mercedes, Porsche and electric vehicles.",
        "type": "article",
    },
    {
        "nid": 1003,
        "drupal_long_id": "node:1003:en",
        "drupal_entity_id": "node:1003:en",
        "title": "Single malt whisky",
        "body": "Scotch whisky, peat, distillery, barley, cask ageing and tasting notes.",
        "type": "article",
    },
    {
        "nid": 1004,
        "drupal_long_id": "node:1004:en",
        "drupal_entity_id": "node:1004:en",
        "title": "Coffee brewing methods",
        "body": "Espresso, pour-over, French press, beans, grinder and water temperature.",
        "type": "article",
    },
    {
        "nid": 1005,
        "drupal_long_id": "node:1005:en",
        "drupal_entity_id": "node:1005:en",
        "title": "Renewable energy projects",
        "body": "Solar panels, wind turbines, battery storage, grid and green electricity.",
        "type": "article",
    },
]


def build_entity(node: dict, text_for_vector: str | None = None) -> dict:
    """Return an insert-ready entity with vector and Drupal metadata."""
    text = text_for_vector or f"{node['title']} {node['body']}"
    vdb_id = drupal_id_to_vdb_id(node["drupal_long_id"])
    return {
        "id": vdb_id,
        "vector": bag_of_words_vector(text),
        "drupal_entity_id": node["drupal_entity_id"],
        "drupal_long_id": node["drupal_long_id"],
        "title": node["title"],
        "body": node["body"],
        "type": node["type"],
    }
