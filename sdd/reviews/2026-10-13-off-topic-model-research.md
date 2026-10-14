# Off-topic question check: which open-source decision model?

- Date: 2026-10-13
- Status: research note with a CPU probe (no decision recorded yet)
- Related: #197 (guard port in `tutoring`), #199 (Bedrock Guardrails prompt-attack screen, `question_guard` flag)

## Question

Which open-source "decision model" should Smart Tutor use to classify a learner's chat question as on-topic or off-topic **before** retrieval? The product owner asked for "an OSS decision model like Jev".

## Answer

"Jev" is almost certainly **TypeSafe AI's Jev**, a hosted, closed-weight "System One" decision model that launched in September 2026 and returns typed decisions with probabilities instead of text. Jev itself can't be used: it is a third-party API with no published weights, no Bedrock listing, and no stated data-handling terms, so question text would leave our infrastructure. The open-source models that copy Jev's approach are 2–5 weeks old. Most are 4–12B LLM fine-tunes that need a GPU. The two small encoder-based ones (Von, Laya) score near the bottom of JevBench and ship calibration fitted to that benchmark.

The best-fitting off-the-shelf open model is GovTech's off-topic classifier **`govtech/jina-embeddings-v2-small-en-off-topic`** (33M parameters, built for exactly this pair task). A probe on our own questions (below) shows it **doesn't work as shipped**:
- Its ONNX export has a fixed 1024-token shape, so a question takes **about 2.4 s on 2 CPU threads**, about 8× our budget.
- Zero-shot, it **rejects real study questions**. A cookbook question scored P(off-topic) 0.95 even with cooking named in the scope.

**Recommendation:** build our own small open-source decision model using GovTech's published method: an LLM drafts labeled on-topic and off-topic questions for *our* scope, and humans review them.
- **Primary: SetFit** (Apache-2.0) on a small sentence-transformer, `bge-small-en-v1.5` or `all-MiniLM-L6-v2`, run in-process on CPU. The encoder takes **about 40–80 ms per question** on 2 threads, measured below.
- **Training data:** the labeled set we need for the eval anyway. GovTech's MIT dataset of 2.6M rows can add off-topic negatives.
- **Placement:** a fail-open `topic_check` node before `search`, fed the previous question plus the current one.
- **Option with no training:** **gpt-oss-safeguard-20b on Bedrock**, which has open weights, follows a written policy, and runs on-demand in us-east-1. It is a reasoning model, so measure its latency against the budget first. It is also useful for drafting labels.
- **Baseline:** a small Bedrock LLM with structured output (Nova Micro/Lite), which every candidate must beat.

## What "Jev" most likely refers to

**Most likely: TypeSafe AI's Jev.**
- TypeSafe's launch post introduces "System One Models" as "a new class of frontier models built to make fast, structured decisions that software can use directly". Jev is the first one: unstructured state in, typed probabilistic decisions out, 70–500 ms end to end. The post names guardrailing prompts and detecting jailbreaks as use cases. [TypeSafe blog]
- The owner's wording, "decision model", is TypeSafe's own category name. An ecosystem of "open-source Jev alternatives" appeared within days of the launch, which matches "an OSS decision model like Jev". Examples: DataCamp's list dated 2026-09-23, a benchmark called JevBench, and projects named Kev, Von, Nimble, JevK5, Laya, and OpenJev. [DataCamp; BenchLM JevBench]
- Jev is closed. The launch post and homepage say nothing about weights, a license, or deployment options. Access is through an early-access waitlist and API, and the service is "currently based" on the US West Coast. OpenRouter also proxies it as `typesafe/jev-1.13`. [TypeSafe blog; TypeSafe home; OpenRouter docs]
- Date note: the TypeSafe blog page currently shows 2026-10-12, but third-party coverage of the launch starts mid-September 2026 (DataCamp 2026-09-23; Kev mentions a Kev-9B fine-tune dated 2026-09-30).

**Less likely: the GovTech "JEV2" reading** (jina-embeddings-v2-small-en off-topic classifier). I found no source that calls these models "Jev" or "JEV2". GovTech calls them "Off Topic Guardrail" classifiers, and the model id abbreviates the base model as `jina-embeddings-v2`. The coincidence is worth stating, because this model is the best fit for our constraints either way (see the recommendation). No other plausible reading turned up.

## Constraints

- **Task:** binary on-topic/off-topic check before search. Scope is broad: anything a learner wants to study, questions about their documents, and follow-ups. Off-topic means chit-chat, jokes, stories, role-play, personal tasks, and live info.
- **Targets:** ≤1% false rejections of real study questions and ≥95% of off-topic questions caught. When unsure, treat the question as on-topic.
- **Follow-ups:** the check needs the previous turn. `AskState.history` already carries earlier question and answer text (ADR 0015).
- **Deployment:** the default on-premise mode is one t3.large (2 vCPU, 8 GB, no GPU, burstable CPU credits) shared by the whole Compose stack (ADR 0012). The added latency budget is about 300 ms before the first token. Native-cloud runs on EKS.
- **Privacy:** question text stays in our infrastructure or AWS, so third-party APIs are out.
- **Code:** LangChain/LangGraph. Project rule: use LangChain interfaces, with no custom wrappers where one exists.

## Candidates compared

"CPU on 2 vCPU" uses only published numbers; anything else is marked as unmeasured.

| Candidate | What it is | Input → output | License / commercial | Size | CPU feasibility (published) | Serving | Multi-turn | Reported accuracy | Maintenance |
|---|---|---|---|---|---|---|---|---|---|
| **TypeSafe Jev** | Hosted "System One" decision model | State + typed questions → answers with probabilities | Closed; terms not published on the launch page | Not disclosed | n/a (API only; 70–500 ms claimed) | TypeSafe API or OpenRouter | Not stated | JevBench v1.5.4: rank 3 (72.13) | Early access, launched Sep 2026 |
| **GovTech jina-v2-small off-topic** | Fine-tuned pair classifier: shared jina-v2-small encoder, adapters, cross-attention, MLP head | (system prompt, user prompt) → softmax [on, off]; label 1 = off-topic | Repo LICENSE is MIT plus GovTech exclusions (logos, crest, third-party material), governed by Singapore law. Base model Apache-2.0. Commercial use OK | 33M params; repo 271 MB (ONNX + safetensors); max 1024 tokens | No CPU numbers published. GPU T4: 0.027 s/pair. Probe: 2.4 s p50 on 2 laptop threads (ONNX input fixed at 1024 tokens) | `onnxruntime` + `transformers` tokenizer in-process (GovTech ships `inference_onnx.py`) | No: single pair. Paper lists multi-turn as future work | Synthetic hold-out (N=17,201): ROC-AUC 0.99, F1 0.97, P 0.99, R 0.95. JailbreakBench F1 0.83. HarmBench recall 0.99 | Weights from Nov 2024; no updates since. Paper v2 Apr 2025 |
| **GovTech stsb-roberta-base off-topic** | Fine-tuned cross-encoder (concatenated pair) | Same as above | Same GovTech license | roberta-base (~125M, base model size; not on card); max 514 tokens | GPU T4: 0.031 s/pair; no CPU numbers | ONNX or safetensors scripts | No | Synthetic: F1 0.99. JailbreakBench F1 0.72. HarmBench recall 0.83 | Nov 2024 |
| **Von** (OSS Jev-like) | ModernBERT-large encoder with option-marker head | State + Choice/Noul/Score questions → probabilities | Apache-2.0 | 395M (1.5 GB fp32) | 0.096 s p50 on 4 vCPU with OpenVINO (JevBench v1.4). The repo table also lists 0.34 s p50 on CPU. Unmeasured on 2 vCPU | `von-sdk` 1.3.7 (Py ≥3.12), `/v1/systemone` server | No | JevBench v1.5.4 composite 0.00 (rank 105/106). Card: confidence "JevBench-shaped", refit needed; English only | Weeks old, single maintainer |
| **Laya** (OSS Jev-like) | ModernBERT-large / mmBERT, one forward pass | State + typed questions → probabilities | Apache-2.0 | 322–421M | 192–453 ms for 4 questions on a 56-core Mac Pro, 28 threads | Python package | No | MASSIVE-en 0.78, XNLI-en 0.86. Shipped over-confident. JevBench rank 86–106 | Weeks old |
| **Kev** (OSS Jev-like) | Qwen3.5 0.8B/4B/9B LoRA + pointer head; Kev-27B | `/v1/systemone`-compatible (TypeSafe SDK works unchanged) | Apache-2.0 | 0.8B–27B | CPU supported (fp32), no CPU timings. Kev-0.8B: 149 ms on Apple M5 | Own server: CUDA, ROCm, MLX, CPU | No | Test accuracy: 0.889 (27B), 0.838 (4B), 0.697 (0.8B); Jev 0.857 | Active (Sep 2026) |
| **JevK5 / Nimble / Winnow** (OSS Jev-likes) | 4B / 9B / 12B LLM fine-tunes scoring answer logits | State + questions → probabilities | Apache-2.0 (JevK5, Winnow); Nimble not stated | 4–12B | JevK5 needs about 9 GB CUDA for bf16 (GGUF exists). Nimble needs about 18 GB, GPU or Apple Silicon | GPU servers, llama.cpp (GGUF) | No | JevBench v1.5.4: Winnow-12B rank 2, JevK5 4B rank 4, Nimble 9B rank 40 | Weeks old |
| **NVIDIA Llama-3.1-NemoGuard-8B-TopicControl** | Llama-3.1-8B-Instruct LoRA for topic following | System prompt with topical rules + OpenAI-format conversation → "on-topic"/"off-topic" | NVIDIA Open Model License + Llama 3.1 Community License; "ready for commercial use" | 8B | No: supported hardware is A100 | NIM container, vLLM, TRT-LLM, HF; NeMo Guardrails | **Yes**, trained on multi-turn dialogues | Paper (Stay-on-Topic-8B, human distractors): distractor F1 0.885, on-topic F1 0.985 | Only v1; dataset updated Jan 2025 |
| **gpt-oss-safeguard-20b / 120b** | Reasoning model that labels content against a policy you write | Policy + content (harmony format) → decision + reasoning; structured outputs | Apache-2.0 + gpt-oss usage policy | 21B (3.6B active) / 117B (5.1B active) | No: 20B "fits on GPUs with 16GB" | **Bedrock, us-east-1 on-demand** (`openai.gpt-oss-safeguard-20b`, in-region only); vLLM, Ollama | Policy can cover a transcript | OpenAI Mod F1 82.9%, ToxicChat F1 79.9% (20B). OpenAI: dedicated classifiers can do better; "time and compute-intensive" | Bedrock launch 2025-10-29; EOL no sooner than 2026-10-29 |
| **IBM Granite Guardian 3.3 8B** | Risk judge with `custom_criteria` | Messages + criteria → yes/no (+ optional think) | Apache-2.0 | 8B | No published CPU path | vLLM | Not stated | Custom criteria "require testing" | Aug 2025 |
| **Qwen3Guard-Gen 0.6B/4B/8B** | Safety moderation | Prompt/response → Safe/Controversial/Unsafe + category | Apache-2.0 | 0.6–8B | 0.6B is small, but irrelevant | HF / vLLM | Prompt + response | Fixed 9 safety categories; no custom scope documented | — |
| **Llama Guard 4 12B** | Safety classifier, MLCommons S1–S14 | → safe/unsafe + categories | Llama 4 Community License | 12B | Single GPU | HF | Covered in release blog | Card documents no custom categories | Apr 2025 |
| **ShieldGemma 2B/9B/27B** | Policy-in-prompt Yes/No scorer | Policy + text → P(Yes) | Gemma terms (gated) | 2–27B | Unmeasured; 2B would be slow on 2 vCPU | HF | No | Trained on 4 harm types; "highly sensitive" to policy wording | 2024 |
| **Zero-shot NLI** (`MoritzLaurer/deberta-v3-base-zeroshot-v2.0`, `bart-large-mnli`) | NLI entailment as a classifier | Text + label hypotheses → scores | MIT base; use the `-c` variant for commercially clean training data. bart MIT | 0.2B / 0.4B | Unmeasured. 512 tokens | HF `zero-shot-classification` pipeline, ONNX | Concatenate history | Mean macro-F1 over 28 datasets 0.643 zero-shot (bart 0.497) | Collection updated Jan 2025 |
| **GLiClass v3** (`knowledgator/gliclass-*`) | Single-pass zero-shot classifier | Text + labels → scores | Apache-2.0 | 33M (edge) to 439M (large) | GPU numbers only (A6000) | `gliclass` package | Concatenate history | Avg zero-shot F1 0.49 (edge) to 0.70 (large) | Paper Aug 2025 |
| **SetFit** (our own labels) | Contrastive fine-tune of a sentence-transformer + logistic head | Text → P(class) | Apache-2.0 | Body of your choice (for example 33M) | Probe: encoder 37 ms (MiniLM-L6) / 78 ms (bge-small) p50 on 2 laptop threads; head negligible | In-process | Concatenate history | "8 labeled examples per class" competitive on CR (README) | v1.2.0 on 2026-09-04 |
| **Baseline: Nova Micro/Lite on Bedrock** | Small LLM with structured output | Prompt + history → JSON label | Not OSS (AWS) | n/a | n/a (network + generation; unmeasured) | `ChatBedrockConverse.with_structured_output` | Yes | None; we would measure | `amazon.nova-micro-v1:0` and `amazon.nova-lite-v1:0` active, on-demand, us-east-1 |

Bedrock availability was checked with `ListFoundationModels` in us-east-1 on 2026-10-13. Active and on-demand: `openai.gpt-oss-safeguard-20b`, `openai.gpt-oss-safeguard-120b`, `openai.gpt-oss-20b-1:0`, `amazon.nova-micro-v1:0`, `amazon.nova-lite-v1:0`, and `google.gemma-3-4b-it`. Not listed: Llama Guard, Granite Guardian, Qwen3Guard, NemoGuard, Jev, and any Jev-like model. Bedrock Guardrails also has **denied topics** (name, definition up to 1000 characters, up to 5 sample phrases). It isn't OSS, but #199 already calls `ApplyGuardrail`, so it could join the bake-off at little cost.

## Probe on our questions (2026-10-13)

A throwaway probe ran the GovTech jina model's ONNX export on CPU with onnxruntime, 2 intra-op threads, loaded once. The machine was an Intel laptop CPU (family 6, model 186), not a t3.large. Inputs were 15 study questions, 4 follow-ups (with and without their previous question), 12 off-topic requests, and 3 borderline questions, under two scope prompts:
- **short:** "a study tutor for the learner's own papers, books, magazines, and news, on any subject"
- **broad:** the short prompt plus an explicit list of subjects: science, history, cooking, sports, finance, security, art.

A sample this small shows the shape of the problem; it measures nothing.

**Latency.** The ONNX graph has a **fixed input shape of 1024 tokens** for both texts, so every question pays for 2 × 1024 tokens.

| Threads | Model-only p50 |
|---|---|
| 2 | 2,424 ms |
| 1 | 4,710 ms |

That is about 8× the 300 ms budget, on a faster CPU than a burstable t3.large. Shorter inputs would need a re-export from the safetensors weights with dynamic shapes, using GovTech's PyTorch class (untested).

**Accuracy.** Threshold 0.5, broad scope:

| Group | Result |
|---|---|
| Off-topic caught | 11/12. Missed "fix the bug in my React app" (0.02). The lowest catches were "Book a flight to Paris" (0.56), "Write an email to my landlord" (0.60), and "hi, how are you today?" (0.66). |
| Study questions wrongly rejected | 1/15: "How long should I rest a steak after grilling, according to the cookbook?" (0.95) |
| Follow-ups | All passed, with or without the previous question. With the short scope, "Why does it need to be fed every day?" alone scored 0.68, and adding the previous question brought it to 0.10. |
| Borderline | "What can you do?" 0.88 (rejected); "Plan my study week" and "Make me a quiz on the chapter" passed. |

With the short scope, **3 of 15 study questions were rejected**: photosynthesis (0.77), the fall of Rome "according to this book" (0.78), and the steak question (0.99). Scope wording moves the scores a lot, and naming a subject didn't rescue the cooking question. This matches the paper's warning about open-ended system prompts. The zero-shot model can't meet ≤1% false rejections for our scope.

**Small encoders for a trained classifier (SetFit body).** sentence-transformers on torch CPU, 2 threads, one follow-up question with its previous question (about 30 tokens):

| Encoder | p50 | p95 |
|---|---|---|
| `all-MiniLM-L6-v2` | 37 ms | 46 ms |
| `bge-small-en-v1.5` | 78 ms | 92 ms |

A SetFit logistic head adds negligible time. Even at 2–3× slower on a shared t3.large, either fits the 300 ms budget.

**Serving SetFit without torch (spike).** A toy SetFit model (bge-small body, 20 examples, 1 epoch) was exported as follows: the body went to ONNX with dynamic shapes via `torch.onnx.export`, and the logistic head was saved as `coef` and `intercept`. It then ran with onnxruntime, `tokenizers`, and numpy only: CLS pooling, L2 normalization, and a sigmoid.

| Variant | Size | Process RSS | p50 | P(off) on 3 test questions |
|---|---|---|---|---|
| SetFit `predict_proba` (torch) | — | — | — | 0.3797, 0.5949, 0.4142 |
| fp32 ONNX | 127 MB | 205 MiB | 9.5 ms | 0.3797, 0.5949, 0.4142 (identical) |
| int8 dynamic-quantized ONNX | 32 MB | 108 MiB | 4.7 ms | 0.3904, 0.5917, 0.4199 (within 0.011) |

The agent image therefore needs no torch, and the int8 model fits the agent's 512 MiB container limit. The toy model's probabilities only show that the export matches; they say nothing about accuracy.

## Recommendation

### Our own small decision model, trained with GovTech's method

1. **Why not GovTech's model as shipped.** It is about 8× too slow on CPU because of the fixed 1024-token export, and zero-shot it rejects real study questions (above). Its value to us is its **method**: an LLM drafts labeled on- and off-topic prompts for a stated scope, then a small classifier is fine-tuned on them. The off-topic half of its MIT dataset can also serve as extra negatives.
2. **Primary: a SetFit classifier** (Apache-2.0, `setfit` 1.2.0) on `bge-small-en-v1.5`, or `all-MiniLM-L6-v2` if latency is tight.
   - It learns our broad "any subject a learner studies" scope directly, from examples like the cookbook question.
   - It runs in-process on CPU at about 40–80 ms.
   - It keeps all text in our infrastructure.
   - It needs only the labeled set the eval needs anyway.
   - Cost: we own training and retraining. Training is a small CPU or one-GPU job, and the model artifact is about 100 MB.
3. **Option with no training: gpt-oss-safeguard-20b on Bedrock.** It has open weights, takes a written policy instead of training data, and runs on-demand in us-east-1, so no question text leaves AWS. It is a reasoning model: OpenAI calls it "time and compute-intensive", and its latency per question is unmeasured. Use it to draft and check labels offline, and keep it in the bake-off as the "OSS model, no training" choice.
4. **Baseline:** Nova Micro/Lite with structured output (not OSS), which every candidate must beat on the same eval.

### How it fits the graph

```
START → topic_check ─(off_topic)→ END   (decline "off_topic", no search)
                    └─(on_topic or error/timeout)→ search → answer → END
```

- **Port and adapter.** Add a question-check port in `tutoring` (#197's guard port), with a `SetFitTopicCheck` adapter that loads the model once at startup.
  - LangChain has no classifier base class, and `BaseChatModel` and `Embeddings` don't fit one, so the adapter is a plain port called from a node. Wrapping it in a `RunnableLambda` is optional; it gets tracing.
  - The gpt-oss-safeguard option would use `ChatBedrockConverse` with structured output behind the same port.
- **Input.** The previous question, a separator, then the current question. The probe shows the previous question rescues terse follow-ups.
- **Decision.** Off-topic only when `p_off ≥ threshold`. The threshold is set on our eval so that false rejections stay ≤1%.
- **Fail-open.** On any exception or a timeout (for example 250 ms), treat the question as on-topic and log it.
- **Flag and privacy.** Put it behind the `question_guard` settings (#199). Traces get `p_off` and the model version; the decline log has no user id.

### Risks

- **Training data quality.** The model is only as good as the labeled set. Draft broadly (every subject, documents, follow-ups, borderline study tasks) and have humans review it.
- **Borderline policy is a product call.** "What can you do?", "hi", and "help me debug my app" need a decision from the product owner before labeling. The probe shows models disagree on them.
- **CPU contention** on the shared, burstable t3.large. Measure p95 under the Compose stack's load.
- **English only**, like every candidate here.

### Validation plan

1. **Eval set** in `backend/evals/` (LangSmith, thresholds in `thresholds.yaml`), kept separate from training data:
   - ≥300 benign study questions across many subjects, including cooking books, sports news, and security papers, plus follow-ups with their previous question.
   - ≥200 off-topic questions.
   - A labeled borderline slice.
2. **Metrics:** false-rejection rate, off-topic catch rate, and p50/p95 added latency on a t3.large under load. Zero errors in 300 benign questions gives a 95% upper bound of about 1% (rule of three), so ≤1% needs either 0 errors in 300 or a larger benign set.
3. **Bake-off** on the same eval:
   - SetFit (bge-small, MiniLM)
   - gpt-oss-safeguard-20b on Bedrock
   - Nova Micro structured output (baseline)
   - Optionally, the GovTech jina model fine-tuned on our data and re-exported with dynamic shapes

   Pick the cheapest that meets ≤1% false rejections and ≥95% catch within 300 ms.
4. **Gate:** ship behind the flag, off by default, and turn it on after the eval passes.

### Not recommended

- **Jev:** third-party hosted, and question text would leave our infrastructure.
- **Kev, JevK5, Nimble, Winnow:** GPU-sized and weeks old.
- **Von and Laya:** near the bottom of JevBench, with benchmark-fitted calibration.
- **NemoGuard-TopicControl:** needs an A100-class GPU.
- **Llama Guard 4 and Qwen3Guard:** fixed safety taxonomies that can't express a custom scope.
- **ShieldGemma and Granite Guardian:** 2–8B models with unproven custom scopes.
- **GovTech jina as shipped:** too slow and too strict (above).

## Sources

- TypeSafe AI, "Introducing System One Models & Jev": https://typesafe.ai/blog/introducing-system-one-models-and-jev
- TypeSafe AI home: https://typesafe.ai/
- OpenRouter, TypeSafe SDK guide: https://openrouter.ai/docs/guides/community/typesafe-sdk
- DataCamp, "Top open-source Jev alternatives" (2026-09-23): https://www.datacamp.com/blog/top-open-source-jev-alternatives
- BenchLM, JevBench v1.5.4 leaderboard: https://benchlm.ai/benchmarks/jevbench
- Kev: https://github.com/jaredpalmer/kev
- Von: https://github.com/wfzyx/von, https://huggingface.co/wfzyx/von, https://pypi.org/project/von-sdk/
- Laya: https://github.com/NandhaKishorM/laya
- Bespoke Nimble: https://github.com/bespokelabsai/nimble
- JevK5: https://huggingface.co/alibiserikbay/jevk5
- GovTech jina off-topic model: https://huggingface.co/govtech/jina-embeddings-v2-small-en-off-topic (LICENSE, `inference_onnx.py`, `inference_safetensors.py`, `config.json` in the repo)
- GovTech roberta off-topic model: https://huggingface.co/govtech/stsb-roberta-base-off-topic
- GovTech collection and demo: https://huggingface.co/collections/govtech/off-topic-guardrail, https://huggingface.co/spaces/govtech/off-topic-demo
- Dataset: https://huggingface.co/datasets/gabrielchua/off-topic
- Chua, Chan, Khoo, "A Flexible Large Language Models Guardrail Development Methodology Applied to Off-Topic Prompt Detection", arXiv 2411.12946 (v2, 2025-04-09): https://arxiv.org/abs/2411.12946
- jina-embeddings-v2-small-en: https://huggingface.co/jinaai/jina-embeddings-v2-small-en
- NVIDIA NemoGuard TopicControl: https://huggingface.co/nvidia/llama-3.1-nemoguard-8b-topic-control
- Sreedhar et al., "CantTalkAboutThis", arXiv 2404.03820: https://arxiv.org/abs/2404.03820
- gpt-oss-safeguard-20b: https://huggingface.co/openai/gpt-oss-safeguard-20b
- gpt-oss-safeguard-120b: https://huggingface.co/openai/gpt-oss-safeguard-120b
- OpenAI, technical report for gpt-oss-safeguard (2025-10-29): https://cdn.openai.com/pdf/08b7dee4-8bc6-4955-a219-7793fb69090c/Technical_report__Research_Preview_of_gpt_oss_safeguard.pdf
- Amazon Bedrock model card, GPT OSS Safeguard 20B: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-oss-safeguard-20b.html
- AWS What's New, 18 open-weight models on Bedrock: https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-fully-managed-open-weight-models/
- Bedrock Guardrails denied topics (AWS ML blog): https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-guardrails-expands-support-for-code-domain/
- IBM Granite Guardian 3.3 8B: https://huggingface.co/ibm-granite/granite-guardian-3.3-8b
- Qwen3Guard-Gen: https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B
- Llama Guard 4: https://huggingface.co/meta-llama/Llama-Guard-4-12B
- ShieldGemma: https://huggingface.co/google/shieldgemma-2b
- Zero-shot NLI: https://huggingface.co/MoritzLaurer/deberta-v3-base-zeroshot-v2.0, https://huggingface.co/facebook/bart-large-mnli
- GLiClass: https://huggingface.co/knowledgator/gliclass-edge-v3.0
- SetFit: https://github.com/huggingface/setfit, https://pypi.org/project/setfit/
- Bedrock model availability: `bedrock:ListFoundationModels`, us-east-1, run 2026-10-13

**Not verified:**
- CPU latency on a real t3.large (the probe used a laptop CPU at 2 threads), and gpt-oss-safeguard latency on Bedrock.
- The stsb-roberta parameter count (taken from the base model, not the card).
- Von's and Laya's dates and long-term maintenance.
- TypeSafe's data-handling terms (not published on the pages read).
- Nova Micro latency for this prompt.
