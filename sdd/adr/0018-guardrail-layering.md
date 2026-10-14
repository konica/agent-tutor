# 0018. Guardrail layering: code checks, Guardrails AI for the output, Bedrock Guardrails for the question

- Status: accepted
- Date: 2026-10-13
- Note: issue #197 called this "ADR 0015" (the guardrail-layering ADR); 0015 was taken by conversation history.

## Context

US-6 asks the tutor to keep its scope, keep its system prompt private, and follow no instruction found in documents. The injection eval (#194) measures this, and #195 hardened the answer prompt. The prompt alone is not a guarantee, so the plan on #15 adds checks in code and a guard on the model's output.

Two facts shape the design:
- Document text is untrusted but must keep working. A security-course PDF about prompt injection is a normal document, so a chunk is never dropped for containing instructions.
- Privacy: no question, chunk, answer, or token may leave the process except to Bedrock (the model) and our own Phoenix (traces).

## Decision

Three layers.

1. **Code checks.** Chunks and the question go to the model as quoted data; the answer is capped; the agent has no tools that reach other learners' data. These exist already.
2. **Guardrails AI for output validation.** A Guardrails AI `AsyncGuard` of our own validators checks the streamed answer, behind a `Guard` port in `tutoring` (a question check and an answer check; `GuardrailsGuard` is the adapter). The first validator, `SystemPromptLeak`, trips on the system prompt's random per-process canary or on a run of 40 or more characters copied from the prompt (case and spacing ignored). The check runs on the accumulated text before each piece reaches the learner.
3. **Bedrock Guardrails prompt-attack filter as an optional screen of the question only** (#199). Guardrails AI's `DetectJailbreak`, measured as a local alternative (#200), tripped 1.1% of benign study questions and caught 1 of 18 seeds at its default threshold, missed the 300 ms p95, and needs about 2 GiB of agent memory, so it ships only as an optional extra in the `agent-jailbreak` image and Bedrock at LOW stays the screen of choice (ADR 0019).

A trip on any guard has one behavior (PRD D29): the stream ends with a `replace` event carrying the guard message, and the turn is kept as a decline with code `guard`. The reason (`guard_answer`, `guard_question`) goes to logs and traces only.

**Guardrails AI runs fully in process.**
- `settings.disable_tracing = True`. Otherwise its spans carry the validated text through our Phoenix tracer provider.
- Hub metrics are off: `HubTelemetry()._tracer = None` and `configure(allow_metrics_collection=False)`. Metrics default to on when there is no `~/.guardrailsrc`, and every `Guard()` re-reads that file, so only the tracer reset lasts.
- `history_max_length=1`, and the guard's history is cleared after each call, so it keeps no answer text.
- No remote inference and no hub calls.
- `guardrails-ai==0.11.0` is pinned, and a test pins this configuration.

**A guard that fails closes the turn.** If a check raises, the agent ends the turn with the `unavailable` error and the turn is not kept. An answer that was not checked never reaches the learner.

**Rejected: NeMo Guardrails for Release 1.** It is a second orchestration runtime next to LangGraph, it adds an LLM call per turn for self-check rails, and its jailbreak classifier needs a GPU NIM.

## Consequences

- The `guard` extra (+54 packages, about 270 MB in site-packages, including litellm, openai, and grpc) is installed only in the agent image, and in the `dev` group so tests import it. Measured, the agent image grows from 581 MB to 1.03 GB with the extra. Guardrails AI is imported only in `tutoring` adapters.
- A check costs about 0.56 ms fixed per call plus work that grows with the answer's length (Guardrails' own per-call handling, not just our scan), and the port checks all of the answer so far on every streamed piece. One maximum-length answer (about 6,000 characters in about 500 pieces) costs about 1.2 s of guard time over the stream; a typical answer (1,000 to 2,000 characters) about 0.1 to 0.2 s. Checks are CPU-bound, so one agent process saturates a core at roughly 15 to 20 long answers in flight.
- Follow-up option, not taken: check only a tail window (the newest piece plus about 2 x `LEAK_RUN` plus the canary length) or reduce Guardrails' per-call work. That changes the port's "all of the answer so far" contract and needs its own decision.
- Up to 39 characters of a leak can show before the replace, since a shorter run is not a leak. The web replaces the partial answer when the event arrives.
- A guard failure makes the turn fail with `unavailable`. The learner can ask again.
- The tripped turn counts toward the chat rate limits, adds no documents used, is never sent as history, and is not used for the learning record. `last_turns` and `history` skip `guard` turns.
- Later guards reuse the `replace` event. #198 reuses it for cleaned text.
- The question check is on the port and returns no trip for now; #199 wires a question screen.
