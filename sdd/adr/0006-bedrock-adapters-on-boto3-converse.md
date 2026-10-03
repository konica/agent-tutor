# 0006. Bedrock adapters call Converse and InvokeModel with boto3, traced with LangSmith

- Status: accepted
- Date: 2026-10-03

## Context

The `ChatModel` and `EmbeddingModel` ports (PRD §9.15) need Bedrock adapters: Nova 2 Lite for the agent, Qwen3 32B for the judge, Nova Multimodal Embeddings for chunks, summaries, subject names, and queries. The PRD's risk table assumed the M0 spike would go through LangChain's `ChatBedrockConverse`.

The M0 check (wayfinder ticket #26) found:

- Nova embeddings work with synchronous `InvokeModel` (`SINGLE_EMBEDDING`, 1024 dimensions); `langchain-aws` has no Nova embeddings class with `embeddingPurpose`, so that adapter is plain boto3 either way.
- With prompt caching on, Bedrock reports cached system-prompt tokens in `cacheReadInputTokens`/`cacheWriteInputTokens`, **not** in `inputTokens` (2 vs 2,052 in the check). The PRD requires learners' usage to match Bedrock's totals.
- Embedding calls report their input tokens only in the `x-amzn-bedrock-input-token-count` response header.
- Both Nova 2 Lite and Qwen3 accept a forced tool choice, so one structured-output path serves both roles.

## Decision

- `BedrockConverseChatModel` calls `converse` / `converse_stream` through boto3 (in a worker thread), mapping our `Message`s to Converse turns itself: alternating roles, tool results as `toolResult` blocks in a user turn, a `cachePoint` after the system prompt when `prompt_cache` is set.
- `structured()` forces a tool named after the Pydantic schema and validates its input; a missing or invalid payload raises `ModelOutputError`.
- `TokenUsage.input_tokens` = `inputTokens` + cache read + cache write; `EmbeddingModel` returns `Embeddings(vectors, usage)` with the header's token count.
- Every chat call is a LangSmith `llm` run (`langsmith.traceable`) with `usage_metadata`, so traces show model, messages, tool calls, and tokens without LangChain chat models.
- SDK errors become `ModelError` after the client's adaptive retries (4 attempts); callers never import botocore.

## Consequences

- No dependency on `langchain-aws` behavior for message mapping, usage, or caching; we own about 250 lines and their unit tests.
- LangGraph nodes call the ports directly; LangChain prebuilt agents that need a `BaseChatModel` are not used.
- `make bedrock-check` (pytest marker `bedrock`) re-verifies the real models after a model or SDK change.
- Quotas that bound ingestion (us-east-1, 2026-10-03): Nova embeddings 2,000 requests/min on demand (not adjustable); Nova 2 Lite cross-region 2,000 requests/min and 8M tokens/min; Qwen3 32B 10,000 requests/min. One worker at 8 concurrent embedding calls uses about 1,000 requests/min.
