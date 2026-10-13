# Topic-check model

The SetFit model the agent's topic check runs (spec `sdd/specs/2026-10-13-off-topic-questions-design.md`, ADR 0019).
`make topic-check-train` writes it here:

| File | What |
|---|---|
| `body.onnx` | int8 sentence-transformer body, dynamic shapes |
| `tokenizer.json` | its tokenizer |
| `head.npz` | logistic head: `coef` (1, dim), `intercept` (1,); class 1 = off-topic |
| `manifest.json` | version, base model, pooling, normalize, max tokens, tuned threshold, training data |

The agent image copies this folder to `/app/models/topic_check`. The check stays off
(`SMART_TUTOR_TOPIC_CHECK__PROVIDER=off`) until a committed model passes the `topic_check` eval. A retrain
replaces the files in a PR that records the eval results; each version adds about 30 MB to git history.
