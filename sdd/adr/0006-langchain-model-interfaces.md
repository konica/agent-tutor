# 0006. LangChain model interfaces are the model ports; `init_chat_model` builds them

- Status: accepted
- Date: 2026-10-03

## Context

The agent is built with LangChain and LangGraph (PRD §9.12). PRD §9.15 planned our own `ChatModel` and `EmbeddingModel` ports with Bedrock adapters behind a `ModelFactory`. LangChain already provides that abstraction: `BaseChatModel` (`invoke`, `astream`, `bind_tools`, `with_structured_output`, `usage_metadata`) and `Embeddings`, with `init_chat_model` choosing the provider class from configuration. A second, hand-written abstraction would have to re-implement message mapping, streaming, tool calls, structured output, and LangSmith tracing, and LangGraph nodes and prebuilt agents could not use it.

The M0 check (wayfinder ticket #26) through LangChain found:

- `ChatBedrockConverse` (provider `bedrock_converse`) streams text and tool calls for Nova 2 Lite and answers from tool results; usage arrives in `usage_metadata`, and its `input_tokens` already include cached prompt tokens (`input_token_details.cache_read` / `cache_creation`), so usage matches Bedrock's totals.
- `with_structured_output` forces the schema's tool only when the class lists the model as supporting forced tool choice. langchain-aws 1.8 lists Nova but not Qwen3, although Bedrock accepts a forced tool choice for Qwen3.
- `BedrockEmbeddings` calls Nova Multimodal Embeddings synchronously (1024 dimensions), but sends `GENERIC_INDEX` for queries too, uses `truncationMode: END` (silently drops the end of long text), and its `aembed_documents` routes every document through `aembed_query`.
- Prompt caching: a `{"cachePoint": {"type": "default"}}` block after the system text. The `us.` profile may route consecutive calls to different regions, so a cache read is likely but not guaranteed.

## Decision

- Business code depends on `langchain_core`'s `BaseChatModel` and `Embeddings`; there are no hand-written model ports. `langchain_core` is allowed in every layer; provider packages (`langchain_aws`, `boto3`) stay in `adapters` (import-linter).
- `ModelFactory.chat(role)` returns `init_chat_model(model_id, model_provider=..., region_name=..., config=<botocore retries>, **params)` from `Settings.models`; switching a model or provider is configuration.
- The judge's configuration sets `supports_tool_choice_values: ["auto", "any", "tool"]` so `with_structured_output` forces the schema tool on Qwen3.
- `ModelFactory.embedding()` returns `NovaEmbeddings`, a small `BedrockEmbeddings` subclass: `GENERIC_INDEX` for documents, `TEXT_RETRIEVAL` for queries, `truncationMode: NONE`, and concurrent `aembed_documents` that stay documents.
- Usage is read with `TokenUsage.from_usage_metadata(message.usage_metadata)`.
- Unit tests use LangChain fakes (`GenericFakeChatModel` with `bind_tools`, `DeterministicFakeEmbedding`) from `tests/fakes/`.

## Consequences

- LangGraph nodes, `create_agent`, tools, and LangSmith tracing work with the factory's models directly; traces show model, messages, tool calls, and tokens.
- `NovaEmbeddings` overrides a private `BedrockEmbeddings` method; `make bedrock-check` (pytest marker `bedrock`) must pass after any langchain-aws upgrade, and the subclass goes away once langchain-aws supports embedding purposes.
- Embedding calls report no token usage through `Embeddings` (Bedrock sends it only in the `x-amzn-bedrock-input-token-count` header). Recording embedding tokens for document processing (PRD §8) needs a decision in M1: read the header in `NovaEmbeddings`, or estimate.
- Quotas that bound ingestion (us-east-1, 2026-10-03): Nova embeddings 2,000 requests/min on demand (not adjustable); Nova 2 Lite cross-region 2,000 requests/min and 8M tokens/min; Qwen3 32B 10,000 requests/min.
- Supersedes the `ChatModel` / `EmbeddingModel` port design in PRD §9.15 (v2.3).
