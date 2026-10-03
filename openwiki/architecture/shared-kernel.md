---
type: Reference
title: Shared Kernel
description: Describes the smart_tutor.shared package — cross-module domain value objects, typed identifiers, abstract model ports, ModelFactory, Settings, and infrastructure adapter stubs that every module may use.
tags: [shared-kernel, domain, ports, model-factory, settings, adapters]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-03T03:19:50.688Z
sources:
  - id: openwiki-source-a9cb74b417c32a807991a9fe
    resource: repo://backend/src/smart_tutor/shared/__init__.py
  - id: openwiki-source-9da3a634a70e3e4faa0c84dd
    resource: repo://backend/src/smart_tutor/shared/adapters/__init__.py
  - id: openwiki-source-2bf96f4cb9d4426b09b256a5
    resource: repo://backend/src/smart_tutor/shared/adapters/auth/__init__.py
  - id: openwiki-source-27a9565074f1a5659a6b8f67
    resource: repo://backend/src/smart_tutor/shared/adapters/aws/__init__.py
  - id: openwiki-source-a89de2c6b65b041ce273ff06
    resource: repo://backend/src/smart_tutor/shared/adapters/bedrock/__init__.py
  - id: openwiki-source-9243ee36d432be33787cb18c
    resource: repo://backend/src/smart_tutor/shared/adapters/model_factory.py
  - id: openwiki-source-6fd30657781815d8a88e54d7
    resource: repo://backend/src/smart_tutor/shared/adapters/postgres/__init__.py
  - id: openwiki-source-681406418d94903fdbe26550
    resource: repo://backend/src/smart_tutor/shared/config.py
  - id: openwiki-source-0c5a5c7341d87f26dd22d816
    resource: repo://backend/src/smart_tutor/shared/domain/citation.py
  - id: openwiki-source-5ce03e11c70148f322e758b5
    resource: repo://backend/src/smart_tutor/shared/domain/errors.py
  - id: openwiki-source-5460b8616d5cd7b6daa7976c
    resource: repo://backend/src/smart_tutor/shared/domain/ids.py
  - id: openwiki-source-4f3e1a9392fd139b358a8f7d
    resource: repo://backend/src/smart_tutor/shared/domain/token_usage.py
  - id: openwiki-source-960bfe4eeee36904a9955e60
    resource: repo://backend/src/smart_tutor/shared/ports/chat_model.py
  - id: openwiki-source-c0cad42826a7e42f375e8365
    resource: repo://backend/src/smart_tutor/shared/ports/clock.py
  - id: openwiki-source-e2ba111dbad66106b6e43410
    resource: repo://backend/src/smart_tutor/shared/ports/embedding_model.py
  - id: openwiki-source-7a12e0cc9b13f167c2f9b1de
    resource: repo://backend/tests/fakes/models.py
  - id: openwiki-source-568dbd58bde410621d3c4ec9
    resource: repo://backend/tests/unit/shared/test_fake_models.py
  - id: openwiki-source-a48025b881401015638b10b4
    resource: repo://backend/tests/unit/shared/test_token_usage.py
generated: { by: "openwiki/0.7.0", at: "2026-10-03T03:19:50.688Z" }
---

# Shared Kernel

The `smart_tutor.shared` package is the foundation layer that every other module depends on. It owns cross-module value objects and typed identifiers, abstract ports that decouple business logic from infrastructure, the `ModelFactory` that resolves model roles to concrete adapters, `Settings` driven from environment variables, and the infrastructure adapter sub-packages for Keycloak, PostgreSQL, AWS services, and Amazon Bedrock.

The strict rule is: **business code imports from `shared.domain` or `shared.ports`, never from `shared.adapters` or any vendor SDK directly**. All vendor SDK imports are confined to `shared.adapters`, which is the only place they appear in the codebase.

## Package structure

```
shared/
├── domain/
│   ├── ids.py          # typed identifiers (NewType)
│   ├── token_usage.py  # TokenUsage value object
│   ├── citation.py     # Citation value object
│   └── errors.py       # DomainError, NotFoundError, AccessDeniedError
├── ports/
│   ├── chat_model.py       # ChatModel ABC + message/result types
│   ├── embedding_model.py  # EmbeddingModel ABC
│   └── clock.py            # Clock ABC
├── adapters/
│   ├── auth/           # Keycloak JWT/JWKS verification (M0 stub)
│   ├── aws/            # S3, SQS, SSM boto3 clients (M0 stub)
│   ├── bedrock/        # BedrockConverseChatModel, NovaEmbeddingModel (M0 stub)
│   ├── postgres/       # SQLAlchemy/psycopg engine, sessions, unit of work (M0 stub)
│   └── model_factory.py  # ModelFactory
└── config.py           # Settings (pydantic-settings)
```

---

## Domain: typed identifiers

`shared/domain/ids.py` defines five identifiers using `typing.NewType`. `NewType` creates a distinct type at the type-checker level while remaining a plain `str` at runtime, so identifiers from different domains cannot be accidentally swapped.

| Type | Semantic |
|---|---|
| `UserId` | Keycloak `sub` claim — globally unique, never reassigned |
| `ThreadId` | Conversation thread |
| `SubjectId` | UUID in the shared subject catalogue — the UUID never changes even if the display name is edited |
| `DocumentId` | A learner's library entry (one copy per user) |
| `ContentId` | SHA-256 of the uploaded file bytes — shared by all `DocumentId`s that point to identical content |

The `DocumentId` / `ContentId` split lets the system deduplicate storage while keeping per-user metadata separate: two users uploading the same PDF get distinct `DocumentId`s that map to the same `ContentId`.

---

## Domain: TokenUsage

`TokenUsage` is a frozen dataclass with `input_tokens`, `output_tokens`, and a computed `total_tokens` property. It enforces a non-negativity invariant in `__post_init__`, raising `ValueError` on violation. The `+` operator produces a new `TokenUsage` by summing both fields, so callers can accumulate usage across multiple model calls without mutable state.

Every model method — `invoke`, `stream` (final chunk), and `structured` — returns or yields a `TokenUsage` value so callers can record cost and enforce budgets.

---

## Domain: Citation

`Citation` is a frozen dataclass attaching a source reference to an answer fragment. It carries `chunk_id`, `document_title`, `page`, and an `archived` flag. When `archived` is `True` the document has been removed from the active library but the citation still resolves — the UI is expected to display a visual marker rather than a broken link.

---

## Domain: errors

Three base exception classes form the error hierarchy. Entrypoints (FastAPI routers, MCP server) catch these and map them to HTTP status codes; business code raises the subclasses without knowing the transport.

```
Exception
└── DomainError          "A business rule was violated."
    ├── NotFoundError    "The entity does not exist or is not visible to the caller."
    └── AccessDeniedError "The caller may not access this resource."
```

Modules are expected to subclass these rather than raise them directly, so a router handler can distinguish a missing document from a missing thread by catching the specific subclass.

---

## Port: ChatModel

`ChatModel` is the abstract base class that all LLM adapters must implement. Business code, including the agent runtime, always programs against this interface — never against a vendor SDK or a model ID string.

### Message types

| Type | Purpose |
|---|---|
| `Message` | Single turn: `role` is `"system"`, `"user"`, `"assistant"`, or `"tool"`; `tool_call_id` links tool results back to their request |
| `ToolSpec` | Declares a tool the model may call: `name`, `description`, and `parameters` (JSON Schema dict) |
| `ToolCall` | A model-requested tool invocation: `id`, `name`, `arguments` |

### Result types

| Type | Purpose |
|---|---|
| `ChatResult` | Full response: `text`, `tool_calls` list, `usage` |
| `ChatChunk` | One streamed piece — text delta, a completed `ToolCall`, or the final `TokenUsage` (exactly one field is set) |
| `StructuredResult[T]` | Generic result for `structured`: validated Pydantic model `value` plus `usage` |

### Methods

```python
class ChatModel(ABC):
    def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ChatChunk]: ...

    async def invoke(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ChatResult: ...

    async def structured[T: BaseModel](
        self, messages: Sequence[Message], schema: type[T]
    ) -> StructuredResult[T]: ...
```

- `stream` is the primary path for user-facing replies; the **last chunk always carries `usage`** and no text.
- `invoke` is for non-streaming calls (evaluation, summarisation, background tasks).
- `structured` forces a typed output. Adapters may use a tool-call trick (Nova) or native structured-output mode depending on the provider.

The sequence below shows the streaming lifecycle:

```mermaid
sequenceDiagram
    participant Caller
    participant CM as ChatModel
    Caller->>CM: stream(messages, tools)
    loop text deltas
        CM-->>Caller: ChatChunk(text="...")
    end
    opt tool calls
        CM-->>Caller: ChatChunk(tool_call=ToolCall(...))
    end
    CM-->>Caller: ChatChunk(usage=TokenUsage(...))
```
*`stream` yields text deltas and optional tool calls, then terminates with a usage-only chunk.*

---

## Port: EmbeddingModel

`EmbeddingModel` is the abstract base class for all embedding adapters. It exposes two properties (`model_id`, `dimension`) that are recorded on every vector chunk stored in the database so the schema can be migrated or validated if the model changes.

```python
class EmbeddingModel(ABC):
    @property
    def model_id(self) -> str: ...   # recorded as embedding_model per chunk

    @property
    def dimension(self) -> int: ...  # recorded as embedding_dim per chunk

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    # uses Nova GENERIC_INDEX input type

    async def embed_query(self, text: str) -> list[float]: ...
    # uses Nova TEXT_RETRIEVAL input type
```

`embed_documents` produces vectors for indexing (Nova's `GENERIC_INDEX` input type). `embed_query` produces a query vector using the asymmetric `TEXT_RETRIEVAL` input type. Keeping these separate lets the adapter pass the correct embedding purpose to the model, which affects retrieval quality for asymmetric embedding models.

---

## Port: Clock

`Clock` is a minimal abstract base class with a single method `now() -> datetime` that returns a timezone-aware UTC datetime. It exists so time-dependent business rules (idle record detection, report generation) can be exercised deterministically in unit tests by injecting a fake clock, without patching `datetime`.

---

## Settings

`Settings` is a Pydantic `BaseSettings` subclass loaded from environment variables. All variables are prefixed `SMART_TUTOR_` and nested groups use `__` as the delimiter (e.g. `SMART_TUTOR_MODELS__AGENT__MODEL_ID`). An optional `.env` file is also read.

In production, secrets (database credentials, etc.) are injected by External Secrets Operator from AWS Secrets Manager, arriving as environment variables at runtime.

### All settings keys and defaults

| Key | Default | Notes |
|---|---|---|
| `environment` | `"local"` | Deployment environment name |
| `aws_region` | `"us-east-1"` | AWS region for all boto3 clients |
| `database_url` | `postgresql+psycopg://smart_tutor:smart_tutor@localhost:5432/smart_tutor` | SQLAlchemy async URL |
| `keycloak_issuer` | `http://localhost:8080/realms/smart-tutor` | JWT `iss` claim and JWKS base URL |
| `keycloak_audience` | `"smart-tutor-api"` | Expected JWT `aud` claim |
| `documents_bucket` | `"smart-tutor-documents"` | S3 bucket for uploaded files |
| `ingest_queue_url` | `http://localhost:4566/000000000000/smart-tutor-ingest` | SQS queue for ingest jobs (LocalStack default) |
| `mcp_url` | `http://localhost:8000/mcp` | MCP server endpoint |
| `learning_record_idle_minutes_param` | `/smart-tutor/learning-record-idle-minutes` | SSM parameter name for idle threshold |
| `rate_limit_per_minute` | `20` | Per-user API rate limit |
| `models` | `ModelsConfig()` | Nested model role configuration (see below) |

### ModelsConfig

`ModelsConfig` is a nested `BaseModel` inside `Settings`. Each entry is a `ModelConfig(provider, model_id, params)`. `provider` defaults to `"bedrock"` for all roles.

| Role key | Default model ID | Default params |
|---|---|---|
| `models.agent` | `us.amazon.nova-2-lite-v1:0` | *(none)* |
| `models.judge` | `qwen.qwen3-32b-v1:0` | `{"temperature": 0}` |
| `models.embedding` | `amazon.nova-2-multimodal-embeddings-v1:0` | `{"dimension": 1024}` |

---

## ModelFactory

`ModelFactory` is the single entry point through which business code and the agent runtime obtain model instances. It accepts a `Settings` instance at construction time and exposes two methods:

```python
class ModelFactory:
    def __init__(self, settings: Settings) -> None: ...

    def chat(self, role: ChatRole) -> ChatModel: ...
    # ChatRole.AGENT → Nova 2 Lite   (us.amazon.nova-2-lite-v1:0)
    # ChatRole.JUDGE → Qwen 3 32B   (qwen.qwen3-32b-v1:0, temperature=0)

    def embedding(self) -> EmbeddingModel: ...
    # → Nova 2 multimodal embeddings, dimension=1024
```

`ChatRole` is a `StrEnum` with two members: `AGENT` and `JUDGE`. Both methods read the appropriate `ModelConfig` from `settings.models` using `getattr(settings.models, role.value)` and delegate construction to the correct adapter.

**Both methods currently raise `NotImplementedError` (M0 milestone stub)** — the Bedrock adapter implementations are planned but not yet written. The error message includes the provider and model ID to guide the implementer.

### The role-not-ID rule

Business code must always call `ModelFactory.chat(ChatRole.AGENT)` or `ModelFactory.chat(ChatRole.JUDGE)` — never hard-code a model ID. Switching a model is a configuration change (set `SMART_TUTOR_MODELS__AGENT__MODEL_ID`) and it is gated on the full evaluation split defined in **PRD D15**. The factory is the single place that translates a role to a concrete adapter; changing it requires only a settings update, not a code change.

```mermaid
flowchart TD
    A["Business code"] -->|"chat(ChatRole.AGENT)"| B["ModelFactory"]
    A -->|"chat(ChatRole.JUDGE)"| B
    A -->|"embedding()"| B
    B -->|reads settings.models.agent| C["ChatModel (Bedrock)"]
    B -->|reads settings.models.judge| D["ChatModel (Bedrock)"]
    B -->|reads settings.models.embedding| E["EmbeddingModel (Bedrock)"]
```
*Business code asks for a role; ModelFactory reads Settings to build the adapter.*

---

## Adapters

`shared.adapters` contains the only place in the codebase where vendor SDKs are imported. Each sub-package implements one or more ports or provides an infrastructure client. All four sub-packages are currently M0 stubs (only docstrings; no implementations yet).

### Auth adapter (`shared.adapters.auth`)

Planned implementation of Keycloak JWT verification for both the API server and the MCP server. It will validate:
- **JWKS signature** — fetches the public keys from the Keycloak `/.well-known/jwks.json` endpoint derived from `settings.keycloak_issuer`.
- **`iss` claim** — must match `keycloak_issuer`.
- **`aud` claim** — must match `keycloak_audience`.
- **`exp` claim** — token must not be expired.

A successfully verified token will yield a `UserId` (the Keycloak `sub` claim).

See [Keycloak Auth integration](../integrations/keycloak-auth.md) for the full token lifecycle.

### PostgreSQL adapter (`shared.adapters.postgres`)

Planned wrapper around SQLAlchemy with the `psycopg` async driver. Will provide:
- An **async engine** constructed from `settings.database_url`.
- **Session factory** for dependency-injected database sessions.
- A **unit-of-work** helper that commits on success and rolls back on exception.

This will be the only place in the codebase that constructs or configures the database engine.

### AWS adapter (`shared.adapters.aws`)

Planned provider of configured boto3 clients for:
- **S3** — document storage (`settings.documents_bucket`).
- **SQS** — ingest job queue (`settings.ingest_queue_url`).
- **SSM Parameter Store** — runtime configuration (`settings.learning_record_idle_minutes_param`).

The `aws_region` setting will be passed to all clients.

### Bedrock adapter (`shared.adapters.bedrock`) — M0 stubs

Planned implementations of the model ports:

| Class | Port | Status |
|---|---|---|
| `BedrockConverseChatModel` | `ChatModel` | M0 stub |
| `NovaEmbeddingModel` | `EmbeddingModel` | M0 stub |

Both classes are declared but contain only docstrings. They will use the Amazon Bedrock Converse API. See [Bedrock Models integration](../integrations/bedrock-models.md) for model details.

---

## Testing: fakes

Unit tests never use the real Bedrock adapters. The `tests/fakes/models.py` module ships two deterministic in-process fakes:

**`FakeChatModel`**
- Constructed with scripted `ChatResult` replies and/or Pydantic model instances for structured calls.
- `invoke` pops the next reply in order and records every call in `self.calls`.
- `stream` is an async generator that calls `invoke` internally, then yields text word-by-word, followed by tool calls, then a final usage-only chunk — matching the real adapter's streaming contract.
- `structured` pops a structured value, validates it against the requested schema via `schema.model_validate(...)`, and wraps it in `StructuredResult`.

**`FakeEmbeddingModel`**
- Embeds text as a tiny deterministic vector using character statistics: `float(sum(ord(c) for c in text[i::dimension]))` for each dimension index `i`.
- `model_id` returns `"fake-embedding"`.
- `embed_documents` and `embed_query` produce vectors of exactly `dimension` floats, satisfying the port contract used by ranking tests.
- `embed_documents` and `embed_query` return identical vectors for the same input, so tests can assert equality across both call paths.

The test `test_stream_ends_with_usage` verifies that the last chunk from `stream` always carries usage, mirroring the contract real adapters must uphold. This ensures any service tested with the fake behaves identically with a real adapter at the streaming boundary.
