#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


API_URL = "http://localhost:8000"
INDEX_NAME = "drupal-nodes"
DIM = 8
TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Node:
    nid: int
    title: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.title} {self.body}"


NODES = [
    Node(
        1001,
        "Regional food in Italy",
        "Pasta, risotto, olive oil, tomatoes, pizza, parmesan and Tuscan cooking.",
    ),
    Node(
        1002,
        "European car makers",
        "Ferrari, Fiat, Alfa Romeo, BMW, Mercedes, Porsche and electric vehicles.",
    ),
    Node(
        1003,
        "Single malt whisky",
        "Scotch whisky, bourbon barrels, peat smoke, Islay distilleries and oak casks.",
    ),
    Node(
        1004,
        "Coffee brewing methods",
        "Espresso, filter coffee, grinders, beans, roast levels and cafe equipment.",
    ),
    Node(
        1005,
        "Renewable energy projects",
        "Solar panels, wind farms, batteries, grid storage and clean electricity.",
    ),
]


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def vectorize(text: str) -> list[float]:
    vector = [0.0] * DIM
    for token in tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        slot = digest[0] % DIM
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[slot] += sign

    length = sum(value * value for value in vector) ** 0.5
    if length:
        vector = [round(value / length, 6) for value in vector]
    return vector


def request(method: str, path: str, payload: dict | None = None) -> dict | None:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"

    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 409:
            return {"already_exists": True}
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc


def seed() -> None:
    request("DELETE", f"/indexes/{INDEX_NAME}")
    request("POST", "/indexes", {"name": INDEX_NAME, "dim": DIM, "bit_width": 4})
    response = request(
        "POST",
        f"/indexes/{INDEX_NAME}/vectors",
        {
            "ids": [node.nid for node in NODES],
            "vectors": [vectorize(node.text) for node in NODES],
        },
    )
    print(json.dumps(response, indent=2))


def search(query: str, k: int) -> None:
    by_id = {node.nid: node for node in NODES}
    query_tokens = tokens(query)
    response = request(
        "POST",
        f"/indexes/{INDEX_NAME}/search",
        {"query": vectorize(query), "k": k},
    )
    if response is None:
        raise RuntimeError(f"Index '{INDEX_NAME}' does not exist. Run with --seed first.")

    print(f"query: {query}")
    print(f"tokens: {query_tokens}")
    for rank, (score, nid) in enumerate(zip(response["scores"][0], response["ids"][0]), start=1):
        node = by_id.get(nid)
        title = node.title if node else "<unknown>"
        print(f"{rank}. nid={nid} score={score:.4f} title={title}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and search fake Drupal node vectors.")
    parser.add_argument("query", nargs="*", help="Search text to tokenize and vectorize.")
    parser.add_argument("--seed", action="store_true", help="Recreate the drupal-nodes index.")
    parser.add_argument("-k", type=int, default=3, help="Number of nearest nodes to return.")
    args = parser.parse_args()

    if args.seed:
        seed()
    if args.query:
        search(" ".join(args.query), args.k)


if __name__ == "__main__":
    main()
