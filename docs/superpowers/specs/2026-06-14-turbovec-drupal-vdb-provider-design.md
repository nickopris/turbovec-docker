# Design: turbovec query endpoint + Drupal VDB provider module

**Date:** 2026-06-14
**Projects:** turbovec-api, drupalcms (`web/modules/custom/ai_vdb_provider_turbovec`)

---

## Overview

Add a metadata query endpoint to turbovec-api, then build a custom Drupal module that registers turbovec as a VDB (vector database) provider in the Drupal AI module ecosystem. The module mirrors the structure and interface of `ai_vdb_provider_milvus` but is standalone (no dependency on the Milvus module), strips all Zilliz/database-name logic, and uses turbovec's native collection-scoped API.

---

## Part 1: turbovec-api — New Query Endpoint

### Endpoint

`POST /v2/vectordb/entities/query`

### Request model (`QueryEntitiesRequest`)

```python
class QueryEntitiesRequest(BaseModel):
    collectionName: str
    filter: dict[str, list[Any]] = Field(default_factory=dict)
    outputFields: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)
```

- `filter`: each key is a metadata field name; value is a list of allowed values. Multiple keys are ANDed. Empty dict returns all records (up to limit).
- `outputFields`: if `None`, return all fields. `id` is always included.
- `limit` / `offset`: pagination over matched records.

### Response

Wraps in existing `ApiResponse` envelope:

```json
{
  "code": 0,
  "data": [
    { "id": 1, "drupal_entity_id": "node:42:en", "content": "..." },
    { "id": 2, "drupal_entity_id": "node:43:en", "content": "..." }
  ]
}
```

### Implementation

Handler in `main.py`:

1. Load the `ManagedIndex` via `registry.get(request.collectionName)`.
2. Iterate `idx.records` (dict of `uint64 id → metadata dict`).
3. For each record, check every key in `request.filter`: the record's value for that key must be in the filter's list (string comparison, coerced to str for both sides).
4. Collect matched records, apply `offset` and `limit`.
5. For each match, build output dict: start with `{"id": record_id}`, merge metadata fields filtered by `outputFields` (or all if `None`).
6. Return `ApiResponse(data=results)`.

Filter match logic (pseudocode):
```python
def matches(record: dict, filter: dict) -> bool:
    for field, allowed in filter.items():
        val = str(record.get(field, ""))
        if val not in [str(a) for a in allowed]:
            return False
    return True
```

### Notes

- `id` in the response is the uint64 integer key, not a metadata field.
- No expression language — only equality + IN semantics via list membership.
- Thread-safe: acquire `idx.lock` for the duration of the scan.

---

## Part 2: Drupal Module — `ai_vdb_provider_turbovec`

### Location

`/Users/nickopris/Work/fg/drupalcms/web/modules/custom/ai_vdb_provider_turbovec/`

### File structure

```
ai_vdb_provider_turbovec/
├── ai_vdb_provider_turbovec.info.yml
├── ai_vdb_provider_turbovec.services.yml
├── ai_vdb_provider_turbovec.routing.yml
├── ai_vdb_provider_turbovec.links.menu.yml
├── config/
│   ├── install/ai_vdb_provider_turbovec.settings.yml
│   └── schema/ai_vdb_provider_turbovec.schema.yml
└── src/
    ├── TurbovecClient.php
    ├── Form/
    │   └── TurbovecConfigForm.php
    └── Plugin/
        └── VdbProvider/
            └── TurbovecProvider.php
```

---

### `ai_vdb_provider_turbovec.info.yml`

```yaml
name: Turbovec VDB Provider
description: Enables turbovec as a Vector Database provider in the AI module.
package: AI Vector Database Providers
type: module
core_version_requirement: ^10.2 || ^11
configure: ai_vdb_provider_turbovec.settings_form

dependencies:
  - ai:ai
  - ai:ai_search
  - key:key
```

---

### `ai_vdb_provider_turbovec.services.yml`

```yaml
services:
  turbovec.client:
    class: Drupal\ai_vdb_provider_turbovec\TurbovecClient
    arguments: ['@http_client']
```

---

### `ai_vdb_provider_turbovec.routing.yml`

```yaml
ai_vdb_provider_turbovec.settings_form:
  path: '/admin/config/ai/vdb_providers/turbovec'
  defaults:
    _form: '\Drupal\ai_vdb_provider_turbovec\Form\TurbovecConfigForm'
    _title: 'Configure Turbovec'
  requirements:
    _permission: 'administer ai providers'
```

---

### `ai_vdb_provider_turbovec.links.menu.yml`

```yaml
ai_vdb_provider_turbovec.settings_menu:
  title: "Turbovec Configuration"
  description: "Configure Turbovec Vector Database"
  route_name: ai_vdb_provider_turbovec.settings_form
  parent: ai.admin_vdb_providers
```

---

### `config/install/ai_vdb_provider_turbovec.settings.yml`

```yaml
api_key: ''
server: ''
```

`port` is omitted from the install config — Drupal rejects `null` for a schema-typed `integer`. The provider derives the default port from the server URL scheme at runtime (443 for https, 80 for http).

---

### `config/schema/ai_vdb_provider_turbovec.schema.yml`

```yaml
ai_vdb_provider_turbovec.settings:
  type: config_object
  label: 'Turbovec Settings'
  mapping:
    api_key:
      type: string
      label: 'API Key'
    server:
      type: string
      label: 'Server'
    port:
      type: integer
      label: 'Port'
```

---

### `TurbovecClient.php`

Guzzle-based HTTP client. Constructor takes `\GuzzleHttp\Client`. Public methods:

| Method | turbovec endpoint |
|---|---|
| `createCollection(string $name, int $dim)` | `POST /v2/vectordb/collections/create` |
| `listCollections(): array` | `POST /v2/vectordb/collections/list` |
| `dropCollection(string $name)` | `POST /v2/vectordb/collections/drop` |
| `insertIntoCollection(string $name, array $data): array` | `POST /v2/vectordb/entities/insert` |
| `deleteFromCollection(string $name, array $ids): array` | `POST /v2/vectordb/entities/delete` |
| `search(string $name, array $vector, array $outputFields, int $limit, int $offset, array $filterIds = []): array` | `POST /v2/vectordb/entities/search` — `filterIds` maps to `"filterIds"` in the request body (array of uint64 ints); omitted when empty |
| `query(string $name, array $outputFields, array $filter = [], int $limit, int $offset): array` | `POST /v2/vectordb/entities/query` |

Private `makeRequest(string $path, string $method, mixed $body): array` handles:
- Base URL + port construction: `{server}:{port}/v2/vectordb/{path}`
- `Content-Type: application/json`, `Accept: application/json`
- Optional `Authorization: Bearer {apiKey}` header
- 120s connect/read/timeout
- Returns decoded JSON array

Setters: `setBaseUrl(string)`, `setPort(int)`, `setApiKey(string)`.

**No database name parameter anywhere.**

---

### `TurbovecProvider.php`

Plugin annotation:
```php
#[AiVdbProvider(
  id: 'turbovec',
  label: new TranslatableMarkup('Turbovec'),
)]
```

Extends `AiVdbProviderClientBase implements ContainerFactoryPluginInterface`.

Constructor injects: `ConfigFactoryInterface`, `KeyRepositoryInterface`, `EventDispatcherInterface`, `EntityFieldManagerInterface`, `MessengerInterface`, `TurbovecClient`.

Key method implementations:

**`getClient(): TurbovecClient`**
Reads config, calls `setBaseUrl()`, `setPort()`, `setApiKey()` on `$this->client`, returns it.

**`getConnectionData(): array`**
Reads `ai_vdb_provider_turbovec.settings`. Resolves `api_key` via `KeyRepositoryInterface` if set. Defaults port to 443 (https) or 80 (http) if not configured.

**`ping(): bool`**
Calls `getClient()->listCollections()`, returns `true` on success, `false` on exception.

**`isSetup(): bool`**
Returns `true` if `server` config is non-empty.

**`createCollection(string $collection_name, int $dimension, VdbSimilarityMetrics $metric_type, string $database): void`**
Calls `getClient()->createCollection($collection_name, $dimension)`. Metric type and database ignored (turbovec uses cosine internally, no database concept).

**`dropCollection(string $collection_name, string $database): void`**
Calls `getClient()->dropCollection($collection_name)`.

**`getCollections(string $database): array`**
Calls `getClient()->listCollections()`, returns the full response array (e.g. `['code' => 0, 'data' => ['col1', 'col2']]`). The base class `validateSettingsForm()` accesses `$collections['data']` directly, so the full envelope must be returned — not just `$result['data']`.

**`insertIntoCollection(string $collection_name, array $data, string $database): void`**
Calls `getClient()->insertIntoCollection($collection_name, $data)`. Checks response `code` is `0`.

**`deleteFromCollection(string $collection_name, array $ids, string $database): void`**
`$ids` are Drupal entity ID strings, not turbovec uint64 IDs. Must first call `getVdbIds($collection_name, $ids)` to resolve them to turbovec integer IDs, then call `getClient()->deleteFromCollection($collection_name, $resolvedIds)`. If `$resolvedIds` is empty, return early without calling the API.

**`prepareFilters(QueryInterface $query): mixed`**
Returns a `['field' => [values]]` PHP array. The interface declares return type `mixed` (confirmed from `AiVdbProviderSearchApiInterface`) so returning an array is valid — Pinecone provider does the same.
- Iterates `$query->getConditionGroup()->getConditions()` recursively.
- For each condition: extracts field identifier and values.
- Supports `=` and `IN` operators; merges values into the filter array under the field key.
- Ignores unsupported operators with a messenger warning.
- Returns the filter array (empty array = no filter).

**`querySearch(string $collection_name, array $output_fields, mixed $filters, int $limit, int $offset, string $database): array`**
`$filters` is the array from `prepareFilters()` (or an empty array when called without filters).
Calls `getClient()->query($collection_name, $output_fields, (array) $filters, $limit, $offset)`.
Returns `$result['data'] ?? []`.

**`vectorSearch(string $collection_name, array $vector_input, array $output_fields, QueryInterface $query, mixed $filters, int $limit, int $offset, string $database): array`**
If `$filters` is a non-empty array, first resolve it to a set of turbovec integer IDs by calling `querySearch($collection_name, ['id'], $filters, 16384, 0)` and extracting the `id` values — these become the `filterIds` allowlist. Then call `getClient()->search($collection_name, $vector_input, $output_fields, $limit, $offset, $filterIds)`.
Returns `$result['data'][0] ?? []` (turbovec wraps results in an outer array, one entry per query vector; we always send one vector).

**`getVdbIds(string $collection_name, array $drupalIds, string $database): array`**
Calls `querySearch()` with `filter = ['drupal_entity_id' => $drupalIds]`, `output_fields = ['id']`, `limit = 16384`.
Extracts and returns `id` values.

**`getRawEmbeddingFieldName(): ?string`**
Returns `'vector'`.

---

### `TurbovecConfigForm.php`

Extends `ConfigFormBase`. Config name: `ai_vdb_provider_turbovec.settings`.

Fields:
- `server` (textfield, required) — the turbovec-api base URL, e.g. `http://localhost:8000`
- `port` (textfield, optional) — overrides default port derived from scheme
- `api_key` (`key_select`, optional) — Bearer token via Key module

`validateForm()`: validates server is a valid URL, port is numeric if set, then calls `ping()` on a temporary client instance.

`submitForm()`: saves server (trailing slash stripped), port, api_key to config.

---

## Data Flow: Search API → turbovec

```
Search API query
  → TurbovecProvider::prepareFilters()   → ['drupal_entity_id' => ['node:42:en']]
  → TurbovecProvider::querySearch()      → TurbovecClient::query()
  → POST /v2/vectordb/entities/query     → turbovec-api metadata scan
  → [{id: 1, drupal_entity_id: ...}]    → Search API results

Vector search query
  → TurbovecProvider::vectorSearch()     → TurbovecClient::search()
  → POST /v2/vectordb/entities/search   → turbovec-api ANN search
  → [{id, distance, entity}]            → Search API results
```

---

## Out of Scope

- Multi-value / array metadata field filtering (Milvus `JSON_CONTAINS_ALL` equivalent)
- Milvus-style filter expression language
- Database/namespace partitioning
- Zilliz cloud support
- Unit tests (can be added later following Milvus provider test patterns)
