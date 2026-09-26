# Approved implementation execution

The approved plan implements documents 01–13 and the M0–M8 tasks in document 10. Contracts own wire shapes. The user selected an owner-configured OpenAI-compatible endpoint. No deployment or live provider use is implied without configured, authorized credentials.

## Global constraints

Six real retrieval adapters, PostgreSQL text snapshots, independent lanes, durable events, honest timings, immutable inputs, shared runtime export, explicit fixture mode, and rendered design/accessibility review remain required. Resolve compatible versions through lockfiles. No fake production fallbacks.

### Task 1: M0 foundations

Repair validator compatibility and contract omissions, create packages and lockfiles, auth/configuration, PostgreSQL migrations/jobs, scoped artifact storage, shared UI primitives. Probe external dependency interfaces early.
Produces: validated contracts, typed runtime boundaries, durable repositories/jobs, development infrastructure.
Verification: `uv run pytest tests/unit/test_contracts.py tests/integration/test_foundations.py` and pack validator. Expected: actual contract validation, authorization, exclusive claims, repeatable migrations pass.

### Task 2: M1 real BM25 slice

Implement bounded parsing, immutable sources/corpora/configurations, chunking, actual BM25, context packing, configured streaming generation, persisted events and source inspection.
Consumes: contracts, repositories/jobs. Produces: runnable upload/prepare/ask/inspect flow and protected external-boundary records.
Verification: `uv run pytest tests/unit tests/integration`. Expected: identifier retrieval, evidence spans, no-evidence handling and end-to-end BM25 pass.

### Task 3: M2 dense and hybrid

Implement scoped Qdrant, embeddings, stable parallel RRF, actual local reranker, artifact reuse and aligned generation revisions.
Consumes: runtime, provenance and configuration contracts. Produces: four independent retrieval techniques.
Verification: `uv run pytest tests/unit tests/integration`. Expected: exact scope, fusion, failure isolation and reuse pass.

### Task 4: M3 traces and recovery

Implement one frontend reducer, fixed graphs, stage inspectors, replay, SSE recovery, cancellation/deadlines and worker fencing.
Consumes: ordered events and persisted outputs. Produces: consistent live/replay presentation.
Verification: `npm test` and `uv run pytest`. Expected: Unicode, duplicates, gaps, replay parity, cancellation and worker loss pass.

### Task 5: M4 hierarchy and PageIndex

Implement parent-child retrieval and actual PageIndex SDK/controller with bounded validated selections and PDF restrictions.
Consumes: typed evidence and provider gateway. Produces: six adapters and truthful capability states.
Verification: `uv run pytest` and `uv run python tools/probe_dependencies.py`. Expected: lineage, clipping, tree limits, public API checks pass; paid SDK indexing requires explicit live configuration.

### Task 6: M5 PostgreSQL snapshots

Implement encrypted credentials, approved hosts/relations, preview, read-only repeatable-read capture, stable keys and bounded snapshots.
Consumes: source runtime and scoped artifacts. Produces: immutable row-level evidence without query-time database access.
Verification: `uv run pytest tests/integration/test_postgres_source.py`. Expected: quoting, permissions, stable keys, limits and immutable capture pass.

### Task 7: M6 export

Package the same runtime with setup/query/API commands, dependency lock and source manifest. Verify privately with recorded boundaries, defaulting to no-data/offline mode.
Consumes: frozen configuration/provenance and boundary recordings. Produces: standalone Python archive.
Verification: `uv run pytest tests/integration/test_export.py`. Expected: clean command startup, evidence/context parity, privacy and traversal checks pass.

### Task 8: M7 product completion

Finish feedback/history/reruns, deletion impact and cleanup, error/empty states, diagnostics, documentation and responsive/accessibility design.
Consumes: all user-facing APIs. Produces: complete UI journey and operations guidance.
Verification: `npm run test:e2e` and `uv run pytest`. Expected: main journey and failure/security scenarios pass; inspect required rendered states.

### Task 9: M8 release verification

Run document 11's acceptance matrix and fresh review. Record actual live integration, browser screenshots/replay evidence and unverified dependencies precisely in IMPLEMENTATION_STATUS.md.
Verification: `uv run pytest`, `npm test`, `npm run build`, `npm run test:e2e`, pack validator and authorized live probes. Expected: performed gates green, external limitations explicit.
