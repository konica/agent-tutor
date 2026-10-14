# 0019. The Bedrock question screen is optional, fails open, and stays off until its latency is solved

- Status: accepted
- Date: 2026-10-13
- Builds on: 0018 (layer 3, "an optional Bedrock Guardrails screen of the question only")

## Context

ADR 0018 left the question check on the `Guard` port returning no trip, and named issue #199 as the place to wire a Bedrock Guardrails prompt-attack filter. The screen sees the learner's question only, never chunks, history, or the system prompt (document text is quoted and checked, never blocked: PRD D28). The product has three limits on it:
- A false positive blocks a real study question. Learners study prompt injection, ML safety, and security, so a filter that trips on them is worse than none (target: at most 1% of benign study questions).
- Cost: at most 10% of an average turn.
- Latency: at most 300 ms added before the first token.

## Decision

1. **The screen is optional and off until measured.** `question_guard` is `off` or `bedrock` (SSM `question-guard`, default `off`). With `bedrock`, the agent needs `question_guardrail_id` and `question_guardrail_version` and refuses to start without them. A `screen` node runs before `search`. A trip follows PRD D29 with reason `guard_question`: the stream ends with the `replace` event, the turn is kept as a decline with code `guard`, and search and the model are not called.
2. **It fails open.** If ApplyGuardrail raises or takes longer than `question_guard_timeout_seconds` (1.0), the turn goes on unscreened and a content-free counter adds one.
3. **CDK owns the guardrail.** `<data_prefix>-question-screen`: the prompt-attack filter at strength LOW, input only, action BLOCK, Standard tier on the cross-region profile `us.guardrail.v1:0`. A retained guardrail version is re-published whenever a hash of the whole definition changes, so a changed definition never leaves agents on a stale snapshot. The agent's role may call `bedrock:ApplyGuardrail` on that guardrail and that profile only.
4. **Strength LOW, and the screen stays off in both modes.** See the measurements. A deployment turns it on by changing `question-guard` in `infra/smart_tutor_infra/stacks/config.py` after re-measuring (`docs/runbooks/on-premise-deploy.md`).

### Update (2026-10-14): on in both modes

The product owner turned the screen on in both modes: `question-guard` is `bedrock` in `infra/smart_tutor_infra/stacks/config.py`. The measurements below still hold, so each on-topic question waits about 0.4 to 0.45 s longer (p95) before the first token, against the 300 ms target. The product accepts that for 0% false positives and the obvious prompt attacks it stops before search. Decision 4's "stays off" and the latency paragraph below record the state on 2026-10-13. The options to revisit at the end can still replace the screen with a faster one.

### Measurements (2026-10-13)

`backend/evals/measure_question_screen.py` created a temporary Standard-tier guardrail per strength with the production definition, measured it, and deleted it. Data: 364 benign study questions (45 LLM security, 44 ML safety, 36 computer security, 27 Vietnamese, 14 long pasted excerpts of 543 to 737 characters, 7 of which quote attack phrasings) and the 18 prompt seeds of the injection taxonomy (#194). Document-embedded attacks are excluded, because the screen never sees chunks. Concurrency 4; client latency from GMT+7.

| Strength | False positives | Catch rate (18 seeds) | Guardrail processing p50/p95 | Client p50/p95 | Text units per question | Cost per question | Share of an average turn |
|---|---|---|---|---|---|---|---|
| LOW | 0/364 (0.0%) | 6/18 | 335/424 ms | 663/773 ms | 1.00 | $0.000150 | 8.9% |
| MEDIUM | 4/364 (1.1%) | 10/18 | 323/412 ms | 650/755 ms | 1.00 | $0.000150 | 8.9% |
| HIGH | 6/364 (1.6%) | 11/18 | 334/450 ms | 657/786 ms | 1.00 | $0.000150 | 8.9% |

- LOW is the only strength at or under 1% false positives, in this run and in the earlier one (350 benign: LOW 0, MEDIUM 3, HIGH 5). MEDIUM and HIGH tripped on questions such as "How is a jailbreak evaluated automatically: which judge model and which rubric does the benchmark use?" and "Can you break down the prompt template shown in the appendix, part by part?". None of the 14 long excerpts tripped at any strength.
- At LOW the screen caught 5 of 7 seeds in the five true prompt-attack categories (instruction override, system-prompt extraction, role-play jailbreak, obfuscation, multi-turn escalation) plus the denial-of-wallet seed. It caught none of citation spoofing, other users' data, output links, scope smuggling, and subject manipulation: those ask for things the code checks already refuse, and are not prompt attacks in Bedrock's sense. The catch-rate gate is `question_screen.catch_rate` at least 0.30.
- The cost is 1 text unit at $0.15 per 1,000 = $0.00015 per question, against an average turn of $0.00169 (2,652 input and 297 output tokens of Nova 2 Lite, the mean of 16 local `ask` traces, at $0.33 and $2.75 per million tokens).
- **Latency misses the target.** Bedrock's own processing p95 is about 410 to 450 ms at every strength, before network time, so the added wait before the first token exceeds 300 ms wherever the caller is. False positives and cost pass; latency does not, so the screen stays off.

## Why it fails open when the output guard fails closed

ADR 0018's output guard closes the turn when it raises, because an answer that was not checked could leak the system prompt to the learner. An unscreened question cannot do that by itself: the model still sees it as quoted data under the system prompt, the code checks run, and the output guard still checks the answer. A screen outage that closed every turn would take the tutor down for a filter that, at LOW, catches 6 of 18 seeds. So the screen is one more layer that may be missing for a moment, and the counter shows how often.

## Other choices

- **Cross-region inference.** The Standard tier requires it. The profile `us.guardrail.v1:0` can route the question to us-east-1, us-east-2, or us-west-2, so the question leaves us-east-1 but stays in AWS's US geography. Questions already go to Bedrock in us-east-1 for the answer, and Bedrock is the privacy boundary for questions (ADR 0018), so the boundary is the same provider and geography. The agent's IAM names the profile in those three regions.
- **boto3, not LangChain.** LangChain has no standalone wrapper for ApplyGuardrail (its Bedrock chat models take a guardrail in the model call, which would send the chunks and history too, and would not stop search). `BedrockQuestionScreen` calls `apply_guardrail` with the question as the only content, source INPUT, with the boto3 `bedrock-runtime` client in a worker thread, one retry, and short timeouts (`SCREEN_BOTO_CONFIG`).
- **The counter is a CloudWatch metric.** `QuestionScreenFailures` in the namespace `SmartTutor/Agent`, dimension `Deployment`, with `cloudwatch:PutMetricData` limited to that namespace. The agent has no database (reads go through the API and MCP), and Phoenix traces are sampled, so a count there would miss failures. The put goes off the request on a background task and cannot delay a turn. The counter carries no user id, question, or token.

## Consequences

- The screen costs nothing while off: no guardrail call, no metric, no added latency.
- The guardrail, its version, and the three SSM parameters exist in both modes even while the screen is off, so turning it on is a settings change, not an infrastructure project.
- A fail-open screen is not a security boundary. It lowers the rate of obvious prompt attacks that reach the model; the code checks and the output guard carry the guarantees.
- A tripped turn behaves like any guard trip (D29): it counts toward the chat rate limits, adds no documents used, is never sent as history, and is not used for the learning record.

## Options to revisit (not built)

- Run the screen concurrently with search and discard the search on a trip. This hides most of the latency but calls search for a question that was tripped, which #199 rules out.
- The Classic tier: lower latency, but no prompt-leakage detection and only English, French, and Spanish (the benign set has Vietnamese questions).
- Bedrock's newer per-check API (`InvokeGuardrailChecks`, prompt-attack check at $0.08 per 1,000 text units), once it is measured.
- A local classifier, such as Guardrails AI's `DetectJailbreak` (#200): no network time, but a model in the agent image.
