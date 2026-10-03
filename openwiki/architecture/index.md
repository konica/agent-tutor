# Files

- [Module and Layer Rules](module-layer-rules.md) - Documents the enforced import contracts for the Smart Tutor modular monolith — module order, layer hierarchy, vendor-SDK restrictions, and how to run and fix the import-linter.
- [System Architecture Overview](overview.md) - Describes every deployable in Smart Tutor — API server, agent server, RAG MCP server, ingestion worker, CronJobs, and web app — their responsibilities, Docker image targets, network topology, and the end-to-end request flow from browser to Amazon Bedrock and back.
- [Shared Kernel](shared-kernel.md) - Describes the smart_tutor.shared package — cross-module domain value objects, typed identifiers, abstract model ports, ModelFactory, Settings, and infrastructure adapter stubs that every module may use.
