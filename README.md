# turbovec API

Dockerized HTTP API for [RyanCodrai/turbovec](https://github.com/RyanCodrai/turbovec), using the Python `IdMapIndex` binding so callers can add, delete, and search vectors by stable `uint64` ids.

## Run

This project is Docker-only. Do not create a local virtualenv or install Python packages on the host OS.

```bash
docker compose up --build
```

The API listens on `http://localhost:8000`. Index files are written to `./data` as `.tvim` files and reloaded on startup.

## Endpoints

- `GET /health`
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

## Drupal-style node test data

The API stores vectors by stable `uint64` ids. For Drupal content, use the Drupal node id (`nid`) as the vector id, and keep metadata such as title, body, type, or URL in your caller or test fixture.

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

The example lowercases text, extracts `[a-z0-9]+` tokens, hashes each token into an 8-dimensional vector, then sends that vector to `/indexes/drupal-nodes/search`. It is intentionally simple test machinery rather than production embeddings.

## Notes

- `bit_width` supports `2`, `3`, or `4`, matching turbovec.
- Vectors are converted to contiguous `float32` arrays before being passed to turbovec.
- Mutations persist the index immediately. For very high ingest throughput, batch vectors in larger `POST /vectors` requests.
