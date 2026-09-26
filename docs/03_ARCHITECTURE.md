# Technical architecture

## Deployment and stack

Build a modular Python backend and a TypeScript React frontend. Release v1 runs on the owner's machine or a private server. Use Python 3.12, Node.js 22 or a later supported LTS, React with TypeScript and Vite, FastAPI with Pydantic, SQLAlchemy and Alembic, PostgreSQL, and Qdrant. Use exact compatible released dependency versions and commit Python and JavaScript lockfiles. Verify compatibility on both a Linux container and the intended developer operating system.

Use four application services in Docker Compose: api, worker, postgres and qdrant. The API image serves the built frontend in production. Vite proxies /api during development. Shared local artifact storage is a mounted volume accessible to api and worker. PostgreSQL and Qdrant are private to the Compose network by default.

PostgreSQL stores metadata, durable jobs and run events. Qdrant stores dense vectors. BM25 stores a safe tokenized corpus artifact and rebuilds its in-memory search structure when loaded. Do not use pickle for user-influenced artifacts. Redis, Kubernetes and a separate event broker are unnecessary for the bounded first release.

The suggested stack is an implementation decision, not a requirement to replace compatible infrastructure in an existing repository.

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| Frontend | Source management, configuration, independent lanes, stream reduction, evidence inspection and replay |
| API | Authorization, validation, immutable snapshots, job creation, event streaming, artifact access and downloads |
| Worker | Source ingestion, indexing, comparison orchestration, export and deletion cleanup |
| Source adapters | Turn files or approved PostgreSQL records into immutable source artifacts |
| Preparation planner | Resolve required indexes, deduplicate work and bind configurations to ready artifacts |
| Retrieval adapters | Produce ordered evidence and observable stage events |
| Context assembler | Deduplicate, budget and label evidence for the common answer prompt |
| Provider gateway | Embedding, generation and tree-selection calls, limits, cancellation and usage metadata |
| Event writer | Append validated, ordered, durable run events |
| Export builder | Package the shared runtime, configuration, provenance and rebuild instructions |

## Suggested repository layout

    apps/web/src/
      app/
      features/sources/
      features/configurations/
      features/comparison/
      features/trace/
      features/history/
      features/export/
      api/
    apps/api/app/
      routes/
      services/
      models/
      repositories/
      auth/
    packages/rag_runtime/
      config/
      sources/
      parsing/
      chunking/
      indexing/
      retrievers/
      providers/
      context/
      generation/
      events/
      export/
    workers/
    migrations/
    tests/unit/
    tests/integration/
    tests/e2e/
    contracts/
    fixtures/
    docs/
    compose.yaml
    IMPLEMENTATION_STATUS.md

The runtime package must not import API routes, web state or deployment-specific credentials. Both the worker and an exported application call its public interfaces.

## Runtime boundaries

Define typed interfaces matching these semantics. Method names below are internal application interfaces, not claims about third-party SDK methods.

    SourceAdapter.capture(request, cancellation) -> SourceSnapshot
    Parser.parse(source) -> ParsedDocument
    PreparationPlanner.resolve(corpus_version, config) -> IndexRequirements
    IndexBuilder.prepare(requirements, progress, cancellation) -> IndexBundle
    Retriever.retrieve(question, bundle, config, trace, cancellation) -> RetrievalResult
    ContextAssembler.pack(evidence, generation_config) -> PackedContext
    Generator.stream(question, packed_context, profile, trace, cancellation)
    ExportBuilder.build(completed_lane, options) -> ExportArtifact

RetrievalResult includes ordered EvidenceRef objects, native scores and score types, branch ranks, trace artifact references, warnings and observable usage. It contains evidence, not the final answer. Final answering always goes through the shared context assembler and generator in v1.

An EvidenceRef points to a source revision and exact page or character interval or database record, carries stable evidence_id and candidate_id values, and records the excerpt actually supplied to generation. Synthetic summaries may aid search, but original evidence must be available for citations.

## Durable job execution

Use a jobs table with job type, resource ID, project ID, status, owner token, lease expiry, heartbeat, created time, start time and terminal time. Supported job types are ingest_source, prepare_index, compare_run, export_lane and delete_source.

A worker atomically claims a queued row with SELECT FOR UPDATE SKIP LOCKED, assigns an unpredictable owner token, and commits the claim before executing external work. It renews its lease every 5 seconds; default lease is 30 seconds. Commit bounded progress updates. Never hold a database transaction open while parsing, calling a model, or waiting for network I/O.

Claiming is serialized in PostgreSQL. Resource references are checked again before execution. Every write from a running worker verifies the current owner token so an expired owner cannot write late results.

One compare job owns an entire run. Within that job, lanes are asynchronous tasks and CPU-bound operations execute outside the event loop. Start all lane tasks without one lane's failure cancelling the others. Bound local reranking and provider calls separately. A comparison can have 6 eligible lanes while a provider semaphore admits fewer simultaneous requests; expose that wait.

Defaults: 2 active compare jobs, 4 simultaneous remote generation or tree-selection requests per configured provider, 4 embedding calls, and 1 local reranking task. These are adjustable resource settings, not guarantees of fairness or throughput.

## Request lifecycle

1. API validates access, question length, corpus, configurations, ready bundles and limits.
2. API freezes the run and lane inputs and creates the compare job in one transaction.
3. API returns run_id, lane IDs and the authorized events endpoint with HTTP 202.
4. Worker claims the job, emits run.started, launches lanes and supplies one event writer.
5. Each lane retrieves evidence, packs context, streams the answer and emits its terminal event.
6. The run reaches one terminal aggregate state when all lanes are terminal.
7. Frontend can reconnect or reopen history using persisted events and the run snapshot.

Index preparation occurs in separate jobs. Ask never waits for indexing while showing a query timer. A preparation request with an identical artifact fingerprint reuses a ready result or joins an existing preparation job.

## Event persistence and recovery

The compare coordinator serializes emissions into a queue. The event writer assigns strictly increasing sequence numbers per run in the same transaction that inserts the event and updates any materialized lane state. A unique constraint on run_id and seq prevents duplication. Event identifiers are run_id followed by a colon and the sequence.

Durable writes precede client delivery. Emit the first nonempty answer delta immediately, then batch subsequent deltas for at most 50 ms or 2 KiB of UTF-8 text, whichever occurs first. Capture first-token time before batching. Bound the event queue and apply backpressure; do not allow unbounded token buffering.

SSE can poll the events table every 250 ms in v1. Query through an index on run_id and seq, use limited batches, and send a heartbeat comment every 15 seconds. This architecture favors simple recovery over extreme fan-out. Introduce a notification broker only after measured need.

On lease expiry, a watchdog fences the old owner and fails unfinished lanes with WORKER_LOST. Keep completed lanes and their artifacts. Aggregate the run normally. Do not automatically repeat potentially billed model calls. The user can create a new run for a failed lane.

If event storage becomes unavailable, stop starting new external work and cancel outstanding lane tasks where possible. The watchdog resolves stale jobs after storage returns. A failed event stream by itself does not stop a healthy backend run.

## Artifact and identity design

Use opaque application identifiers; never embed credentials or filenames in storage paths. Generate content hashes from canonical bytes. Index fingerprints include project, corpus content fingerprint, source parser version, chunker and tokenizer revision, embedding profile and model identity, vector dimension, preprocessing revision and algorithm parameters.

Configuration fingerprints include all effective settings, including prompts and budgets. Generation-only changes reuse indexes but receive a new configuration fingerprint. Store dependency and provider revision metadata where available; an unknown remote model revision is recorded as unknown.

Share artifacts within one project only in v1. Reference-count shared artifacts before deletion. Do not deduplicate across owners as an implicit future SaaS optimization.

## API and process isolation

Serve frontend and API from one origin. Use explicit bearer authorization, strict allowed origins, and no credentials in query strings. Stream with fetch so the Authorization header and resume cursor are available. A file download uses authorized fetch and a Blob URL, then revokes it.

Parse untrusted files in bounded worker subprocesses. A worker task timeout must terminate its owned subprocess when safe; cancelling an asyncio wrapper alone does not stop synchronous parsing or reranking.

Model endpoints and database hosts are configured through owner-controlled profiles with validated allowlists. Raw source URLs, arbitrary filesystem paths and user-supplied executable plugins are excluded from v1.

## Operational visibility

Use structured operational logs with request_id, job_id, run_id, lane_id, stage, duration and error code. Omit source text, prompts, answers and secrets by default. The application's protected trace store deliberately retains user content for inspection; it has a separate retention and deletion policy.

Expose health checks for the process and readiness checks for required infrastructure. Missing optional model weights or PageIndex capabilities make those cards unavailable rather than taking down the entire application.
