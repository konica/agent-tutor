# Isolation tests (PRD US-11, US-12)

A learner can never read, list, retrieve, cite, or download another learner's documents, threads, notes, learning records, quizzes, reports, or usage — including two learners whose documents are in the same shared subject. MCP search returns only chunks of contents behind documents the caller can read (`can_read`).

Deduplication: a duplicate upload links to existing content without creating chunks, and a browser-sent hash alone never links content. Tests run against the API and MCP server.
