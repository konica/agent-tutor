# 0020. Off-topic questions are screened by a local SetFit classifier behind a swappable port

- Status: accepted
- Date: 2026-10-13
- Supersedes: PRD D5's "Search always runs first … off-topic and uncovered questions get the same friendly decline"

## Context

Every question searched all of the learner's documents first (D5), so "tell me a joke" ran a search and the answer
model improvised over unrelated chunks. The product owner wants Smart Tutor to cover education and research only and
to decline off-topic questions politely without searching, with an open-source decision model "like Jev", and the
option to switch to TypeSafe's Jev later. The default on-premise host is one t3.large (2 vCPU, 8 GB, no GPU), and the
agent container is capped at 512 MiB (ADR 0012).

The topic check is a fixed pre-search step that decides scope. It is separate from ADR 0018's guard layers, which check
the answer and, with ADR 0019's optional question screen (#199), screen the question for prompt attacks. It runs
before that question screen: the local check takes milliseconds, so an off-topic question never costs a Bedrock call.
It reuses the same pattern: a `tutoring` port, an agent-only extra, and an import-linter contract.

## Decision

- A `topic_check` graph step runs before `search` and is a fixed step, not a model's choice. Off-topic means the
  classifier's P(off-topic) is at or above a threshold tuned with the model. The verdict is the lower of the question
  alone and the question with the previous question.
- The check sits behind a `TopicClassifier` port in `tutoring`. Its first adapter runs a **SetFit** model
  (sentence-transformer body plus logistic head) trained on our own reviewed messages, exported to **int8 ONNX** and run
  with onnxruntime, `tokenizers`, and numpy in the agent process. There is no torch in any image, and only the agent
  image gets the `topic` extra.
- It **fails open**: an error, a timeout (250 ms), or the check being off lets the question go on to search.
- The model is committed to git in `backend/models/topic_check/` (about 30 MB) and copied into the agent image.
- The check stays off until the `topic_check` eval passes: at most 1% of study questions declined and at least 95% of
  off-topic ones declined.

## Alternatives rejected (research note `sdd/reviews/2026-10-13-off-topic-model-research.md`)

- **Jev itself:** hosted and closed, so learners' question text would leave our infrastructure.
- **GovTech's off-topic classifier as shipped:** its export pads to 1,024 tokens (about 2.4 s per question on 2 CPU
  threads), and zero-shot it declined real study questions for our broad scope.
- **NemoGuard-TopicControl, Llama Guard, Qwen3Guard, ShieldGemma, Granite Guardian:** need a GPU or can't express a
  custom scope.
- **An LLM call (Nova Micro):** works, but costs a model call per turn; it remains the eval baseline.
- **Bedrock Guardrails denied topics:** a blocklist can't express "only education and research".

## Consequences

- Swapping in another decision model (Jev) means a new adapter, a provider value, and its key in Secrets Manager.
  Because Jev would send question text to a third party, it needs a PRD privacy decision before it is enabled.
- Data upkeep: the model learns the boundary from human-reviewed messages, and each retrain adds about 30 MB to git
  history. Revisit storage after about five versions.
- One more step per turn: about 5–10 ms on CPU in the spike, to be measured on the host before enabling.
