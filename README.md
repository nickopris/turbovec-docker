# turbovec API

Dockerized HTTP API for [RyanCodrai/turbovec](https://github.com/RyanCodrai/turbovec), using the Python `IdMapIndex` binding so callers can add, delete, and search vectors by stable `uint64` ids.

## Run

This project is Docker-only. Do not create a local virtualenv or install Python packages on the host OS.

```bash
docker compose up --build
```

The API listens on `http://localhost:8000`. Index files are written to `./data` as `.tvim` files and reloaded on startup.

## Authentication

Authentication is optional. If `API_BEARER_TOKEN` is set, every API route requires:

```text
Authorization: Bearer <token>
```

Run with auth enabled:

```bash
API_BEARER_TOKEN=dev-secret docker compose up --build
```

Then include the header in requests:

```bash
curl http://localhost:8000/health \
  -H 'Authorization: Bearer dev-secret'
```

If `API_BEARER_TOKEN` is unset or empty, the API accepts requests without an authorization header. In `/docs`, use the Authorize button when auth is enabled.

## Endpoints

- `GET /health`
- `POST /v2/vectordb/collections/create`
- `POST /v2/vectordb/collections/list`
- `POST /v2/vectordb/collections/describe`
- `POST /v2/vectordb/collections/drop`
- `POST /v2/vectordb/entities/insert`
- `POST /v2/vectordb/entities/search`
- `POST /indexes`
- `GET /indexes`
- `GET /indexes/{name}`
- `DELETE /indexes/{name}`
- `POST /indexes/{name}/vectors`
- `POST /indexes/{name}/search`
- `DELETE /indexes/{name}/vectors/{vector_id}`

Interactive docs are available at `http://localhost:8000/docs`.

To run shell commands inside the container:

```bash
docker compose run --rm turbovec-api python -c "import turbovec; print('turbovec ok')"
```

## Example

Create an index. `dim` must be a positive multiple of 8. You can omit it and turbovec will infer it from the first add.

```bash
curl -X POST http://localhost:8000/indexes \
  -H 'content-type: application/json' \
  -d '{"name":"demo","dim":8,"bit_width":4}'
```

Add vectors with stable ids:

```bash
curl -X POST http://localhost:8000/indexes/demo/vectors \
  -H 'content-type: application/json' \
  -d '{
    "ids": [101, 102, 103],
    "vectors": [
      [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
      [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
      [0.2, 0.1, 0.4, 0.3, 0.6, 0.5, 0.8, 0.7]
    ]
  }'
```

Search:

```bash
curl -X POST http://localhost:8000/indexes/demo/search \
  -H 'content-type: application/json' \
  -d '{"query":[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8],"k":2}'
```

Filtered search with an allowlist:

```bash
curl -X POST http://localhost:8000/indexes/demo/search \
  -H 'content-type: application/json' \
  -d '{"query":[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8],"k":2,"allowlist":[102,103]}'
```

Delete a vector:

```bash
curl -X DELETE http://localhost:8000/indexes/demo/vectors/102
```

## Vector database API

The `/v2/vectordb/...` routes provide a small collection/entity layer over turbovec. It gives you a familiar testing shape for create, insert, and search flows without tying the codebase to a specific vendor API.

Create a collection:

```bash
curl -X POST http://localhost:8000/v2/vectordb/collections/create \
  -H 'content-type: application/json' \
  -d '{"collectionName":"drupal_nodes","dimension":8}'
```

Insert entities. The `id` can be your Drupal node id, `vector` is the indexed vector, and every other field is stored as metadata:

```bash
curl -X POST http://localhost:8000/v2/vectordb/entities/insert \
  -H 'content-type: application/json' \
  -d '{
    "collectionName": "drupal_nodes",
    "data": [
      {
        "id": 1001,
        "title": "Regional food in Italy",
        "body": "Pasta, risotto, olive oil, tomatoes, pizza, parmesan and Tuscan cooking.",
        "vector": [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8]
      },
      {
        "id": 1002,
        "title": "European car makers",
        "body": "Ferrari, Fiat, Alfa Romeo, BMW, Mercedes, Porsche and electric vehicles.",
        "vector": [0.8,0.7,0.6,0.5,0.4,0.3,0.2,0.1]
      }
    ]
  }'
```

Search entities and request metadata back with `outputFields`:

```bash
curl -X POST http://localhost:8000/v2/vectordb/entities/search \
  -H 'content-type: application/json' \
  -d '{
    "collectionName": "drupal_nodes",
    "data": [[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8]],
    "limit": 2,
    "outputFields": ["title", "body"]
  }'
```

## Drupal-style node test data

The API stores vectors by stable `uint64` ids. For Drupal content, use the Drupal node id (`nid`) as the entity `id`, and store metadata such as title, body, type, or URL as fields on the entity.

This repo includes a small stdlib-only test script with five fake nodes:

- `1001`: Regional food in Italy
- `1002`: European car makers
- `1003`: Single malt whisky
- `1004`: Coffee brewing methods
- `1005`: Renewable energy projects

Start the API, then seed the index:

```bash
docker compose up --build
```

In another terminal:

```bash
python3 examples/drupal_node_vector_test.py --seed
```

Search by tokenized words:

```bash
python3 examples/drupal_node_vector_test.py pasta parmesan italy
python3 examples/drupal_node_vector_test.py ferrari porsche electric
python3 examples/drupal_node_vector_test.py peat whisky distillery
python3 examples/drupal_node_vector_test.py espresso beans grinder
python3 examples/drupal_node_vector_test.py solar battery wind
```

The example lowercases text, extracts `[a-z0-9]+` tokens, hashes each token into a 64-dimensional count vector, then sends that vector to `/v2/vectordb/entities/search`. It is intentionally simple test machinery rather than production embeddings.

## Notes

- `bit_width` supports `2`, `3`, or `4`, matching turbovec.
- Vectors are converted to contiguous `float32` arrays before being passed to turbovec.
- Mutations persist the index immediately. For very high ingest throughput, batch vectors in larger `POST /vectors` requests.
