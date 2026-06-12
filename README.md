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

## Notes

- `bit_width` supports `2`, `3`, or `4`, matching turbovec.
- Vectors are converted to contiguous `float32` arrays before being passed to turbovec.
- Mutations persist the index immediately. For very high ingest throughput, batch vectors in larger `POST /vectors` requests.
