# Files

- [Ask Flow — Agent Graph](ask-flow.md) - Traces the complete ask-path through the LangGraph agent, covering subject detection, MCP search, relevance gate, growth check, answer generation, and the decline path. Also documents the summarize and idle-record side paths.
- [Ingestion Flow](ingestion-flow.md) - Documents the full document processing pipeline—browser duplicate check, presigned POST upload, SHA-256 deduplication, first-pages step, Docling extraction, chunking, and embedding—and the worker scheduling, isolation, and S3/SQS event path that drives it.
- [Lesson Notes and Learning Records](lesson-notes-and-learning-records.md) - Documents the learning module's two artifacts—per-thread Lesson Notes with soft-delete and edit-aware overwrite, and lifetime learning records written by exactly two triggers—together with the record sweeper CronJob that handles the idle trigger.
