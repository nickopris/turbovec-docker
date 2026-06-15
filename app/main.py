from __future__ import annotations

import json
import os
import re
import secrets
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Path as ApiPath, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from turbovec import IdMapIndex


DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN") or None
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
bearer_scheme = HTTPBearer(auto_error=False)


def index_path(name: str) -> Path:
    return DATA_DIR / f"{name}.tvim"


def metadata_path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def require_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> None:
    if API_BEARER_TOKEN is None:
        return
    if credentials is None or not secrets.compare_digest(credentials.credentials, API_BEARER_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def load_metadata(name: str) -> dict[str, Any]:
    path = metadata_path(name)
    if not path.exists():
        return {"records": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"records": {}}

    records = {}
    for key, value in raw.get("records", {}).items():
        try:
            records[int(key)] = value
        except ValueError:
            continue
    return {"records": records}


def validate_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Index name must be 1-64 characters: letters, numbers, dots, underscores, or hyphens.",
        )
    return name


def as_float32_matrix(vectors: list[list[float]], field: str) -> np.ndarray:
    try:
        array = np.asarray(vectors, dtype=np.float32)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} must contain numeric vectors.") from exc
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2 or array.shape[1] == 0:
        raise HTTPException(status_code=422, detail=f"{field} must be a non-empty 2D vector array.")
    if not np.isfinite(array).all():
        raise HTTPException(status_code=422, detail=f"{field} cannot contain NaN or Infinity.")
    return np.ascontiguousarray(array, dtype=np.float32)


def as_uint64_array(values: list[int], field: str) -> np.ndarray:
    if not values:
        raise HTTPException(status_code=422, detail=f"{field} cannot be empty.")
    try:
        array = np.asarray(values, dtype=np.uint64)
    except (OverflowError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must contain unsigned 64-bit integers.") from exc
    if array.ndim != 1:
        raise HTTPException(status_code=422, detail=f"{field} must be a 1D integer array.")
    return array


class CreateIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dim: int | None = Field(default=None, ge=8, le=65536)
    bit_width: Literal[2, 3, 4] = 4

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, value: str) -> str:
        if not NAME_RE.fullmatch(value):
            raise ValueError("Use 1-64 characters: letters, numbers, dots, underscores, or hyphens.")
        return value

    @field_validator("dim")
    @classmethod
    def dim_is_multiple_of_8(cls, value: int | None) -> int | None:
        if value is not None and value % 8 != 0:
            raise ValueError("dim must be a positive multiple of 8.")
        return value


class AddVectorsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1)
    vectors: list[list[float]] = Field(min_length=1)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: list[float] | None = None
    queries: list[list[float]] | None = None
    k: int = Field(default=10, ge=1, le=1000)
    allowlist: list[int] | None = None

    @field_validator("queries")
    @classmethod
    def queries_not_empty(cls, value: list[list[float]] | None) -> list[list[float]] | None:
        if value is not None and not value:
            raise ValueError("queries cannot be empty.")
        return value


class IndexInfo(BaseModel):
    name: str
    dim: int | None
    bit_width: int
    size: int
    path: str


class AddVectorsResponse(BaseModel):
    name: str
    added: int
    size: int


class SearchResponse(BaseModel):
    scores: list[list[float]]
    ids: list[list[int]]


class CreateCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectionName: str
    dimension: int = Field(ge=8, le=65536)
    bitWidth: Literal[2, 3, 4] = 4

    @field_validator("collectionName")
    @classmethod
    def collection_name_is_safe(cls, value: str) -> str:
        if not NAME_RE.fullmatch(value):
            raise ValueError("Use 1-64 characters: letters, numbers, dots, underscores, or hyphens.")
        return value

    @field_validator("dimension")
    @classmethod
    def dimension_is_multiple_of_8(cls, value: int) -> int:
        if value % 8 != 0:
            raise ValueError("dimension must be a positive multiple of 8.")
        return value


class CollectionNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectionName: str


class InsertEntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectionName: str
    data: list[dict[str, Any]] = Field(min_length=1)


class SearchEntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectionName: str
    data: list[list[float]] = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    outputFields: list[str] | None = None
    filterIds: list[int] | None = None


class DeleteEntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectionName: str
    filter: str


class QueryEntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectionName: str
    filter: dict[str, list[Any]] = Field(default_factory=dict)
    outputFields: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


class ApiResponse(BaseModel):
    code: int = 0
    data: Any = None


@dataclass
class ManagedIndex:
    name: str
    index: IdMapIndex
    lock: threading.RLock
    records: dict[int, dict[str, Any]]

    def info(self) -> IndexInfo:
        return IndexInfo(
            name=self.name,
            dim=self.index.dim,
            bit_width=self.index.bit_width,
            size=len(self.index),
            path=str(index_path(self.name)),
        )

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.index.write(str(index_path(self.name)))
        metadata_path(self.name).write_text(
            json.dumps(
                {
                    "name": self.name,
                    "kind": "IdMapIndex",
                    "records": {str(key): value for key, value in sorted(self.records.items())},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


class IndexRegistry:
    def __init__(self) -> None:
        self._indexes: dict[str, ManagedIndex] = {}
        self._lock = threading.RLock()

    def load_existing(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for path in sorted(DATA_DIR.glob("*.tvim")):
                name = path.stem
                if not NAME_RE.fullmatch(name):
                    continue
                metadata = load_metadata(name)
                self._indexes[name] = ManagedIndex(
                    name=name,
                    index=IdMapIndex.load(str(path)),
                    lock=threading.RLock(),
                    records=metadata.get("records", {}),
                )

    def create(self, request: CreateIndexRequest) -> ManagedIndex:
        with self._lock:
            if request.name in self._indexes or index_path(request.name).exists():
                raise HTTPException(status_code=409, detail=f"Index '{request.name}' already exists.")
            idx = ManagedIndex(
                name=request.name,
                index=IdMapIndex(dim=request.dim, bit_width=request.bit_width),
                lock=threading.RLock(),
                records={},
            )
            idx.save()
            self._indexes[request.name] = idx
            return idx

    def get(self, name: str) -> ManagedIndex:
        validate_name(name)
        with self._lock:
            idx = self._indexes.get(name)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"Index '{name}' was not found.")
        return idx

    def list(self) -> list[IndexInfo]:
        with self._lock:
            return [idx.info() for idx in sorted(self._indexes.values(), key=lambda item: item.name)]

    def delete(self, name: str) -> None:
        validate_name(name)
        with self._lock:
            removed = self._indexes.pop(name, None)
        if removed is None:
            raise HTTPException(status_code=404, detail=f"Index '{name}' was not found.")
        index_path(name).unlink(missing_ok=True)
        metadata_path(name).unlink(missing_ok=True)


registry = IndexRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.load_existing()
    yield


app = FastAPI(
    title="turbovec API",
    summary="A small HTTP service for RyanCodrai/turbovec's IdMapIndex.",
    version="0.1.0",
    dependencies=[Security(require_bearer_token)],
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v2/vectordb/collections/create", response_model=ApiResponse)
def vectordb_create_collection(request: CreateCollectionRequest) -> ApiResponse:
    idx = registry.create(
        CreateIndexRequest(
            name=request.collectionName,
            dim=request.dimension,
            bit_width=request.bitWidth,
        )
    )
    return ApiResponse(data=idx.info().model_dump())


@app.post("/v2/vectordb/collections/list", response_model=ApiResponse)
def vectordb_list_collections() -> ApiResponse:
    return ApiResponse(
        data=[
            {
                "name": item.name,
                "dimension": item.dim,
                "numEntities": item.size,
            }
            for item in registry.list()
        ]
    )


@app.post("/v2/vectordb/collections/describe", response_model=ApiResponse)
def vectordb_describe_collection(request: CollectionNameRequest) -> ApiResponse:
    idx = registry.get(request.collectionName)
    info = idx.info()
    return ApiResponse(
        data={
            "collectionName": info.name,
            "dimension": info.dim,
            "numEntities": info.size,
            "bitWidth": info.bit_width,
        }
    )


@app.post("/v2/vectordb/collections/drop", response_model=ApiResponse)
def vectordb_drop_collection(request: CollectionNameRequest) -> ApiResponse:
    registry.delete(request.collectionName)
    return ApiResponse(data={})


@app.post("/v2/vectordb/entities/insert", response_model=ApiResponse)
def vectordb_insert_entities(request: InsertEntitiesRequest) -> ApiResponse:
    idx = registry.get(request.collectionName)
    ids: list[int] = []
    vectors: list[list[float]] = []
    records: dict[int, dict[str, Any]] = {}

    for row in request.data:
        if "id" not in row:
            raise HTTPException(status_code=422, detail="Each entity must include an id field.")
        if "vector" not in row:
            raise HTTPException(status_code=422, detail="Each entity must include a vector field.")
        try:
            entity_id = int(row["id"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Entity id must be an unsigned 64-bit integer.") from exc
        ids.append(entity_id)
        vectors.append(row["vector"])
        records[entity_id] = {key: value for key, value in row.items() if key != "vector"}

    vector_matrix = as_float32_matrix(vectors, "data.vector")
    id_array = as_uint64_array(ids, "data.id")
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Entity ids must be unique within an insert request.")

    try:
        with idx.lock:
            idx.index.add_with_ids(vector_matrix, id_array)
            idx.records.update(records)
            idx.save()
            size = len(idx.index)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ApiResponse(data={"insertCount": len(ids), "ids": ids, "numEntities": size})


@app.post("/v2/vectordb/entities/search", response_model=ApiResponse)
def vectordb_search_entities(request: SearchEntitiesRequest) -> ApiResponse:
    idx = registry.get(request.collectionName)
    matrix = as_float32_matrix(request.data, "data")
    allowlist = as_uint64_array(request.filterIds, "filterIds") if request.filterIds is not None else None

    fetch = request.offset + request.limit
    try:
        with idx.lock:
            scores, ids = idx.index.search(matrix, fetch, allowlist=allowlist)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown filter id: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    output_fields = request.outputFields
    results = []
    for result_scores, result_ids in zip(scores.astype(float).tolist(), ids.astype(object).tolist()):
        hits = []
        for score, entity_id in zip(result_scores, result_ids):
            record = idx.records.get(entity_id, {"id": entity_id})
            entity = dict(record)
            if output_fields is not None:
                entity = {field: entity[field] for field in output_fields if field in entity}
            hits.append({"id": entity_id, "distance": score, "entity": entity})
        results.append(hits[request.offset:])

    return ApiResponse(data=results)


@app.post("/v2/vectordb/entities/delete", response_model=ApiResponse)
def vectordb_delete_entities(request: DeleteEntitiesRequest) -> ApiResponse:
    idx = registry.get(request.collectionName)

    match = re.search(r'id\s+in\s*\[([^\]]*)\]', request.filter, re.IGNORECASE)
    if not match:
        raise HTTPException(status_code=422, detail="filter must be in the form 'id in [1,2,3]'")

    ids = [int(x.strip()) for x in match.group(1).split(',') if x.strip()]
    if not ids:
        return ApiResponse(data={"deleteCount": 0})

    uint64_ids = as_uint64_array(ids, "filter ids")
    deleted = 0
    with idx.lock:
        for uid in uint64_ids:
            if uid in idx.records:
                del idx.records[uid]
                idx.index.remove(int(uid))
                deleted += 1
        if deleted:
            idx.save()

    return ApiResponse(data={"deleteCount": deleted})


@app.post("/v2/vectordb/entities/query", response_model=ApiResponse)
def vectordb_query_entities(request: QueryEntitiesRequest) -> ApiResponse:
    idx = registry.get(request.collectionName)

    str_filter = {field: {str(a) for a in vals} for field, vals in request.filter.items()}

    def matches(record: dict[str, Any]) -> bool:
        for field, allowed_set in str_filter.items():
            val = str(record.get(field, ""))
            if val not in allowed_set:
                return False
        return True

    with idx.lock:
        snapshot = dict(idx.records)

    results = []
    for record_id, record in snapshot.items():
        if not matches(record):
            continue
        entry: dict[str, Any] = {"id": record_id}
        if request.outputFields is None:
            entry.update(record)
        else:
            for field in request.outputFields:
                if field in record:
                    entry[field] = record[field]
        results.append(entry)

    paginated = results[request.offset : request.offset + request.limit]
    return ApiResponse(data=paginated)


@app.post("/indexes", response_model=IndexInfo, status_code=201)
def create_index(request: CreateIndexRequest) -> IndexInfo:
    return registry.create(request).info()


@app.get("/indexes", response_model=list[IndexInfo])
def list_indexes() -> list[IndexInfo]:
    return registry.list()


@app.get("/indexes/{name}", response_model=IndexInfo)
def get_index(name: Annotated[str, ApiPath()]) -> IndexInfo:
    return registry.get(name).info()


@app.delete("/indexes/{name}", status_code=204, response_class=Response)
def delete_index(name: Annotated[str, ApiPath()]) -> Response:
    registry.delete(name)
    return Response(status_code=204)


@app.post("/indexes/{name}/vectors", response_model=AddVectorsResponse)
def add_vectors(name: Annotated[str, ApiPath()], request: AddVectorsRequest) -> AddVectorsResponse:
    idx = registry.get(name)
    vectors = as_float32_matrix(request.vectors, "vectors")
    ids = as_uint64_array(request.ids, "ids")
    if len(ids) != vectors.shape[0]:
        raise HTTPException(status_code=422, detail="ids length must match vectors row count.")

    try:
        with idx.lock:
            idx.index.add_with_ids(vectors, ids)
            idx.save()
            size = len(idx.index)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return AddVectorsResponse(name=name, added=int(vectors.shape[0]), size=size)


@app.post("/indexes/{name}/search", response_model=SearchResponse)
def search(name: Annotated[str, ApiPath()], request: SearchRequest) -> SearchResponse:
    idx = registry.get(name)
    if request.query is None and request.queries is None:
        raise HTTPException(status_code=422, detail="Provide either query or queries.")
    if request.query is not None and request.queries is not None:
        raise HTTPException(status_code=422, detail="Provide query or queries, not both.")

    queries = [request.query] if request.query is not None else request.queries
    matrix = as_float32_matrix(queries or [], "query")
    allowlist = as_uint64_array(request.allowlist, "allowlist") if request.allowlist is not None else None

    try:
        with idx.lock:
            scores, ids = idx.index.search(matrix, request.k, allowlist=allowlist)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown allowlist id: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SearchResponse(scores=scores.astype(float).tolist(), ids=ids.astype(object).tolist())


@app.delete("/indexes/{name}/vectors/{vector_id}", status_code=204, response_class=Response)
def remove_vector(name: Annotated[str, ApiPath()], vector_id: Annotated[int, ApiPath(ge=0)]) -> Response:
    idx = registry.get(name)
    try:
        with idx.lock:
            removed = idx.index.remove(vector_id)
            if not removed:
                raise HTTPException(status_code=404, detail=f"Vector id {vector_id} was not found.")
            idx.records.pop(vector_id, None)
            idx.save()
    except OverflowError as exc:
        raise HTTPException(status_code=422, detail="vector_id must fit in uint64.") from exc
    return Response(status_code=204)
