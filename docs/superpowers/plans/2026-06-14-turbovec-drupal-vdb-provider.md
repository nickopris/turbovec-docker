# Turbovec Drupal VDB Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/v2/vectordb/entities/query` metadata-filter endpoint to turbovec-api, then build a standalone Drupal custom module (`ai_vdb_provider_turbovec`) that registers turbovec as a fully functional VDB provider in the Drupal AI ecosystem.

**Architecture:** Two independent subprojects sharing one plan. Part 1 extends `app/main.py` with a new Pydantic model and route handler for metadata filtering. Part 2 is a new Drupal module at `web/modules/custom/ai_vdb_provider_turbovec/` containing a Guzzle HTTP client, a VDB provider plugin, a config form, and PHPUnit unit tests — following the exact structure of `ai_vdb_provider_milvus` but standalone and turbovec-specific.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (Part 1); PHP 8.2 / Drupal 11 / Guzzle / PHPUnit (Part 2); no external services needed for tests (mocked Guzzle client).

**Spec:** `docs/superpowers/specs/2026-06-14-turbovec-drupal-vdb-provider-design.md`

---

## File Map

### Part 1 — turbovec-api
| File | Change |
|---|---|
| `app/main.py` | Add `QueryEntitiesRequest` model + `vectordb_query_entities` route handler |

### Part 2 — Drupal module
| File | Role |
|---|---|
| `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.info.yml` | Module metadata + dependencies |
| `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.services.yml` | Registers `turbovec.client` service |
| `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.routing.yml` | Admin config route |
| `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.links.menu.yml` | Admin menu link |
| `web/modules/custom/ai_vdb_provider_turbovec/config/install/ai_vdb_provider_turbovec.settings.yml` | Default config values |
| `web/modules/custom/ai_vdb_provider_turbovec/config/schema/ai_vdb_provider_turbovec.schema.yml` | Config schema |
| `web/modules/custom/ai_vdb_provider_turbovec/src/TurbovecClient.php` | Guzzle HTTP client wrapping all turbovec endpoints |
| `web/modules/custom/ai_vdb_provider_turbovec/src/Form/TurbovecConfigForm.php` | Admin settings form |
| `web/modules/custom/ai_vdb_provider_turbovec/src/Plugin/VdbProvider/TurbovecProvider.php` | VDB provider plugin (core logic) |
| `web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecClientTest.php` | Unit tests for HTTP client |
| `web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecProviderIndexAndSearchTest.php` | Semantic index+search unit tests |

---

## Task 1: turbovec-api query endpoint

**Goal:** Add `POST /v2/vectordb/entities/query` to `app/main.py` that filters stored metadata records and returns matches.

**Files:**
- Modify: `app/main.py`

**Acceptance Criteria:**
- [ ] `QueryEntitiesRequest` Pydantic model exists with `collectionName`, `filter`, `outputFields`, `limit`, `offset`
- [ ] Empty `filter` dict returns all records up to `limit`
- [ ] Each key in `filter` is ANDed; values matched as strings
- [ ] `outputFields=None` returns all metadata fields; `id` always included
- [ ] `offset`/`limit` paginate the matched set
- [ ] Handler acquires `idx.lock` for the full scan
- [ ] Response uses `ApiResponse` envelope (`{"code": 0, "data": [...]}`)

**Verify:** `curl -s -X POST http://localhost:8000/v2/vectordb/entities/query -H 'Content-Type: application/json' -d '{"collectionName":"test","filter":{"drupal_entity_id":["node:1:en"]},"limit":10}' | python3 -m json.tool` → `{"code": 0, "data": [...]}`

**Steps:**

- [ ] **Step 1: Add `QueryEntitiesRequest` model to `app/main.py`**

  Add after the existing `SearchEntitiesRequest` class (around line 207):

  ```python
  class QueryEntitiesRequest(BaseModel):
      model_config = ConfigDict(extra="forbid")

      collectionName: str
      filter: dict[str, list[Any]] = Field(default_factory=dict)
      outputFields: list[str] | None = None
      limit: int = Field(default=100, ge=1, le=10000)
      offset: int = Field(default=0, ge=0)
  ```

- [ ] **Step 2: Add the route handler to `app/main.py`**

  Add after the `vectordb_search_entities` handler (after line ~430):

  ```python
  @app.post("/v2/vectordb/entities/query", response_model=ApiResponse)
  def vectordb_query_entities(request: QueryEntitiesRequest) -> ApiResponse:
      idx = registry.get(request.collectionName)

      def matches(record: dict[str, Any]) -> bool:
          for field, allowed in request.filter.items():
              val = str(record.get(field, ""))
              if val not in [str(a) for a in allowed]:
                  return False
          return True

      results = []
      with idx.lock:
          for record_id, record in idx.records.items():
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
  ```

- [ ] **Step 3: Manual smoke test**

  Start the API: `cd /Users/nickopris/Work/turbovec-api && pip install -r requirements.txt -q && DATA_DIR=/tmp/tvtest uvicorn app.main:app --port 8000 &`

  Seed a collection:
  ```bash
  curl -s -X POST http://localhost:8000/v2/vectordb/collections/create \
    -H 'Content-Type: application/json' \
    -d '{"collectionName":"qtest","dimension":8}' | python3 -m json.tool

  curl -s -X POST http://localhost:8000/v2/vectordb/entities/insert \
    -H 'Content-Type: application/json' \
    -d '{"collectionName":"qtest","data":[{"id":1,"drupal_entity_id":"node:1:en","vector":[1,0,0,0,0,0,0,0]},{"id":2,"drupal_entity_id":"node:2:en","vector":[0,1,0,0,0,0,0,0]}]}' \
    | python3 -m json.tool
  ```

  Query with filter — expects only record 1:
  ```bash
  curl -s -X POST http://localhost:8000/v2/vectordb/entities/query \
    -H 'Content-Type: application/json' \
    -d '{"collectionName":"qtest","filter":{"drupal_entity_id":["node:1:en"]},"limit":10}' \
    | python3 -m json.tool
  ```
  Expected: `{"code": 0, "data": [{"id": 1, "drupal_entity_id": "node:1:en"}]}`

  Query with empty filter — expects both records:
  ```bash
  curl -s -X POST http://localhost:8000/v2/vectordb/entities/query \
    -H 'Content-Type: application/json' \
    -d '{"collectionName":"qtest","filter":{},"limit":10}' \
    | python3 -m json.tool
  ```
  Expected: `{"code": 0, "data": [{"id": 1, ...}, {"id": 2, ...}]}`

  Query with outputFields:
  ```bash
  curl -s -X POST http://localhost:8000/v2/vectordb/entities/query \
    -H 'Content-Type: application/json' \
    -d '{"collectionName":"qtest","filter":{},"outputFields":["drupal_entity_id"],"limit":10}' \
    | python3 -m json.tool
  ```
  Expected: records contain only `id` and `drupal_entity_id` fields.

  Kill server: `pkill -f "uvicorn app.main:app" || true && rm -rf /tmp/tvtest`

- [ ] **Step 4: Commit**

  ```bash
  cd /Users/nickopris/Work/turbovec-api
  git add app/main.py
  git commit -m "feat: add POST /v2/vectordb/entities/query metadata filter endpoint"
  ```

---

## Task 2: Drupal module scaffold (YAML files + config)

**Goal:** Create the module's directory structure and all YAML/config files so the module can be enabled in Drupal.

**Files:**
- Create: `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.info.yml`
- Create: `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.services.yml`
- Create: `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.routing.yml`
- Create: `web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.links.menu.yml`
- Create: `web/modules/custom/ai_vdb_provider_turbovec/config/install/ai_vdb_provider_turbovec.settings.yml`
- Create: `web/modules/custom/ai_vdb_provider_turbovec/config/schema/ai_vdb_provider_turbovec.schema.yml`

**Acceptance Criteria:**
- [ ] All six YAML files exist at the correct paths
- [ ] `info.yml` declares dependencies on `ai:ai`, `ai:ai_search`, `key:key`
- [ ] `services.yml` registers `turbovec.client` with `@http_client` argument
- [ ] Config install has `api_key: ''` and `server: ''` (no `port` key — Drupal rejects `null` for integer schema)
- [ ] Config schema types `port` as `integer`, `server` and `api_key` as `string`

**Verify:** `cd /Users/nickopris/Work/fg/drupalcms && php -r "require 'vendor/autoload.php'; \$yaml = \Symfony\Component\Yaml\Yaml::parseFile('web/modules/custom/ai_vdb_provider_turbovec/ai_vdb_provider_turbovec.info.yml'); echo \$yaml['name'];"` → `Turbovec VDB Provider`

**Steps:**

- [ ] **Step 1: Create module directory structure**

  ```bash
  mkdir -p /Users/nickopris/Work/fg/drupalcms/web/modules/custom/ai_vdb_provider_turbovec/src/Plugin/VdbProvider
  mkdir -p /Users/nickopris/Work/fg/drupalcms/web/modules/custom/ai_vdb_provider_turbovec/src/Form
  mkdir -p /Users/nickopris/Work/fg/drupalcms/web/modules/custom/ai_vdb_provider_turbovec/config/install
  mkdir -p /Users/nickopris/Work/fg/drupalcms/web/modules/custom/ai_vdb_provider_turbovec/config/schema
  mkdir -p /Users/nickopris/Work/fg/drupalcms/web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit
  ```

- [ ] **Step 2: Create `ai_vdb_provider_turbovec.info.yml`**

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

- [ ] **Step 3: Create `ai_vdb_provider_turbovec.services.yml`**

  ```yaml
  services:
    turbovec.client:
      class: Drupal\ai_vdb_provider_turbovec\TurbovecClient
      arguments: ['@http_client']
  ```

- [ ] **Step 4: Create `ai_vdb_provider_turbovec.routing.yml`**

  ```yaml
  ai_vdb_provider_turbovec.settings_form:
    path: '/admin/config/ai/vdb_providers/turbovec'
    defaults:
      _form: '\Drupal\ai_vdb_provider_turbovec\Form\TurbovecConfigForm'
      _title: 'Configure Turbovec'
    requirements:
      _permission: 'administer ai providers'
  ```

- [ ] **Step 5: Create `ai_vdb_provider_turbovec.links.menu.yml`**

  ```yaml
  ai_vdb_provider_turbovec.settings_menu:
    title: "Turbovec Configuration"
    description: "Configure Turbovec Vector Database"
    route_name: ai_vdb_provider_turbovec.settings_form
    parent: ai.admin_vdb_providers
  ```

- [ ] **Step 6: Create `config/install/ai_vdb_provider_turbovec.settings.yml`**

  ```yaml
  api_key: ''
  server: ''
  ```

- [ ] **Step 7: Create `config/schema/ai_vdb_provider_turbovec.schema.yml`**

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

- [ ] **Step 8: Commit**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  git add web/modules/custom/ai_vdb_provider_turbovec/
  git commit -m "feat(turbovec): add module scaffold — YAML and config files"
  ```

---

## Task 3: TurbovecClient HTTP client

**Goal:** Implement `TurbovecClient.php` — the Guzzle-based HTTP client that wraps all turbovec-api endpoints.

**Files:**
- Create: `web/modules/custom/ai_vdb_provider_turbovec/src/TurbovecClient.php`

**Acceptance Criteria:**
- [ ] All seven public methods exist: `createCollection`, `listCollections`, `dropCollection`, `insertIntoCollection`, `deleteFromCollection`, `search`, `query`
- [ ] `makeRequest` builds URL as `{baseUrl}:{port}/v2/vectordb/{path}`
- [ ] `Authorization: Bearer` header sent only when `$apiKey` is non-empty
- [ ] `search()` includes `filterIds` in body only when the array is non-empty
- [ ] `listCollections()` sends empty JSON object `{}` as body
- [ ] All timeouts set to 120s
- [ ] Returns decoded array from JSON response body

**Verify:** (Verified via TurbovecClientTest in Task 5)

**Steps:**

- [ ] **Step 1: Create `src/TurbovecClient.php`**

  ```php
  <?php

  namespace Drupal\ai_vdb_provider_turbovec;

  use Drupal\Component\Serialization\Json;
  use GuzzleHttp\Client;

  /**
   * HTTP client for the turbovec-api vector database.
   */
  class TurbovecClient {

    /**
     * The HTTP client.
     *
     * @var \GuzzleHttp\Client
     */
    protected Client $httpClient;

    /**
     * API bearer token.
     *
     * @var string
     */
    private string $apiKey = '';

    /**
     * Base URL (scheme + host, no trailing slash).
     *
     * @var string
     */
    private string $baseUrl = '';

    /**
     * Port override. 0 means derive from scheme.
     *
     * @var int
     */
    private int $port = 0;

    /**
     * Constructor.
     *
     * @param \GuzzleHttp\Client $httpClient
     *   The Guzzle HTTP client.
     */
    public function __construct(Client $httpClient) {
      $this->httpClient = $httpClient;
    }

    /**
     * Set the API key (bearer token).
     */
    public function setApiKey(string $apiKey): void {
      $this->apiKey = $apiKey;
    }

    /**
     * Set the base URL (e.g. "http://localhost").
     */
    public function setBaseUrl(string $baseUrl): void {
      $this->baseUrl = rtrim($baseUrl, '/');
    }

    /**
     * Set the port. 0 means derive from scheme (443 for https, 80 for http).
     */
    public function setPort(int $port): void {
      $this->port = $port;
    }

    /**
     * Create a collection.
     */
    public function createCollection(string $name, int $dimension): array {
      return $this->makeRequest('collections/create', [
        'collectionName' => $name,
        'dimension' => $dimension,
      ]);
    }

    /**
     * List all collections.
     */
    public function listCollections(): array {
      return $this->makeRequest('collections/list', new \stdClass());
    }

    /**
     * Drop a collection.
     */
    public function dropCollection(string $name): array {
      return $this->makeRequest('collections/drop', [
        'collectionName' => $name,
      ]);
    }

    /**
     * Insert entities into a collection.
     */
    public function insertIntoCollection(string $name, array $data): array {
      return $this->makeRequest('entities/insert', [
        'collectionName' => $name,
        'data' => [$data],
      ]);
    }

    /**
     * Delete entities from a collection by their turbovec integer IDs.
     */
    public function deleteFromCollection(string $name, array $ids): array {
      return $this->makeRequest('entities/delete', [
        'collectionName' => $name,
        'filter' => 'id in [' . implode(',', $ids) . ']',
      ]);
    }

    /**
     * Vector search.
     *
     * @param string $name
     *   Collection name.
     * @param array $vector
     *   The query vector (floats).
     * @param array $outputFields
     *   Fields to return.
     * @param int $limit
     *   Max results.
     * @param int $offset
     *   Offset.
     * @param array $filterIds
     *   Optional allowlist of turbovec integer IDs. Omitted when empty.
     */
    public function search(string $name, array $vector, array $outputFields, int $limit, int $offset, array $filterIds = []): array {
      $body = [
        'collectionName' => $name,
        'data' => [$vector],
        'outputFields' => $outputFields,
        'limit' => $limit,
        'offset' => $offset,
      ];
      if (!empty($filterIds)) {
        $body['filterIds'] = array_values($filterIds);
      }
      return $this->makeRequest('entities/search', $body);
    }

    /**
     * Metadata query (filter without a vector).
     *
     * @param string $name
     *   Collection name.
     * @param array $outputFields
     *   Fields to return.
     * @param array $filter
     *   Filter dict: ['field' => ['value1', 'value2'], ...].
     * @param int $limit
     *   Max results.
     * @param int $offset
     *   Offset.
     */
    public function query(string $name, array $outputFields, array $filter = [], int $limit = 100, int $offset = 0): array {
      return $this->makeRequest('entities/query', [
        'collectionName' => $name,
        'filter' => $filter ?: new \stdClass(),
        'outputFields' => $outputFields,
        'limit' => $limit,
        'offset' => $offset,
      ]);
    }

    /**
     * Execute an HTTP POST to a turbovec-api endpoint.
     *
     * @param string $path
     *   Relative path under /v2/vectordb/ (e.g. "collections/create").
     * @param mixed $body
     *   JSON-encodable request body.
     *
     * @return array
     *   Decoded JSON response.
     */
    protected function makeRequest(string $path, mixed $body): array {
      if (!$this->baseUrl) {
        throw new \RuntimeException('TurbovecClient: base URL is not set.');
      }

      $port = $this->port;
      if ($port === 0) {
        $port = str_starts_with($this->baseUrl, 'https') ? 443 : 80;
      }

      $url = $this->baseUrl . ':' . $port . '/v2/vectordb/' . $path;

      $options = [
        'connect_timeout' => 120,
        'read_timeout' => 120,
        'timeout' => 120,
        'headers' => [
          'Content-Type' => 'application/json',
          'Accept' => 'application/json',
        ],
        'body' => json_encode($body),
      ];

      if ($this->apiKey !== '') {
        $options['headers']['Authorization'] = 'Bearer ' . $this->apiKey;
      }

      $response = $this->httpClient->request('POST', $url, $options);
      return Json::decode((string) $response->getBody()) ?? [];
    }

  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  git add web/modules/custom/ai_vdb_provider_turbovec/src/TurbovecClient.php
  git commit -m "feat(turbovec): add TurbovecClient HTTP client"
  ```

---

## Task 4: TurbovecProvider VDB plugin

**Goal:** Implement `TurbovecProvider.php` — the Drupal VDB provider plugin that wires `TurbovecClient` into the AI module's Search API integration.

**Files:**
- Create: `web/modules/custom/ai_vdb_provider_turbovec/src/Plugin/VdbProvider/TurbovecProvider.php`

**Acceptance Criteria:**
- [ ] Plugin annotation has `id: 'turbovec'`
- [ ] `getClient()` configures and returns `TurbovecClient` from injected config
- [ ] `getConnectionData()` resolves `api_key` via Key module when set; defaults port from scheme
- [ ] `ping()` returns `false` on exception, `true` on successful `listCollections()`
- [ ] `isSetup()` returns `true` only when `server` config is non-empty
- [ ] `deleteFromCollection()` resolves Drupal entity IDs to turbovec IDs via `getVdbIds()` before deleting; returns early when nothing to delete
- [ ] `vectorSearch()` resolves non-empty `$filters` to an ID allowlist via `querySearch()` before calling `search()`
- [ ] `getCollections()` returns the full API response envelope (not just `data`)
- [ ] `getRawEmbeddingFieldName()` returns `'vector'`
- [ ] `prepareFilters()` returns a `['field' => [values]]` array; unsupported operators log a warning and are skipped

**Verify:** (Verified via TurbovecProviderIndexAndSearchTest in Task 6)

**Steps:**

- [ ] **Step 1: Create `src/Plugin/VdbProvider/TurbovecProvider.php`**

  ```php
  <?php

  namespace Drupal\ai_vdb_provider_turbovec\Plugin\VdbProvider;

  use Drupal\Core\Config\ConfigFactoryInterface;
  use Drupal\Core\Config\ImmutableConfig;
  use Drupal\Core\Entity\EntityFieldManagerInterface;
  use Drupal\Core\Form\FormStateInterface;
  use Drupal\Core\Messenger\MessengerInterface;
  use Drupal\Core\Plugin\ContainerFactoryPluginInterface;
  use Drupal\Core\StringTranslation\StringTranslationTrait;
  use Drupal\Core\StringTranslation\TranslatableMarkup;
  use Drupal\ai\Attribute\AiVdbProvider;
  use Drupal\ai\Base\AiVdbProviderClientBase;
  use Drupal\ai\Enum\VdbSimilarityMetrics;
  use Drupal\ai_vdb_provider_turbovec\TurbovecClient;
  use Drupal\key\KeyRepositoryInterface;
  use Drupal\search_api\Query\ConditionGroupInterface;
  use Drupal\search_api\Query\QueryInterface;
  use Symfony\Component\DependencyInjection\ContainerInterface;
  use Symfony\Component\EventDispatcher\EventDispatcherInterface;

  /**
   * Plugin implementation of the Turbovec VDB provider.
   */
  #[AiVdbProvider(
    id: 'turbovec',
    label: new TranslatableMarkup('Turbovec'),
  )]
  class TurbovecProvider extends AiVdbProviderClientBase implements ContainerFactoryPluginInterface {

    use StringTranslationTrait;

    /**
     * Constructor.
     */
    public function __construct(
      protected string $pluginId,
      protected mixed $pluginDefinition,
      protected ConfigFactoryInterface $configFactory,
      protected KeyRepositoryInterface $keyRepository,
      protected EventDispatcherInterface $eventDispatcher,
      protected EntityFieldManagerInterface $entityFieldManager,
      protected MessengerInterface $messenger,
      protected TurbovecClient $client,
    ) {
      parent::__construct(
        $this->pluginId,
        $this->pluginDefinition,
        $this->configFactory,
        $this->keyRepository,
        $this->eventDispatcher,
        $this->entityFieldManager,
        $this->messenger,
      );
    }

    /**
     * {@inheritdoc}
     */
    public static function create(ContainerInterface $container, array $configuration, $plugin_id, $plugin_definition): static {
      return new static(
        $plugin_id,
        $plugin_definition,
        $container->get('config.factory'),
        $container->get('key.repository'),
        $container->get('event_dispatcher'),
        $container->get('entity_field.manager'),
        $container->get('messenger'),
        $container->get('turbovec.client'),
      );
    }

    /**
     * {@inheritdoc}
     */
    public function getConfig(): ImmutableConfig {
      return $this->configFactory->get('ai_vdb_provider_turbovec.settings');
    }

    /**
     * Read connection parameters from config and override key from Key module.
     *
     * @return array{server: string, port: int, api_key: string}
     */
    public function getConnectionData(): array {
      $config = $this->getConfig();
      $server = $this->configuration['server'] ?? $config->get('server') ?? '';
      if (!$server) {
        throw new \RuntimeException('Turbovec server is not configured.');
      }

      $apiKey = '';
      $keyId = $config->get('api_key');
      if ($keyId) {
        $key = $this->keyRepository->getKey($keyId);
        if (!$key) {
          throw new \RuntimeException("API key '$keyId' not found in Key module.");
        }
        $apiKey = $key->getKeyValue();
      }
      if (!empty($this->configuration['api_key'])) {
        $apiKey = $this->configuration['api_key'];
      }

      $port = (int) ($this->configuration['port'] ?? $config->get('port') ?? 0);
      if ($port === 0) {
        $port = str_starts_with($server, 'https') ? 443 : 80;
      }

      return ['server' => $server, 'port' => $port, 'api_key' => $apiKey];
    }

    /**
     * Configure and return the HTTP client.
     */
    public function getClient(): TurbovecClient {
      $conn = $this->getConnectionData();
      $this->client->setBaseUrl($conn['server']);
      $this->client->setPort($conn['port']);
      $this->client->setApiKey($conn['api_key']);
      return $this->client;
    }

    /**
     * {@inheritdoc}
     */
    public function setAuthentication(mixed $authentication): void {
      $this->configuration['api_key'] = $authentication;
    }

    /**
     * {@inheritdoc}
     */
    public function ping(): bool {
      try {
        $this->getClient()->listCollections();
        return TRUE;
      }
      catch (\Throwable) {
        return FALSE;
      }
    }

    /**
     * {@inheritdoc}
     */
    public function isSetup(): bool {
      return (bool) $this->getConfig()->get('server');
    }

    /**
     * {@inheritdoc}
     */
    public function getCollections(string $database = 'default'): array {
      // Return the full envelope so the base class can access $result['data'].
      return $this->getClient()->listCollections();
    }

    /**
     * {@inheritdoc}
     */
    public function createCollection(
      string $collection_name,
      int $dimension,
      VdbSimilarityMetrics $metric_type = VdbSimilarityMetrics::CosineSimilarity,
      string $database = 'default',
    ): void {
      // turbovec uses cosine internally; metric_type and database are ignored.
      $this->getClient()->createCollection($collection_name, $dimension);
    }

    /**
     * {@inheritdoc}
     */
    public function dropCollection(string $collection_name, string $database = 'default'): void {
      $this->getClient()->dropCollection($collection_name);
    }

    /**
     * {@inheritdoc}
     */
    public function insertIntoCollection(string $collection_name, array $data, string $database = 'default'): void {
      $response = $this->getClient()->insertIntoCollection($collection_name, $data);
      if (($response['code'] ?? -1) !== 0) {
        throw new \RuntimeException('Failed to insert into turbovec collection: ' . ($response['message'] ?? 'unknown error'));
      }
    }

    /**
     * {@inheritdoc}
     *
     * $ids are Drupal entity ID strings. We resolve them to turbovec uint64 IDs
     * first via getVdbIds() before calling the delete endpoint.
     */
    public function deleteFromCollection(string $collection_name, array $ids, string $database = 'default'): void {
      $vdbIds = $this->getVdbIds($collection_name, $ids);
      if (empty($vdbIds)) {
        return;
      }
      $this->getClient()->deleteFromCollection($collection_name, $vdbIds);
    }

    /**
     * {@inheritdoc}
     *
     * Returns a ['field' => [values]] array consumed by querySearch() and
     * vectorSearch(). The interface return type is mixed, so returning an
     * array is valid (same approach as PineconeProvider).
     */
    public function prepareFilters(QueryInterface $query): mixed {
      $filters = [];
      $this->processConditionGroup($query->getConditionGroup(), $filters);
      return $filters;
    }

    /**
     * Recursively process a condition group into the filter array.
     */
    protected function processConditionGroup(ConditionGroupInterface $group, array &$filters): void {
      foreach ($group->getConditions() as $condition) {
        if ($condition instanceof ConditionGroupInterface) {
          $this->processConditionGroup($condition, $filters);
          continue;
        }

        $field = $condition->getField();
        $operator = $condition->getOperator();
        $values = is_array($condition->getValue()) ? $condition->getValue() : [$condition->getValue()];

        if ($operator === '=' || $operator === 'IN') {
          if (!isset($filters[$field])) {
            $filters[$field] = [];
          }
          foreach ($values as $v) {
            $filters[$field][] = (string) $v;
          }
        }
        else {
          $this->messenger->addWarning(
            $this->t('Turbovec VDB does not support the "@op" filter operator; condition on "@field" was skipped.', [
              '@op' => $operator,
              '@field' => $field,
            ])
          );
        }
      }
    }

    /**
     * {@inheritdoc}
     */
    public function querySearch(
      string $collection_name,
      array $output_fields,
      mixed $filters = '',
      int $limit = 10,
      int $offset = 0,
      string $database = 'default',
    ): array {
      $filterArray = is_array($filters) ? $filters : [];
      $result = $this->getClient()->query($collection_name, $output_fields, $filterArray, $limit, $offset);
      return $result['data'] ?? [];
    }

    /**
     * {@inheritdoc}
     *
     * If $filters is a non-empty array, we first resolve it to turbovec integer
     * IDs via querySearch() and use those as the filterIds allowlist.
     */
    public function vectorSearch(
      string $collection_name,
      array $vector_input,
      array $output_fields,
      QueryInterface $query,
      mixed $filters = '',
      int $limit = 10,
      int $offset = 0,
      string $database = 'default',
    ): array {
      $filterIds = [];
      if (is_array($filters) && !empty($filters)) {
        $idRows = $this->querySearch($collection_name, ['id'], $filters, 16384, 0);
        foreach ($idRows as $row) {
          if (isset($row['id'])) {
            $filterIds[] = (int) $row['id'];
          }
        }
      }

      $result = $this->getClient()->search(
        $collection_name,
        $vector_input,
        $output_fields,
        $limit,
        $offset,
        $filterIds,
      );
      // turbovec wraps results in an outer array (one entry per query vector).
      return $result['data'][0] ?? [];
    }

    /**
     * {@inheritdoc}
     */
    public function getVdbIds(string $collection_name, array $drupalIds, string $database = 'default'): array {
      $rows = $this->querySearch(
        collection_name: $collection_name,
        output_fields: ['id'],
        filters: ['drupal_entity_id' => array_values($drupalIds)],
        limit: 16384,
      );
      return array_column($rows, 'id');
    }

    /**
     * {@inheritdoc}
     */
    public function getRawEmbeddingFieldName(): ?string {
      return 'vector';
    }

  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  git add web/modules/custom/ai_vdb_provider_turbovec/src/Plugin/VdbProvider/TurbovecProvider.php
  git commit -m "feat(turbovec): add TurbovecProvider VDB plugin"
  ```

---

## Task 5: TurbovecConfigForm admin settings form

**Goal:** Implement the admin settings form so administrators can configure the turbovec server URL, port, and optional API key.

**Files:**
- Create: `web/modules/custom/ai_vdb_provider_turbovec/src/Form/TurbovecConfigForm.php`

**Acceptance Criteria:**
- [ ] Form has `server` (required textfield), `port` (optional textfield), `api_key` (`key_select`)
- [ ] `validateForm()` rejects non-URL server values and non-numeric ports
- [ ] `validateForm()` calls `ping()` and sets a form error if connection fails
- [ ] `submitForm()` saves server with trailing slash stripped, port as integer or null, api_key
- [ ] Config name constant is `ai_vdb_provider_turbovec.settings`

**Verify:** (Manual — enable module in Drupal and visit `/admin/config/ai/vdb_providers/turbovec`)

**Steps:**

- [ ] **Step 1: Create `src/Form/TurbovecConfigForm.php`**

  ```php
  <?php

  namespace Drupal\ai_vdb_provider_turbovec\Form;

  use Drupal\Core\Form\ConfigFormBase;
  use Drupal\Core\Form\FormStateInterface;
  use Drupal\ai\AiVdbProviderPluginManager;
  use Drupal\key\KeyRepositoryInterface;
  use Symfony\Component\DependencyInjection\ContainerInterface;

  /**
   * Admin configuration form for the Turbovec VDB provider.
   */
  class TurbovecConfigForm extends ConfigFormBase {

    const CONFIG_NAME = 'ai_vdb_provider_turbovec.settings';

    /**
     * @var \Drupal\ai\AiVdbProviderPluginManager
     */
    protected AiVdbProviderPluginManager $vdbProviderPluginManager;

    /**
     * @var \Drupal\key\KeyRepositoryInterface
     */
    protected KeyRepositoryInterface $keyRepository;

    /**
     * Constructor.
     */
    public function __construct(
      AiVdbProviderPluginManager $vdbProviderPluginManager,
      KeyRepositoryInterface $keyRepository,
    ) {
      $this->vdbProviderPluginManager = $vdbProviderPluginManager;
      $this->keyRepository = $keyRepository;
    }

    /**
     * {@inheritdoc}
     */
    public static function create(ContainerInterface $container): static {
      return new static(
        $container->get('ai.vdb_provider'),
        $container->get('key.repository'),
      );
    }

    /**
     * {@inheritdoc}
     */
    public function getFormId(): string {
      return 'ai_vdb_provider_turbovec_settings';
    }

    /**
     * {@inheritdoc}
     */
    protected function getEditableConfigNames(): array {
      return [static::CONFIG_NAME];
    }

    /**
     * {@inheritdoc}
     */
    public function buildForm(array $form, FormStateInterface $form_state): array {
      $config = $this->config(static::CONFIG_NAME);

      $form['server'] = [
        '#type' => 'textfield',
        '#title' => $this->t('Server'),
        '#required' => TRUE,
        '#description' => $this->t('The turbovec-api base URL, e.g. <code>http://localhost:8000</code> or <code>https://turbovec.example.com</code>.'),
        '#default_value' => $config->get('server'),
      ];

      $form['port'] = [
        '#type' => 'textfield',
        '#title' => $this->t('Port'),
        '#description' => $this->t('Optional port override. Defaults to 443 for HTTPS or 80 for HTTP when left empty.'),
        '#default_value' => $config->get('port'),
      ];

      $form['api_key'] = [
        '#type' => 'key_select',
        '#title' => $this->t('API Key (Bearer Token)'),
        '#description' => $this->t('Optional bearer token for turbovec-api authentication. Leave empty if the server requires no authentication.'),
        '#default_value' => $config->get('api_key'),
        '#empty_option' => $this->t('— No authentication —'),
      ];

      return parent::buildForm($form, $form_state);
    }

    /**
     * {@inheritdoc}
     */
    public function validateForm(array &$form, FormStateInterface $form_state): void {
      $server = $form_state->getValue('server');
      if (!filter_var($server, FILTER_VALIDATE_URL)) {
        $form_state->setErrorByName('server', $this->t('The server must be a valid URL (e.g. http://localhost:8000).'));
        return;
      }

      $port = $form_state->getValue('port');
      if ($port !== '' && $port !== NULL && !is_numeric($port)) {
        $form_state->setErrorByName('port', $this->t('The port must be a number.'));
        return;
      }

      // Test connectivity.
      $keyId = $form_state->getValue('api_key');
      $apiKey = '';
      if (!empty($keyId)) {
        $key = $this->keyRepository->getKey($keyId);
        if ($key) {
          $apiKey = $key->getKeyValue();
        }
      }

      /** @var \Drupal\ai_vdb_provider_turbovec\Plugin\VdbProvider\TurbovecProvider $provider */
      $provider = $this->vdbProviderPluginManager->createInstance('turbovec');
      $provider->setCustomConfig([
        'server' => $server,
        'port' => $port ? (int) $port : 0,
        'api_key' => $apiKey,
      ]);

      if (!$provider->ping()) {
        $form_state->setErrorByName('server', $this->t('Could not connect to the turbovec server. Check the URL, port, and API key.'));
      }

      parent::validateForm($form, $form_state);
    }

    /**
     * {@inheritdoc}
     */
    public function submitForm(array &$form, FormStateInterface $form_state): void {
      $port = $form_state->getValue('port');
      $this->config(static::CONFIG_NAME)
        ->set('server', rtrim($form_state->getValue('server'), '/'))
        ->set('port', $port !== '' && $port !== NULL ? (int) $port : NULL)
        ->set('api_key', $form_state->getValue('api_key'))
        ->save();

      parent::submitForm($form, $form_state);
    }

  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  git add web/modules/custom/ai_vdb_provider_turbovec/src/Form/TurbovecConfigForm.php
  git commit -m "feat(turbovec): add TurbovecConfigForm admin settings form"
  ```

---

## Task 6: Unit tests — TurbovecClient

**Goal:** Write `TurbovecClientTest.php` verifying that every `TurbovecClient` method sends the correct request body to the correct endpoint, with the correct headers.

**Files:**
- Create: `web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecClientTest.php`

**Acceptance Criteria:**
- [ ] Tests for all seven public methods pass
- [ ] Bearer token header test passes
- [ ] No-auth-header test passes
- [ ] Port-in-URL construction test passes
- [ ] `filterIds` included in search body only when non-empty

**Verify:**
```bash
cd /Users/nickopris/Work/fg/drupalcms
vendor/bin/phpunit web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecClientTest.php --testdox
```
Expected: all tests green.

> **Setup note:** If `vendor/bin/phpunit` does not exist, run:
> `composer require --dev drupal/core-dev --with-all-dependencies`
> This installs PHPUnit into `vendor/bin/phpunit`.

**Steps:**

- [ ] **Step 1: Install PHPUnit if needed**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  ls vendor/bin/phpunit 2>/dev/null || composer require --dev drupal/core-dev --with-all-dependencies
  ```

- [ ] **Step 2: Create `tests/src/Unit/TurbovecClientTest.php`**

  ```php
  <?php

  declare(strict_types=1);

  namespace Drupal\Tests\ai_vdb_provider_turbovec\Unit;

  use Drupal\Tests\UnitTestCase;
  use Drupal\ai_vdb_provider_turbovec\TurbovecClient;
  use GuzzleHttp\Client;
  use GuzzleHttp\Psr7\Response;

  /**
   * @coversDefaultClass \Drupal\ai_vdb_provider_turbovec\TurbovecClient
   * @group ai_vdb_provider_turbovec
   */
  class TurbovecClientTest extends UnitTestCase {

    /**
     * Build a TurbovecClient with a mock Guzzle client that captures requests.
     *
     * @return array{TurbovecClient, array}
     *   The client and a reference to the captured requests array.
     */
    private function buildClient(string $responseBody = '{"code":0,"data":{}}'): array {
      $captured = [];
      $mockHttp = $this->createMock(Client::class);
      $mockHttp->method('request')
        ->willReturnCallback(function (string $method, string $url, array $options) use (&$captured, $responseBody) {
          $captured[] = [
            'method' => $method,
            'url' => $url,
            'body' => json_decode($options['body'] ?? '{}', TRUE),
            'headers' => $options['headers'] ?? [],
          ];
          return new Response(200, [], $responseBody);
        });

      $client = new TurbovecClient($mockHttp);
      $client->setBaseUrl('http://localhost');
      $client->setPort(8000);

      return [$client, &$captured];
    }

    /**
     * @covers ::createCollection
     */
    public function testCreateCollection(): void {
      [$client, $captured] = $this->buildClient();
      $client->createCollection('my_col', 128);

      $this->assertCount(1, $captured);
      $this->assertStringContainsString('collections/create', $captured[0]['url']);
      $this->assertSame('my_col', $captured[0]['body']['collectionName']);
      $this->assertSame(128, $captured[0]['body']['dimension']);
    }

    /**
     * @covers ::listCollections
     */
    public function testListCollections(): void {
      [$client, $captured] = $this->buildClient('{"code":0,"data":["col1"]}');
      $result = $client->listCollections();

      $this->assertStringContainsString('collections/list', $captured[0]['url']);
      $this->assertSame(0, $result['code']);
    }

    /**
     * @covers ::dropCollection
     */
    public function testDropCollection(): void {
      [$client, $captured] = $this->buildClient();
      $client->dropCollection('my_col');

      $this->assertStringContainsString('collections/drop', $captured[0]['url']);
      $this->assertSame('my_col', $captured[0]['body']['collectionName']);
    }

    /**
     * @covers ::insertIntoCollection
     */
    public function testInsertIntoCollection(): void {
      [$client, $captured] = $this->buildClient('{"code":0,"data":{"insertCount":1}}');
      $client->insertIntoCollection('my_col', ['id' => 42, 'vector' => [0.1, 0.2], 'title' => 'Hello']);

      $this->assertStringContainsString('entities/insert', $captured[0]['url']);
      $this->assertSame('my_col', $captured[0]['body']['collectionName']);
      $this->assertSame(42, $captured[0]['body']['data'][0]['id']);
      $this->assertSame('Hello', $captured[0]['body']['data'][0]['title']);
    }

    /**
     * @covers ::deleteFromCollection
     */
    public function testDeleteFromCollection(): void {
      [$client, $captured] = $this->buildClient();
      $client->deleteFromCollection('my_col', [1, 2, 3]);

      $this->assertStringContainsString('entities/delete', $captured[0]['url']);
      $this->assertSame('my_col', $captured[0]['body']['collectionName']);
      $this->assertStringContainsString('1', $captured[0]['body']['filter']);
      $this->assertStringContainsString('2', $captured[0]['body']['filter']);
    }

    /**
     * @covers ::search
     */
    public function testSearch(): void {
      [$client, $captured] = $this->buildClient('{"code":0,"data":[[{"id":1,"distance":0.9,"entity":{}}]]}');
      $client->search('my_col', [0.1, 0.2], ['title'], 5, 0);

      $this->assertStringContainsString('entities/search', $captured[0]['url']);
      $this->assertSame('my_col', $captured[0]['body']['collectionName']);
      $this->assertSame([[0.1, 0.2]], $captured[0]['body']['data']);
      $this->assertSame(['title'], $captured[0]['body']['outputFields']);
      $this->assertSame(5, $captured[0]['body']['limit']);
      $this->assertArrayNotHasKey('filterIds', $captured[0]['body'], 'filterIds must be omitted when empty');
    }

    /**
     * @covers ::search
     */
    public function testSearchWithFilterIds(): void {
      [$client, $captured] = $this->buildClient('{"code":0,"data":[[{"id":1,"distance":0.9,"entity":{}}]]}');
      $client->search('my_col', [0.1, 0.2], ['title'], 5, 0, [10, 20]);

      $this->assertSame([10, 20], $captured[0]['body']['filterIds']);
    }

    /**
     * @covers ::query
     */
    public function testQuery(): void {
      [$client, $captured] = $this->buildClient('{"code":0,"data":[{"id":1,"drupal_entity_id":"node:1:en"}]}');
      $client->query('my_col', ['id', 'drupal_entity_id'], ['drupal_entity_id' => ['node:1:en']], 10, 0);

      $this->assertStringContainsString('entities/query', $captured[0]['url']);
      $this->assertSame('my_col', $captured[0]['body']['collectionName']);
      $this->assertSame(['node:1:en'], $captured[0]['body']['filter']['drupal_entity_id']);
      $this->assertSame(['id', 'drupal_entity_id'], $captured[0]['body']['outputFields']);
      $this->assertSame(10, $captured[0]['body']['limit']);
    }

    /**
     * @covers ::makeRequest
     */
    public function testBearerTokenHeader(): void {
      [$client, $captured] = $this->buildClient();
      $client->setApiKey('secret-token');
      $client->listCollections();

      $this->assertSame('Bearer secret-token', $captured[0]['headers']['Authorization']);
    }

    /**
     * @covers ::makeRequest
     */
    public function testNoAuthHeaderWhenNoApiKey(): void {
      [$client, $captured] = $this->buildClient();
      $client->listCollections();

      $this->assertArrayNotHasKey('Authorization', $captured[0]['headers']);
    }

    /**
     * @covers ::makeRequest
     */
    public function testPortInUrl(): void {
      [$client, $captured] = $this->buildClient();
      $client->listCollections();

      $this->assertStringContainsString('http://localhost:8000/v2/vectordb/collections/list', $captured[0]['url']);
    }

  }
  ```

- [ ] **Step 3: Run tests**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  vendor/bin/phpunit web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecClientTest.php --testdox
  ```

  Expected output (all green):
  ```
  Turbovec Client (Drupal\Tests\ai_vdb_provider_turbovec\Unit\TurbovecClient)
   ✔ Create collection
   ✔ List collections
   ✔ Drop collection
   ✔ Insert into collection
   ✔ Delete from collection
   ✔ Search
   ✔ Search with filter ids
   ✔ Query
   ✔ Bearer token header
   ✔ No auth header when no api key
   ✔ Port in url
  ```

- [ ] **Step 4: Commit**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  git add web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecClientTest.php
  git commit -m "test(turbovec): add TurbovecClientTest unit tests"
  ```

---

## Task 7: Unit tests — TurbovecProvider semantic index + search

**Goal:** Write `TurbovecProviderIndexAndSearchTest.php` using a bag-of-words vectorizer and an in-memory mock HTTP handler to verify the full index → search cycle, metadata filtering, deletion, and filter-to-allowlist resolution.

**Files:**
- Create: `web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecProviderIndexAndSearchTest.php`

**Acceptance Criteria:**
- [ ] `testIndexAndSearchByKeyword` passes: each of three topic-matched queries returns the correct node as top result
- [ ] `testQuerySearchByEntityId` passes: filtering by `drupal_entity_id` returns exactly one matching record
- [ ] `testDeleteRemovesFromResults` passes: delete call carries the resolved turbovec integer ID
- [ ] `testPrepareFiltersBuildsCorrectArray` passes: conditions correctly accumulated into filter array
- [ ] `testVectorSearchPassesFilterIdsAsAllowlist` passes: `filterIds` present in search request body

**Verify:**
```bash
cd /Users/nickopris/Work/fg/drupalcms
vendor/bin/phpunit web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecProviderIndexAndSearchTest.php --testdox
```
Expected: all five tests green.

**Steps:**

- [ ] **Step 1: Create `tests/src/Unit/TurbovecProviderIndexAndSearchTest.php`**

  ```php
  <?php

  declare(strict_types=1);

  namespace Drupal\Tests\ai_vdb_provider_turbovec\Unit;

  use Drupal\Core\Config\ConfigFactoryInterface;
  use Drupal\Core\Config\ImmutableConfig;
  use Drupal\Core\Entity\EntityFieldManagerInterface;
  use Drupal\Core\Messenger\MessengerInterface;
  use Drupal\Tests\UnitTestCase;
  use Drupal\ai\Enum\VdbSimilarityMetrics;
  use Drupal\ai_vdb_provider_turbovec\Plugin\VdbProvider\TurbovecProvider;
  use Drupal\ai_vdb_provider_turbovec\TurbovecClient;
  use Drupal\key\KeyRepositoryInterface;
  use GuzzleHttp\Client;
  use GuzzleHttp\Psr7\Response;
  use Drupal\search_api\Query\ConditionGroupInterface;
  use Drupal\search_api\Query\ConditionInterface;
  use Drupal\search_api\Query\QueryInterface;
  use Symfony\Component\EventDispatcher\EventDispatcherInterface;

  /**
   * @coversDefaultClass \Drupal\ai_vdb_provider_turbovec\Plugin\VdbProvider\TurbovecProvider
   * @group ai_vdb_provider_turbovec
   */
  class TurbovecProviderIndexAndSearchTest extends UnitTestCase {

    /**
     * Sample nodes matching the topics in drupal_node_vector_test.py.
     */
    private array $nodes = [
      1001 => ['id' => 1001, 'drupal_entity_id' => 'node:1001:en', 'title' => 'Regional food in Italy',   'body' => 'Pasta, risotto, olive oil, tomatoes, pizza, parmesan and Tuscan cooking.'],
      1002 => ['id' => 1002, 'drupal_entity_id' => 'node:1002:en', 'title' => 'European car makers',       'body' => 'Ferrari, Fiat, Alfa Romeo, BMW, Mercedes, Porsche and electric vehicles.'],
      1003 => ['id' => 1003, 'drupal_entity_id' => 'node:1003:en', 'title' => 'Single malt whisky',        'body' => 'Scotch whisky, bourbon barrels, peat smoke, Islay distilleries and oak casks.'],
      1004 => ['id' => 1004, 'drupal_entity_id' => 'node:1004:en', 'title' => 'Coffee brewing methods',    'body' => 'Espresso, filter coffee, grinders, beans, roast levels and cafe equipment.'],
      1005 => ['id' => 1005, 'drupal_entity_id' => 'node:1005:en', 'title' => 'Renewable energy projects', 'body' => 'Solar panels, wind farms, batteries, grid storage and clean electricity.'],
    ];

    /**
     * Deterministic bag-of-words vectorizer (SHA-256 token hashing).
     * Matches the algorithm in examples/drupal_node_vector_test.py.
     */
    private function vectorize(string $text, int $dim = 64): array {
      $vector = array_fill(0, $dim, 0.0);
      preg_match_all('/[a-z0-9]+/', strtolower($text), $matches);
      foreach ($matches[0] as $token) {
        $digest = hash('sha256', $token, TRUE);
        $slot = ord($digest[0]) % $dim;
        $vector[$slot] += 1.0;
      }
      $length = sqrt(array_sum(array_map(fn($v) => $v * $v, $vector)));
      if ($length > 0.0) {
        $vector = array_map(fn($v) => round($v / $length, 6), $vector);
      }
      return $vector;
    }

    /**
     * Cosine similarity between two equal-length float vectors.
     */
    private function cosine(array $a, array $b): float {
      $dot = 0.0;
      $na = 0.0;
      $nb = 0.0;
      foreach ($a as $i => $v) {
        $dot += $v * $b[$i];
        $na += $v * $v;
        $nb += $b[$i] * $b[$i];
      }
      $denom = sqrt($na) * sqrt($nb);
      return $denom > 0.0 ? $dot / $denom : 0.0;
    }

    /**
     * Build a TurbovecProvider backed by an in-memory mock HTTP handler.
     *
     * The mock handler:
     * - entities/insert  → stores records in $store keyed by integer id
     * - entities/search  → computes cosine similarity, returns top-k hits
     * - entities/query   → filters $store by the filter dict
     * - entities/delete  → records the call in $deleteCalls
     * - everything else  → {"code":0,"data":{}}
     *
     * @return array{TurbovecProvider, array, array}
     *   [provider, &$store, &$deleteCalls]
     */
    private function buildProvider(): array {
      $store = [];
      $deleteCalls = [];

      $mockHttp = $this->createMock(Client::class);
      $mockHttp->method('request')
        ->willReturnCallback(function (string $method, string $url, array $options) use (&$store, &$deleteCalls) {
          $body = json_decode($options['body'] ?? '{}', TRUE);

          if (str_contains($url, 'entities/insert')) {
            foreach ($body['data'] as $row) {
              $store[(int) $row['id']] = $row;
            }
            return new Response(200, [], json_encode(['code' => 0, 'data' => ['insertCount' => count($body['data'])]]));
          }

          if (str_contains($url, 'entities/search')) {
            $queryVec = $body['data'][0];
            $filterIds = isset($body['filterIds']) ? array_flip($body['filterIds']) : NULL;
            $limit = $body['limit'] ?? 10;
            $outputFields = $body['outputFields'] ?? NULL;

            $scores = [];
            foreach ($store as $id => $record) {
              if ($filterIds !== NULL && !isset($filterIds[$id])) {
                continue;
              }
              $scores[$id] = $this->cosine($queryVec, $record['vector']);
            }
            arsort($scores);
            $hits = [];
            foreach (array_slice(array_keys($scores), 0, $limit, TRUE) as $id) {
              $entity = $store[$id];
              unset($entity['vector']);
              if ($outputFields !== NULL) {
                $entity = array_intersect_key($entity, array_flip($outputFields));
              }
              $hits[] = ['id' => $id, 'distance' => $scores[$id], 'entity' => $entity];
            }
            return new Response(200, [], json_encode(['code' => 0, 'data' => [$hits]]));
          }

          if (str_contains($url, 'entities/query')) {
            $filter = $body['filter'] ?? [];
            $outputFields = $body['outputFields'] ?? NULL;
            $limit = $body['limit'] ?? 100;
            $offset = $body['offset'] ?? 0;
            $results = [];
            foreach ($store as $id => $record) {
              $match = TRUE;
              foreach ($filter as $field => $allowed) {
                if (!in_array((string) ($record[$field] ?? ''), array_map('strval', $allowed), TRUE)) {
                  $match = FALSE;
                  break;
                }
              }
              if ($match) {
                $entry = ['id' => $id];
                if ($outputFields === NULL) {
                  $entry = array_merge($entry, $record);
                  unset($entry['vector']);
                }
                else {
                  foreach ($outputFields as $f) {
                    if (isset($record[$f])) {
                      $entry[$f] = $record[$f];
                    }
                  }
                }
                $results[] = $entry;
              }
            }
            $paginated = array_slice($results, $offset, $limit);
            return new Response(200, [], json_encode(['code' => 0, 'data' => $paginated]));
          }

          if (str_contains($url, 'entities/delete')) {
            $deleteCalls[] = $body;
            return new Response(200, [], json_encode(['code' => 0, 'data' => []]));
          }

          return new Response(200, [], json_encode(['code' => 0, 'data' => []]));
        });

      $turbovecClient = new TurbovecClient($mockHttp);
      $turbovecClient->setBaseUrl('http://localhost');
      $turbovecClient->setPort(8000);

      // Mock Drupal services the provider needs.
      $mockConfig = $this->createMock(ImmutableConfig::class);
      $mockConfig->method('get')->willReturnMap([
        ['server', 'http://localhost'],
        ['port', 8000],
        ['api_key', ''],
      ]);
      $mockConfigFactory = $this->createMock(ConfigFactoryInterface::class);
      $mockConfigFactory->method('get')->willReturn($mockConfig);

      $provider = new TurbovecProvider(
        'turbovec',
        [],
        $mockConfigFactory,
        $this->createMock(KeyRepositoryInterface::class),
        $this->createMock(EventDispatcherInterface::class),
        $this->createMock(EntityFieldManagerInterface::class),
        $this->createMock(MessengerInterface::class),
        $turbovecClient,
      );

      return [$provider, &$store, &$deleteCalls];
    }

    /**
     * Index all sample nodes into the mock store.
     */
    private function indexNodes(TurbovecProvider $provider): void {
      foreach ($this->nodes as $node) {
        $data = $node;
        $data['vector'] = $this->vectorize($node['title'] . ' ' . $node['body']);
        $provider->insertIntoCollection('test_col', $data);
      }
    }

    /**
     * @covers ::insertIntoCollection
     * @covers ::vectorSearch
     */
    public function testIndexAndSearchByKeyword(): void {
      [$provider] = $this->buildProvider();
      $this->indexNodes($provider);

      $mockQuery = $this->createMock(QueryInterface::class);

      // "pasta pizza italy" → node 1001
      $queryVec = $this->vectorize('pasta pizza italy');
      $results = $provider->vectorSearch('test_col', $queryVec, ['id', 'title'], $mockQuery, [], 3);
      $this->assertSame(1001, $results[0]['id'], 'Italian food query should match node 1001 first');

      // "solar wind electricity" → node 1005
      $queryVec = $this->vectorize('solar wind electricity');
      $results = $provider->vectorSearch('test_col', $queryVec, ['id', 'title'], $mockQuery, [], 3);
      $this->assertSame(1005, $results[0]['id'], 'Energy query should match node 1005 first');

      // "whisky scotch peat" → node 1003
      $queryVec = $this->vectorize('whisky scotch peat');
      $results = $provider->vectorSearch('test_col', $queryVec, ['id', 'title'], $mockQuery, [], 3);
      $this->assertSame(1003, $results[0]['id'], 'Whisky query should match node 1003 first');
    }

    /**
     * @covers ::querySearch
     */
    public function testQuerySearchByEntityId(): void {
      [$provider] = $this->buildProvider();
      $this->indexNodes($provider);

      $results = $provider->querySearch(
        'test_col',
        ['id', 'drupal_entity_id', 'title'],
        ['drupal_entity_id' => ['node:1002:en']],
        10,
      );

      $this->assertCount(1, $results);
      $this->assertSame(1002, $results[0]['id']);
      $this->assertSame('node:1002:en', $results[0]['drupal_entity_id']);
    }

    /**
     * @covers ::deleteFromCollection
     * @covers ::getVdbIds
     */
    public function testDeleteRemovesFromResults(): void {
      [$provider, , $deleteCalls] = $this->buildProvider();
      $this->indexNodes($provider);

      $provider->deleteFromCollection('test_col', ['node:1004:en']);

      $this->assertCount(1, $deleteCalls, 'One delete call expected');
      // The filter string in the delete body must contain the resolved ID 1004.
      $this->assertStringContainsString('1004', $deleteCalls[0]['filter']);
    }

    /**
     * @covers ::prepareFilters
     */
    public function testPrepareFiltersBuildsCorrectArray(): void {
      [$provider] = $this->buildProvider();

      $condA = $this->createMock(ConditionInterface::class);
      $condA->method('getField')->willReturn('drupal_entity_id');
      $condA->method('getOperator')->willReturn('=');
      $condA->method('getValue')->willReturn('node:1001:en');

      $condB = $this->createMock(ConditionInterface::class);
      $condB->method('getField')->willReturn('drupal_entity_id');
      $condB->method('getOperator')->willReturn('IN');
      $condB->method('getValue')->willReturn(['node:1002:en', 'node:1003:en']);

      $condGroup = $this->createMock(ConditionGroupInterface::class);
      $condGroup->method('getConditions')->willReturn([$condA, $condB]);

      $mockQuery = $this->createMock(QueryInterface::class);
      $mockQuery->method('getConditionGroup')->willReturn($condGroup);

      $filters = $provider->prepareFilters($mockQuery);

      $this->assertIsArray($filters);
      $this->assertArrayHasKey('drupal_entity_id', $filters);
      $this->assertContains('node:1001:en', $filters['drupal_entity_id']);
      $this->assertContains('node:1002:en', $filters['drupal_entity_id']);
      $this->assertContains('node:1003:en', $filters['drupal_entity_id']);
    }

    /**
     * @covers ::vectorSearch
     */
    public function testVectorSearchPassesFilterIdsAsAllowlist(): void {
      [$provider, , $deleteCalls] = $this->buildProvider();
      $this->indexNodes($provider);

      // Captured HTTP bodies for search calls.
      $searchBodies = [];
      // We need to intercept the search call — rebuild provider with capture.
      $store = [];
      foreach ($this->nodes as $node) {
        $data = $node;
        $data['vector'] = $this->vectorize($node['title'] . ' ' . $node['body']);
        $store[(int) $node['id']] = $data;
      }

      $capturedSearch = [];
      $mockHttp2 = $this->createMock(Client::class);
      $mockHttp2->method('request')
        ->willReturnCallback(function (string $method, string $url, array $options) use (&$store, &$capturedSearch) {
          $body = json_decode($options['body'] ?? '{}', TRUE);
          if (str_contains($url, 'entities/search')) {
            $capturedSearch[] = $body;
            return new Response(200, [], json_encode(['code' => 0, 'data' => [[]]]));
          }
          if (str_contains($url, 'entities/query')) {
            // Return node 1003 as the matching record for the filter.
            return new Response(200, [], json_encode(['code' => 0, 'data' => [['id' => 1003]]]));
          }
          return new Response(200, [], json_encode(['code' => 0, 'data' => []]));
        });

      $turbovecClient2 = new TurbovecClient($mockHttp2);
      $turbovecClient2->setBaseUrl('http://localhost');
      $turbovecClient2->setPort(8000);

      $mockConfig = $this->createMock(ImmutableConfig::class);
      $mockConfig->method('get')->willReturnMap([
        ['server', 'http://localhost'],
        ['port', 8000],
        ['api_key', ''],
      ]);
      $mockConfigFactory = $this->createMock(ConfigFactoryInterface::class);
      $mockConfigFactory->method('get')->willReturn($mockConfig);

      $provider2 = new TurbovecProvider(
        'turbovec',
        [],
        $mockConfigFactory,
        $this->createMock(KeyRepositoryInterface::class),
        $this->createMock(EventDispatcherInterface::class),
        $this->createMock(EntityFieldManagerInterface::class),
        $this->createMock(MessengerInterface::class),
        $turbovecClient2,
      );

      $mockQuery = $this->createMock(QueryInterface::class);
      $provider2->vectorSearch(
        'test_col',
        $this->vectorize('whisky'),
        ['id', 'title'],
        $mockQuery,
        ['drupal_entity_id' => ['node:1003:en']],
        5,
      );

      $this->assertNotEmpty($capturedSearch, 'A search request must have been made');
      $this->assertArrayHasKey('filterIds', $capturedSearch[0], 'filterIds must be present in search body');
      $this->assertContains(1003, $capturedSearch[0]['filterIds']);
    }

  }
  ```

- [ ] **Step 2: Run tests**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  vendor/bin/phpunit web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecProviderIndexAndSearchTest.php --testdox
  ```

  Expected output:
  ```
  Turbovec Provider Index And Search (Drupal\Tests\ai_vdb_provider_turbovec\Unit\TurbovecProviderIndexAndSearch)
   ✔ Index and search by keyword
   ✔ Query search by entity id
   ✔ Delete removes from results
   ✔ Prepare filters builds correct array
   ✔ Vector search passes filter ids as allowlist
  ```

- [ ] **Step 3: Commit**

  ```bash
  cd /Users/nickopris/Work/fg/drupalcms
  git add web/modules/custom/ai_vdb_provider_turbovec/tests/src/Unit/TurbovecProviderIndexAndSearchTest.php
  git commit -m "test(turbovec): add TurbovecProviderIndexAndSearchTest semantic tests"
  ```

---

## Self-Review Checklist

| Spec requirement | Task |
|---|---|
| `POST /v2/vectordb/entities/query` endpoint | Task 1 |
| `QueryEntitiesRequest` with filter/outputFields/limit/offset | Task 1 |
| Filter match: AND semantics, string coercion | Task 1 |
| Thread-safe scan with `idx.lock` | Task 1 |
| Module YAML scaffold + config | Task 2 |
| `turbovec.client` service | Task 2 |
| `TurbovecClient` — all 7 methods + `makeRequest` | Task 3 |
| Bearer token auth, port-in-URL, filterIds omitted when empty | Task 3 |
| `TurbovecProvider` plugin `id: 'turbovec'` | Task 4 |
| `deleteFromCollection` resolves Drupal IDs first | Task 4 |
| `vectorSearch` resolves filters to filterIds allowlist | Task 4 |
| `getCollections` returns full envelope | Task 4 |
| `prepareFilters` returns array, handles `=` and `IN` | Task 4 |
| `port` omitted from install config | Task 2 |
| Admin config form with server/port/api_key | Task 5 |
| `validateForm` pings server | Task 5 |
| `TurbovecClientTest` — all HTTP method/header/URL tests | Task 6 |
| `TurbovecProviderIndexAndSearchTest` — 3 semantic queries | Task 7 |
| delete + querySearch + prepareFilters + filterIds tests | Task 7 |
