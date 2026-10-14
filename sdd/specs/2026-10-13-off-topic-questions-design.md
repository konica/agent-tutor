# Off-topic questions

| | |
|---|---|
| **Status** | Draft for PO review, 2026-10-13 |
| **Date** | 2026-10-13 |
| **Owner** | Thao Dinh (PO) |
| **Research** | `sdd/reviews/2026-10-13-off-topic-model-research.md` (model choice, CPU probe, ONNX spike) |
| **Applies to** | `backend/src/smart_tutor/apps/agent/` (graph, new node, server), `tutoring` (new port, adapter, decline message), `shared/config.py`, `backend/Dockerfile` (agent target), `backend/pyproject.toml` (extras, import contracts), `backend/models/topic_check/`, `backend/evals/` (dataset, generator, training, evaluators), `web/src/api/chat.ts` and the chat page tests, `deploy/` (enable flag), `sdd/prd.md` (D5, US-5, §9.2, §9.6, §10.1, glossary), `CONTEXT.md`, new ADR 0020 |

## 1. Problem

Every question searches the learner's documents before anything else (PRD D5, §9.2 step 1). An off-topic question, such as "tell me a joke" or "what's the weather tomorrow?", still searches all of the learner's documents. The answer model then improvises over unrelated chunks.

The product owner says Smart Tutor covers **education and research** only. It helps learners understand their papers, books, magazines, and news articles, and it should **politely reject** an off-topic question **without searching**.

## 2. Goal and success criteria

An off-topic question gets one polite decline, without a search and without an answer-model call. Every other question behaves as today.

1. At most **1%** of real study questions are declined as off-topic, and at least **95%** of off-topic questions are declined (`topic_check` eval, §6.3).
2. An off-topic turn makes no MCP `search` call and no answer-model call, and adds nothing to Documents used.
3. The check adds at most **300 ms** p95 before the first token on the on-premise host (t3.large), and works within the agent's 512 MiB container limit.
4. If the check fails or times out, the question is treated as on-topic (fail open), and the answer behaves exactly as today.
5. Question text stays in our infrastructure: the classifier runs in the agent process.
6. The classifier sits behind a port, so another decision model can replace SetFit through configuration, with the agent code unchanged. The product owner expects to try TypeSafe's Jev once there is an API key (§5.4).

**Out of scope:** the decline log row for `off_topic` (the log doesn't exist yet; #14 adds it, see §6.4). Also out of scope: prompt-attack screening (#197, #199) and any other language than English.

## 3. What is on-topic

The classifier follows this policy. The generator (§6.1) and human review use it to label data.

**On-topic.** Anything a learner asks in order to study, understand, or research:

| Kind | Examples |
|---|---|
| A concept in any subject | "Explain photosynthesis", "How do I differentiate x² sin x?" Edge subjects count: cooking, sports, finance, security, art. |
| A question about their documents | "What does chapter 3 say about inflation?", "Summarize the paper I uploaded" |
| A follow-up | "Explain that more simply", "And its limitations?", "Thanks! Can you give an example?" |
| A study task on their material | "Quiz me on this chapter", "Help me plan my study week for the biology exam" |

**Off-topic.** Requests that have nothing to do with learning:

| Kind | Examples |
|---|---|
| Greetings and chit-chat | "hi", "how are you?" |
| Questions about the tutor itself | "What can you do?" The decline message already answers this. |
| Entertainment | Jokes, stories, poems, role-play |
| Personal tasks | Write an email, plan a trip, book a flight, recommend a restaurant, fix the bug in my app |
| Live information | Weather, prices, "who will win tonight?" |

**When unsure, call it on-topic.** An on-topic question the documents don't cover still searches and gets the US-5 decline, as today.

## 4. Behaviour

### 4.1 The ask graph

```
START → topic_check ─(off_topic)──────────────→ END    decline "off_topic"
                    └─(on_topic, off, or error)→ search → answer → END
```

`topic_check` runs first in every conversation, limited or not, and before the no-documents check. A learner with no readable documents who asks an off-topic question gets the off-topic decline.

### 4.2 The off-topic decline

- **New decline code:** `off_topic`. Its message is a constant `OFF_TOPIC_DECLINE` in `tutoring/application/answer.py`, next to `LIMITED_DECLINE`:

  > I'm Smart Tutor: I help you study and research the papers, books, magazines, and news articles in your library, so I can't help with that. Ask me about your documents or a topic you're learning.

- **Same handling as the existing declines:**
  - The turn is kept in `thread_turns` with its code and message.
  - It adds nothing to Documents used and can be rated.
  - Its message stands in for the answer in later turns' history (`turn.py`).
- **The web shows the message with no action button.** `ChatPage.tsx` already renders an unknown code this way (lines 992–996). The `DeclineCode` union in `web/src/api/chat.ts` gains `"off_topic"`, and a test pins the rendering.
- **No migration:** `decline_code` is free text in the database.

### 4.3 Fail open

Each of these lets the question through to `search`:
- the classifier raises an error;
- the classifier takes longer than `timeout_ms` (default 250);
- the check is turned off (`provider = "off"`).

Errors and timeouts are logged without the question text. The node's state records `topic_check: {"verdict": "error"}`, so traces show it.

## 5. Design

### 5.1 Port: `TopicClassifier` (`tutoring/ports/topic_classifier.py`)

```python
@dataclass(frozen=True)
class TopicVerdict:
    p_off_topic: float      # 0..1
    model: str              # e.g. "setfit-bge-small-int8@2026-10-20", for traces

class TopicClassifier(ABC):
    @abstractmethod
    async def classify(self, question: str, history: Sequence[HistoryTurn]) -> TopicVerdict: ...
```

- The port takes the whole capped history, not a pre-built string, so each adapter can format context its own way. A Jev adapter would send the history as state.
- The port is re-exported from `tutoring/application/__init__.py`, like `Retriever`.
- An application function, `is_off_topic(verdict, threshold) -> bool`, holds the decision. It returns true only when `p_off_topic >= threshold`.

### 5.2 Adapter: `OnnxSetFitTopicClassifier` (`tutoring/adapters/onnx_topic_classifier.py`)

**Loading.** At startup the adapter loads a model directory:

| File | Content |
|---|---|
| `body.onnx` | int8 sentence-transformer body, dynamic shapes |
| `tokenizer.json` | the body's tokenizer |
| `head.npz` | logistic-regression `coef` and `intercept` |
| `manifest.json` | model version, base model, pooling (`cls`/`mean`), max tokens, tuned threshold, training-data version |

It runs with `onnxruntime` (2 intra-op threads), `tokenizers`, and numpy only. There is no torch in the agent image.

**Scoring** (inference runs in `asyncio.to_thread`):

1. P(off) of the **current question alone**.
2. If there is a previous turn, P(off) of **"Previous question: … \nQuestion: …"**. The previous question is the last turn's question, whatever its outcome.
3. The verdict is the **minimum** of the two.

Why the minimum:
- A terse follow-up ("why does it need to be fed every day?") is rescued by its context; the probe saw 0.68 drop to 0.10.
- An off-topic previous turn ("tell me a joke") can't drag a real study question to off-topic, because the question alone still scores on-topic.
- It costs two inferences, about 10 ms in the spike.

**Library boundary.** The adapter is the only place `onnxruntime` and `tokenizers` are imported. An import-linter contract enforces this, copied from the pypdf contract.

### 5.3 Node and wiring

- **Node** `apps/agent/nodes/topic_check.py`: `topic_check_node(classifier: TopicClassifier | None, threshold: float, timeout_ms: int)`.
  - `None` means off.
  - It writes `topic_check: {"p_off_topic", "model", "verdict"}` to `AskState`, plus `decline: "off_topic"` when the verdict is off-topic.
  - `DeclineCode` gains `"off_topic"`, and `DECLINE_MESSAGES` maps it.
- **Graph:** `build_graph(..., topic_classifier=None, topic_threshold=0.5, topic_timeout_ms=250)` adds the node and a conditional edge. The keyword defaults keep the existing callers (`server.py`, `evals/targets.py`, tests) working unchanged.
- **Server:**
  - `answer_events` reads `decline` from **any** node's update, not only `answer`'s, so the off-topic decline reaches the SSE stream.
  - The module docstring lists the new code.
  - `lifespan` builds the classifier once from settings: `None` when off.
- **Tracing:** the node is traced automatically as a LangGraph chain span, with `topic_check` in its output. `AskTrace.finish` already records the decline code on the root span. No question text is added anywhere new.

### 5.4 Configuration and swapping the model

`Settings.topic_check: TopicCheckConfig`, set through env `SMART_TUTOR_TOPIC_CHECK__*`:

| Field | Default | Meaning |
|---|---|---|
| `provider` | `"off"` | `"off"` or `"setfit"`. Later `"jev"`. |
| `model_dir` | `models/topic_check` | SetFit model directory, relative to the working directory: `/app/models/topic_check` in the image, `backend/models/topic_check` on the host and in CI |
| `threshold` | `None` | `None` means the manifest's tuned threshold. A number overrides it. |
| `timeout_ms` | `250` | Fail-open timeout |

**Swapping in Jev later** means:
1. A `JevTopicClassifier` adapter.
2. A `"jev"` provider value.
3. Its API key in Secrets Manager (ADR 0013).
4. A threshold set on the same eval (§8).

The graph, node, port, and web are unchanged. **Precondition:** Jev is a third-party hosted API, so turning it on sends learners' question text outside our infrastructure. That is against today's privacy invariant (AGENTS.md "Privacy", PRD §11), so it needs a PRD decision and an ADR before it is enabled. The swap is a configuration change once that is decided.

### 5.5 Packaging

- **Dependencies:**
  - A new extra `topic`: `onnxruntime`, `tokenizers`, `numpy`.
  - A new extra `train`: `setfit`, CPU `torch`, `onnx`, `onnxruntime`. It is used only by the training command, never by an image.
- **Image:** `backend/Dockerfile` gains a `deps-agent` stage (`uv sync --frozen --no-dev --extra topic`), used only by the `agent` target, which copies `backend/models/topic_check/` to `/app/models/topic_check`. The api and mcp images are unchanged (structure spec S1: "Each Docker build target installs only the extras it needs").
- **Model artifact:** committed to git at `backend/models/topic_check/`, about 32 MB int8 for bge-small, or about 23 MB for MiniLM-L6.
  - A retrain replaces the files in a PR that also records the eval results.
  - We use plain git, not Git LFS (LFS bandwidth quotas would be spent by every CI checkout), and not S3 (the agent has no bucket or S3 grant today).
  - Revisit if more than about five versions pile up in history.
- **Memory:** the spike measured 108 MiB RSS for a process with the int8 model loaded. The agent's limit stays 512 MiB unless the implementation measures the full agent above about 450 MiB. In that case `mem_limit` (on-premise Compose) and the Helm agent limits go to 768 MiB in the same PR.

## 6. Data, training, and evaluation

### 6.1 Labeled questions

- **Generator:** `evals/generators/topic_check.py`. The judge model drafts questions per kind from §3. It follows the pattern of `generators/ask.py`: seeded drafts and `with_structured_output`.
  - On-topic kinds cover many subjects, including the edge subjects, document-style questions, follow-ups (with a previous question), and study tasks.
  - Off-topic kinds are greetings, questions about the tutor, entertainment, personal tasks, and live info.
  - A borderline set targets the boundary: study tasks versus personal tasks, and a news article in the library versus live news.
- **Review:** drafts go through the existing review flow (`evals.generate topic_check`, then the `topic_check-candidates` annotation queue, `review.py`). Only accepted examples are used.
- **Train/eval split:** each accepted example goes to **train** or **eval** by a stable hash of its normalized question (70/30), so the two never overlap. The eval holds at least **300 on-topic** and **200 off-topic** questions (§6.3). Off-topic rows from GovTech's MIT dataset (`gabrielchua/off-topic`) may join **train** only.
- **Hand-written seeds:** the probe's questions (research note) go into `evals/datasets/topic_check.yaml` as the hand-written examples and the smoke split.

### 6.2 Training

- **Command:** `python -m evals.topic_check.train` (with the `train` extra), wrapped as `make topic-check-train`. It:
  1. trains SetFit on the train split;
  2. picks the threshold on a held-out slice of train: the lowest threshold that keeps false rejections ≤ 0.5%, which leaves headroom for the 1% target;
  3. exports the body to ONNX with dynamic shapes and quantizes it to int8;
  4. writes the model directory and `manifest.json`;
  5. checks that the ONNX probabilities match SetFit's within 0.02 on the held-out slice.
- **Base model:** `BAAI/bge-small-en-v1.5` first, or `sentence-transformers/all-MiniLM-L6-v2` if it scores as well. The run that commits a model records which one won.

### 6.3 Evaluators and gate

- **New suite `topic_check`** on dataset `topic_check`. Its target runs only the classifier: no Bedrock, no MCP.
  - `topic_check.false_rejections`: on-topic examples declined. `max: 0.01`.
  - `topic_check.off_topic_caught`: off-topic examples declined. `min: 0.95`.
  - Both go in `thresholds.yaml` under `release_1` in PR 2, together with the first model (§7). Before that the suite has no model to run.
  - With 300 on-topic examples, the rule of three means ≤1% is shown only with zero errors. That is accepted; a larger set can come later.
- **Changes to existing evaluators:**
  - **`search_step_ran`:** an example whose run declined `off_topic` and made no search scores n/a, not 0. This matches PRD §10.1's wording "every answered turn".
  - **`decline_correctness`:** `wrongly_declined` already counts an `off_topic` decline of a covered question as a miss, so it stays.
- **`ask.yaml`:** a few off-topic examples with `outputs.off_topic: true`, so the end-to-end target shows the graph declines without searching.
- **Latency:** the p50/p95 of `topic_check` on the on-premise host under the running stack is measured once, by a small script, and recorded in the PR that enables the flag. It is not a CI gate, because CI hardware isn't the host.

### 6.4 Decline log (later)

When #14 builds the decline log, an off-topic decline writes a row with reason `off_topic`. PRD §9.6 gains the reason now, so #14 builds it in.

## 7. Rollout

1. **PR 1** (behaviour, flag off): port, adapter, node, graph, server, web, config, packaging, evaluators, generator, training command, PRD/ADR/CONTEXT updates. Tests use a fake classifier. No model is committed, and `provider` stays `off` everywhere.
2. **Data:** generate and review the labeled set; publish `topic_check` (train and eval).
3. **PR 2** (model, flag on):
   - train and commit `backend/models/topic_check/`;
   - the `topic_check` eval passes its thresholds;
   - latency is measured on the host;
   - `.env.example`, `deploy/on-premise/compose.yaml`, and the Helm agent values set `SMART_TUTOR_TOPIC_CHECK__PROVIDER=setfit`.

## 8. Testing

- **Unit (agent graph,** with `FakeTopicClassifier` in `tests/fakes/tutoring.py`):
  - off-topic → `decline == "off_topic"`, `FakeRetriever.calls == []`, and no model call;
  - on-topic → search and answer as today;
  - classifier error → search;
  - timeout → search;
  - `None` → search;
  - limited conversation → the off-topic decline still wins;
  - the graph's node set includes `topic_check` (`test_graph.py:115`).
- **Unit (server):** the SSE stream carries `decline {code: "off_topic", message}` then `done`, with no `delta` or `sources`.
- **Unit (`is_off_topic`, adapter scoring):**
  - the min-of-two rule, tested with a stubbed scorer;
  - manifest loading and threshold override;
  - an adapter test against a tiny randomly initialized ONNX fixture, built in the test with `onnx.helper` (`onnx` joins the `dev` group), so the real model isn't needed.
- **Import contracts:** `onnxruntime` and `tokenizers` only in `tutoring.adapters.onnx_topic_classifier`.
- **Evals unit tests:** `search_step_ran` n/a case, and the `topic_check` evaluators' scoring.
- **Web:** an `off_topic` decline renders its message with no action, both streamed and from history.

## 9. Documents to update

| Document | Change |
|---|---|
| `sdd/prd.md` | D5 becomes "A topic check runs first; on-topic questions always search; off-topic questions get the off-topic decline without a search." §9.2 gains step 0 "Topic check". US-5 gains an off-topic criterion (message, no action). §9.6 lists reason `off_topic`. §10.1 gains "Topic check: ≤1% false rejections / ≥95% off-topic caught". The glossary gains **Off-topic question** and **Topic check**. Version → v2.62. |
| ADR 0020 | "Off-topic questions are screened by a local SetFit classifier behind a swappable port". Covers why a trained classifier and not an LLM call, Jev, or GovTech's model (research note); ONNX without torch in the agent; the model committed to git; and the Jev privacy precondition. |
| `CONTEXT.md` | **Decline** widens to "a question the documents don't support, or an off-topic question". Adds **Off-topic question** and **Topic check**. |
| `backend/src/smart_tutor/tutoring/README.md` | The port and adapter. |
| `backend/evals/README.md` | The `topic_check` dataset, training command, and suite. |

## 10. Risks

- **Label policy drift.** The boundary in §3 is a product decision; the classifier learns whatever the reviewed data says. Borderline examples get explicit review.
- **Real learners phrase things differently from generated drafts.** 👎 ratings on off-topic declines (PRD §10.2) and, later, decline-log rows feed new training data.
- **History growth.** Each retrain adds about 30 MB to git history (§5.5).
- **English only**, like the rest of R1's evals.
