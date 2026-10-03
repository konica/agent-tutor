---
type: integration
title: RAG MCP Server and Retrieval
description: Documents the MCP server's two tools (search and get_chunk), the access-enforced SQL filter that scopes retrieval to a learner's own readable documents, iterative HNSW search with exact-search fallback, and the Retriever port through which the tutoring agent accesses chunks without touching chunk tables directly.
tags: [mcp, rag, retrieval, pgvector, access-control, tutoring, knowledge, hnsw]
sources:
  - id: openwiki-source-148109c968469387883a2911
    resource: repo://backend/evals/thresholds.yaml
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-daaefe65bdc8373e27d6b95d
    resource: repo://backend/src/smart_tutor/apps/mcp_server/server.py
  - id: openwiki-source-91a36491842f2eb410d9e6f9
    resource: repo://backend/src/smart_tutor/tutoring/README.md
  - id: openwiki-source-473ea646d59721d67fc55bbb
    resource: repo://sdd/prd.md
  - id: openwiki-source-e378957ac9ba2f1c5932cd66
    resource: repo://sdd/specs/2026-10-02-project-structure-design.md
verified:
  - by: openwiki/0.7.0
    at: 2026-10-03T03:19:50.688Z
generated: { by: "openwiki/0.7.0", at: "2026-10-03T03:19:50.688Z" }
---

# RAG MCP Server and Retrieval

The RAG MCP server is a dedicated deployable that puts an access-enforced retrieval interface between the Smart Tutor agent and the chunk tables in PostgreSQL. It exposes exactly two tools over streamable HTTP and is the only runtime path through which the agent reaches embedded document text.

## Transport

The server is instantiated as an `MCPServer` from the `mcp` 2.x library and listens at `:8000/mcp` on the `streamable-http` transport:

```python
# backend/src/smart_tutor/apps/mcp_server/server.py
from mcp.server import MCPServer

mcp = MCPServer("rag-mcp")

def main() -> None:
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

`host` and `port` are passed directly to `run()`. Inside the cluster the service is `ClusterIP`-only; a `NetworkPolicy` allows inbound traffic from the agent only, so it is never reachable from the web or API tier.

## Tools

Both tools are declared in `apps/mcp_server/tools.py`, which is a planned stub at M1. The server docstring explicitly records this as an M1 task. Tool signatures and behaviour are fully specified in the PRD and design spec; the implementation wires into `knowledge.application`.

### `search(query, subject_ids, k=5)`

Performs a vector similarity search scoped to a specific learner's readable documents.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | — | The question or text to embed and search against |
| `subject_ids` | `list[UUID]` | — | The thread's current subject ids; at most 3 (US-4) |
| `k` | `int` | `5` | Maximum number of chunks to return |

**JWT validation** happens first: the tool reads the `Authorization` header forwarded by the agent, validates the JWT in code (JWKS, `iss`, `exp`, `aud`), and extracts `sub`. No further call proceeds until this succeeds; an invalid or missing token causes a `401` before any database query.

**Returns** a ranked list of chunks with their similarity scores and citation metadata (document display title, `content_id`, `page`).

### `get_chunk(chunk_id)`

Resolves a single chunk by id for citation purposes. The same JWT validation and `can_read` check applies: the chunk is returned only if the caller's `sub` has a readable, ready, non-archived document whose `content_id` matches the chunk's `content_id`. This prevents a learner from reading another learner's chunk text even when the underlying content is shared.

## Access-Enforced SQL Filter

The search filter is constructed entirely in SQL, not in application code or in the prompt. After extracting `sub` from the validated JWT, the server builds a predicate over the `chunks` table:

```sql
chunks.content_id IN (
    SELECT documents.content_id
    FROM   documents
    JOIN   document_subjects ON document_subjects.document_id = documents.document_id
    WHERE  documents.owner_id   = :sub          -- Releases 1–3; Release 4 adds grants and visibility
    AND    documents.state      = 'ready'
    AND    documents.archived   = false
    AND    document_subjects.subject_id IN :requested_subject_ids
)
```

Key properties:

- **Owner isolation:** `owner_id = sub` is the enforced boundary for Releases 1–3. Release 4 extends this to also accept rows in `document_grants` (grantee) or `visibility = 'public'`, all in the same predicate, without changing callers.
- **State and archive guard:** only documents in the `ready` state that are not archived are included. A document being `processing`, `awaiting_subjects`, or `failed` is invisible to search even if the subject matches.
- **Subject scope:** the filter is restricted to the `subject_id`s the agent passes; chunks from the learner's documents in other subjects are not accessible within this tool call.
- **Empty result is not an error:** if no readable, ready, non-archived documents exist for the requested subjects, `search` returns an empty list. The agent maps this to the US-10 message ("There are no active documents in this conversation's subjects") without surfacing an error to the learner.

This design implements PRD D4: the LLM is never the access boundary; access is decided by one rule, `can_read(user, document)`, enforced in the RAG MCP server with the user's forwarded token.

## Iterative HNSW Search and Exact-Search Fallback

A learner's documents represent a small fraction of all chunks in the database. A standard post-filtered HNSW search can return fewer than `k` results because the index graph visits neighbours that fail the filter before finding enough passing ones.

The server uses **pgvector ≥ 0.8 iterative index scans** (`hnsw.iterative_scan`) to work around this: rather than a single pass that may exhaust the graph without finding `k` filtered results, the scan expands its search frontier iteratively until it either finds `k` matching chunks or determines that none more exist.

For learners with a very small readable set (e.g. one or two newly uploaded documents), the iterative scan may still be less efficient than a brute-force search. In that case the server falls back to **exact search** directly over the subset of chunk rows that pass the SQL filter, bypassing the HNSW index entirely. Recall under a selective filter is a Release 1 milestone (M1) evaluation target.

The `filtered_retrieval_recall_at_5` evaluation in `backend/evals/thresholds.yaml` requires ≥ 0.95 recall for a learner holding fewer than 1% of all chunks in the database (PRD §9.10 risk mitigation for "Filtered search returns too few results").

## Retriever Port in the Tutoring Module

The tutoring module never reads the `chunks` or `documents` tables directly. Its domain rule, expressed in the `tutoring` README, is:

> Never reads chunk tables: retrieval goes through the `Retriever` port (MCP client adapter).

`tutoring.ports.Retriever` is an abstract base class (ABC) that declares the retrieval contract the application layer depends on. The concrete implementation lives in `tutoring.adapters` as an MCP client adapter that:

1. Attaches the forwarded JWT to each outgoing HTTP request to the MCP server.
2. Calls the `search` tool with the thread's `subject_ids` and the user's query.
3. Returns the ranked chunk list to the application service (`AskService`).

This indirection maintains the access-control boundary in the code structure, as stated in the project-structure design spec (§5):

> The agent never reads chunk tables: `tutoring`'s `Retriever` port is implemented by an MCP client adapter that calls `apps/mcp_server`, which calls `knowledge.application.SearchService`. This keeps the access boundary of PRD §9.3 in the code structure.

The `mcp` library is an external vendor SDK; the import-linter contracts (contract 4 in §6) enforce that it is used only from `adapters` or `apps` packages, never from module domains or ports.

## Request Flow

The diagram below shows how a retrieval request travels from the agent through to the database during the `search` step of the ask path.

```mermaid
sequenceDiagram
    participant Agent as Smart Tutor Agent
    participant Adapter as tutoring.adapters<br/>(MCP client)
    participant MCP as RAG MCP Server
    participant KA as knowledge.application<br/>SearchService
    participant DB as PostgreSQL + pgvector

    Agent->>Adapter: Retriever.search(query, subject_ids, k)
    Adapter->>MCP: POST /mcp  search(query, subject_ids, k)<br/>Authorization: Bearer <token>
    MCP->>MCP: Validate JWT, extract sub
    MCP->>KA: search(sub, query, subject_ids, k)
    KA->>DB: Embed query; HNSW iterative scan<br/>filtered by can_read SQL predicate
    DB-->>KA: Ranked chunks with scores
    KA-->>MCP: ChunkResult list
    MCP-->>Adapter: Tool response (chunks + citations)
    Adapter-->>Agent: Ranked chunks
```

*Retrieval flow: the agent's Retriever port adapter calls the MCP server, which validates the JWT and delegates to `knowledge.application.SearchService` for the filtered vector search.*

## Architecture Invariant

The agent→MCP→knowledge chain is the **enforced access boundary** for chunk data. The spec (§5) makes this explicit: chunk tables are read only by the `knowledge` module. No other module — including `tutoring`, `graph`, or `reports` — may import `knowledge.domain` or query chunk tables directly; they must go through `knowledge.application` or the `Retriever` port. The import-linter contracts enforce this rule in CI on every push.

## Configuration and Deployment

| Item | Value |
|---|---|
| Transport | `streamable-http` |
| Address | `0.0.0.0:8000/mcp` |
| MCP library | `mcp >= 2.2` (`MCPServer` class; `host`/`port` passed to `run()`) |
| Cluster visibility | `ClusterIP`; `NetworkPolicy` allows only agent → MCP |
| Keycloak client | `rag-mcp`; audience mapper adds `rag-mcp` to access tokens |
| pgvector requirement | ≥ 0.8 for `hnsw.iterative_scan` |
| Docker build target | `mcp` (no `[ingest]` or `[eval]` extras) |

## Related Pages

- [Module and Layer Rules](../architecture/module-layer-rules.md) — import-linter contracts that enforce the chunk-table boundary
- [Access Control](../concepts/access-control.md) — `can_read` rule and visibility model
- [Keycloak Auth](keycloak-auth.md) — JWT validation, JWKS, and audience configuration
- [Ask Flow](../workflows/ask-flow.md) — how the agent uses `search` within the LangGraph ask path
