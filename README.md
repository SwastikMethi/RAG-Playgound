# RAG Playground

A private, self-hosted workspace for comparing six retrieval techniques against your documents and PostgreSQL text snapshots. Ask once, inspect independent streamed answers, replay measured execution steps, leave feedback and export a standalone implementation.

## Run locally

Requires Python 3.12, uv, Node 22+ and Docker Compose. From this directory:

```sh
uv sync --frozen --all-extras
uv run python tools/init_env.py
```

Set `OPENAI_API_KEY` in the ignored `.env`. It already contains a generated encryption key for saved database credentials. The default profiles use `https://api.openai.com/v1`, `gpt-4.1-mini-2025-04-14` and `text-embedding-3-small`. Keep secrets out of `.env.example`.

```sh
uv run python tools/prepare_models.py --reranker --pdf
npm ci
./start.sh
```

`./start.sh` starts PostgreSQL and Qdrant, applies migrations, builds the frontend and starts the API and worker in the background. It waits for readiness before returning. Open **http://127.0.0.1:8780**; the workspace opens directly without a login or application token. Create a project, upload sources, freeze a corpus, select techniques and prepare them before asking.

Run `./stop.sh` to stop the API, worker and local database services. Uploads, indexes and database volumes are preserved. Logs are in `.data/logs/api.log` and `.data/logs/worker.log`; repeat starts do not create duplicate processes. Restart after changing `.env` or profiles. `RAG_MODE=fixture ./start.sh` enables a visibly labeled synthetic demonstration on both processes.

For the full container setup, PostgreSQL connection policy, backups, limits and troubleshooting, see [running the application](docs/17_RUNNING_THE_APPLICATION.md). See [implementation status](IMPLEMENTATION_STATUS.md) for checks actually performed and remaining limitations.

## Specification pack

The original implementation specification is retained below. Its fictional answers, traces and timings under `fixtures/` and `contracts/examples/` are examples, separate from measured application runs.

Build a live playground in which a user supplies documents or a supported database snapshot, selects retrieval techniques, asks one question, compares streamed answers and elapsed time, inspects visual execution traces, and exports a runnable implementation of a selected configuration. The user judges which answer is useful. A mandatory benchmark dataset, an automatic quality leaderboard, and an automatic winner are outside this release.

This repository contains the application, implementation specifications and synthetic development fixtures.

Revision 1.1.0 adds required design standards for a mature, uncluttered interface and clear step-by-step simulations, with implementation tasks and visual review gates. API and event contract versions remain unchanged.

## Start with Codex

1. Extract this folder into a new project directory, or place its contents into the root of the repository you want Codex to implement.
2. For an existing repository, preserve its instructions and merge the supplied AGENTS.md guidance instead of replacing an existing file.
3. Open that directory with Codex and paste the contents of [CODEX_START_PROMPT.md](CODEX_START_PROMPT.md).
4. Provide actual model credentials only through the implemented server environment or secret settings. Do not paste credentials into these documents.
5. Codex should implement the milestones in order, reporting the files changed, checks performed, and remaining blockers after each meaningful slice.

The first running slice must include real BM25 retrieval, real source inspection, streaming through a configured answer provider, and live events. A deterministic fake provider is allowed in automated tests and an explicitly labeled fixture preview. It cannot be represented as live RAG.

## Read the pack

| File | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Working rules for the implementing agent |
| [Product requirements](docs/01_PRODUCT_REQUIREMENTS.md) | Scope, user stories, requirements, release gates |
| [User experience](docs/02_USER_EXPERIENCE.md) | Screens, comparison lanes, visual explanations and accessibility |
| [Architecture](docs/03_ARCHITECTURE.md) | Services, execution ownership, adapters, storage and recovery |
| [Retrieval techniques](docs/04_RETRIEVAL_TECHNIQUES.md) | Exact behavior of six adapters and extension boundaries |
| [Data and indexing](docs/05_DATA_AND_INDEXING.md) | Corpus versions, provenance, preparation and database snapshots |
| [API and events](docs/06_API_AND_EVENTS.md) | Endpoint semantics, streaming, errors and contracts |
| [Timing and replay](docs/07_TIMING_AND_REPLAY.md) | Timing definitions, live animation and replay reduction |
| [Code export](docs/08_CODE_EXPORT.md) | Portable package contents and parity verification |
| [Security and operations](docs/09_SECURITY_AND_OPERATIONS.md) | Local-first access, secrets, limits, cancellation and deployment |
| [Implementation plan](docs/10_IMPLEMENTATION_PLAN.md) | Ordered build tasks and milestone acceptance |
| [Acceptance tests](docs/11_ACCEPTANCE_TESTS.md) | Concrete behavior and failure scenarios to verify |
| [Decisions and sources](docs/12_DECISIONS_AND_SOURCES.md) | Assumptions, trade-offs, external references and open implementation checks |
| [Design and simulation standards](docs/13_DESIGN_AND_SIMULATION_STANDARDS.md) | Visual system, information density, clear step explanations and rendered UI review |
| [OpenAPI](contracts/openapi.yaml) | HTTP request and response shapes |
| [Pipeline schema](contracts/pipeline.schema.json) | Versioned, strict pipeline configuration |
| [Trace event schema](contracts/trace-event.schema.json) | Durable live and replay event envelope |
| [Export manifest schema](contracts/export-manifest.schema.json) | Export provenance and verification status |
| [Example contracts](contracts/examples) | Valid configurations, run request, trace and export manifest |
| [Development fixtures](fixtures) | Fictional source documents, questions and SQL text-source fixture |
| [Pack validator](tools/validate_pack.py) | Local document, contract, example, link and trace consistency checks |
| [Validation report](VALIDATION_REPORT.json) | Completed documentation checks and explicit validation limits |

## Scope at a glance

Release v1 is a self-hosted, single-owner playground. It includes files, a read-only PostgreSQL text snapshot connector, saved configurations and runs, feedback, six adapters, stream recovery, visual replay, and code export. Six adapters means BM25, dense vector retrieval, hybrid retrieval, hybrid with reranking, parent-child retrieval, and an experimental PageIndex-backed tree adapter.

PageIndex is restricted to text-based PDF corpora in v1. It stays visible but disabled for incompatible corpora. It must use the actual PageIndex index and honestly expose only operations the application observes.

GraphRAG, RAPTOR, query expansion, analytical text-to-SQL, SaaS accounts, live database synchronization, and additional connectors have explicit extension paths; they are not acceptance requirements for v1.

## Source of truth

Product scope is authoritative in document 01. Machine-readable files under contracts are authoritative for wire shapes. Documents 03 through 09 are authoritative for runtime semantics. Documents 02 and 13 define required interaction and design quality. Document 11 defines behavioral and visual review gates. If a conflict is found, preserve the agreed product intent, fix the affected documents and contracts together, and record the decision. Never silently reduce a release requirement.

Package versions in the application must be selected and locked after compatibility checks. These specifications deliberately do not assert unverified latest versions or prescribe nonexistent SDK methods.
