# Judge rubrics

One Markdown prompt per LLM-as-judge evaluator (retrieval relevance, answer relevance, learning record quality, injection resistance; R2: quiz quality, report faithfulness). Judge: `qwen.qwen3-32b-v1:0`, temperature 0, returns a score and a short reason. Revise a rubric when judge–human agreement drops below 0.80 (`thresholds.yaml`).

Files: `answer_relevance.md` (`../answer_relevance.py`). Each is a Python format string with `{inputs}`, `{outputs}`, and `{reference_outputs}`; write any other brace as `{{` or `}}`.
