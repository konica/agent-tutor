# Files

- [LangSmith Evaluations and Release Gates](evals.md) - Documents the Smart Tutor evaluation framework including LangSmith datasets, evaluator modules, adversarial attack taxonomy, seed corpus, thresholds.yaml release gates, and how to run eval splits against the agent.
- [Fakes and Unit Tests](fakes-and-unit-tests.md) - Documents the FakeChatModel and FakeEmbeddingModel test doubles, explains how to write unit tests with them, and covers the test layout conventions and pytest configuration for the backend.
- [Isolation and Deduplication Tests](isolation-tests.md) - Documents the tests/isolation/ suite, what it asserts about cross-user access and SHA-256 deduplication, why the tests exist, and how they relate to PRD US-11 and US-12.
