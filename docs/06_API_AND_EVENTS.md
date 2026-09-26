# HTTP API and event contracts

## Contract authority

The machine-readable contract is contracts/openapi.yaml, with external JSON Schema references for pipeline configuration, trace events and export manifests. This document defines behavior that schema validation cannot express. Return JSON with UTF-8 encoding. Prefix all application endpoints with /api/v1.

Every protected request carries Authorization: Bearer followed by the owner's application token. The health endpoint is public and contains no private details. Use same-origin requests. Never place the token, database credentials or model keys in URLs.

## Resource flow

| Operation | Endpoint | Behavior |
| --- | --- | --- |
| Create or list projects | POST or GET /projects | Return project metadata |
| Read project | GET /projects/{project_id} | Return one project's metadata |
| List source revisions | GET /projects/{project_id}/sources | Return processing status and sanitized metadata |
| Upload one file | POST /projects/{project_id}/sources/upload | Multipart file, create source and ingestion job, return 202 |
| Read source status | GET /sources/{source_id} | Include extraction warnings and job state |
| Inspect source | GET /sources/{source_id}/content | Authorized page or text preview |
| Read original source file | GET /sources/{source_id}/file | Authorized safe file bytes for the viewer; unavailable for database-only snapshots |
| Inspect deletion impact | GET /sources/{source_id}/impact | Return affected resource counts |
| Delete source | DELETE /sources/{source_id}?cascade=true | Require exact confirmation ID; reject active dependencies; return cleanup job |
| Add PostgreSQL connection | POST /projects/{project_id}/connections | Encrypt credentials and return sanitized profile |
| List or inspect connection | GET /projects/{project_id}/connections or /connections/{connection_id} | Never return secrets |
| Delete connection | DELETE /connections/{connection_id} | Remove credentials while preserving existing snapshots; reject active captures |
| List selectable relations | GET /connections/{connection_id}/relations | Approved schemas and fields only |
| Capture PostgreSQL text | POST /projects/{project_id}/sources/postgres | Create source and snapshot job from selected relation and fields |
| Freeze corpus | POST /projects/{project_id}/corpus-versions | Ready source IDs only; snapshot membership |
| List corpus versions | GET /projects/{project_id}/corpus-versions | Restore version selection after reload |
| Read corpus | GET /corpus-versions/{corpus_version_id} | Immutable metadata and source list |
| Save or list configurations | POST or GET /projects/{project_id}/configurations | New config revision on every save |
| Read configuration | GET /configurations/{config_id} | Inspect one immutable revision |
| Prepare | POST /projects/{project_id}/preparations | Resolve corpus/config and build or reuse required bundle |
| Read bundle | GET /index-bundles/{bundle_id} | Status, setup time, artifact reuse and warnings |
| Submit comparison | POST /projects/{project_id}/runs | Freeze 1 to 6 lanes and enqueue; return 202 |
| List or read runs | GET /projects/{project_id}/runs or /runs/{run_id} | Snapshot includes all lane IDs and latest event sequence |
| Stream events | GET /runs/{run_id}/events | Authenticated SSE with after_seq cursor |
| Cancel run | POST /runs/{run_id}/cancel | Idempotent cancellation request |
| Cancel lane | POST /runs/{run_id}/lanes/{lane_id}/cancel | Affect only the selected lane |
| Read evidence | GET /runs/{run_id}/lanes/{lane_id}/evidence | Full protected evidence records and rank metadata |
| Save lane feedback | PUT /runs/{run_id}/lanes/{lane_id}/feedback | Helpful, unhelpful or unset with note |
| Save preference | PUT /runs/{run_id}/preference | One preferred lane or a tie, with optional note |
| Export lane | POST /runs/{run_id}/lanes/{lane_id}/exports | Completed lane only; return export job |
| Export status or download | GET /exports/{export_id} or /exports/{export_id}/download | Manifest and authorized archive |
| Registry and profiles | GET /system/capabilities or /system/profiles | Public adapter/model metadata, no secrets |
| Job status | GET /jobs/{job_id} | Progress and safe error details |

No PATCH mutates a configuration or corpus version. A new run can reference parent_run_id for a rerun. The v1 run API rejects generation-setting mismatches across multiple lanes; callers make new aligned configurations before comparison.

## Submission and validation

Run requests contain corpus_version_id, question and lanes of config_id plus bundle_id, and optional parent_run_id. Validate that all referenced records belong to the route's project, each bundle is ready and bound to the same corpus and config revision, techniques are compatible, the instance has capacity, and model capabilities match the configuration.

Use an Idempotency-Key header for run, preparation and export creation. Store its request hash and result for 24 hours. The same key and body return the original resource; the same key with a different body returns 409. A user-initiated rerun uses a new key. Source uploads can deduplicate content separately but must not treat a browser reconnect as a new query.

Validate compatibility before accepting a run. Runtime failures remain possible and become lane error events. A configuration that depends on an unavailable adapter is rejected with 422 ADAPTER_UNAVAILABLE.

## State machines

Lane statuses: queued, running, completed, failed, cancelled, timed_out.

Run statuses: queued, running, completed, partial, failed, cancelled.

After all lanes terminate:

- All completed gives completed.
- At least one completed and at least one other terminal state gives partial.
- All cancelled gives cancelled.
- Otherwise gives failed.

Completed insufficient-evidence responses remain completed but have answer_kind insufficient_evidence. They cannot be displayed as verified factual answers.

Setting cancel_requested_at does not immediately assert that a provider call has stopped. The executor emits lane.cancelled after stopping or detaching owned work. A late result cannot change a terminal state. A queued cancellation can terminate without lane.started; its query timings remain null.

Bundle statuses: queued, preparing, ready, failed. Export statuses: queued, building, ready, failed. Job statuses: queued, running, succeeded, failed, cancelled. Source states are defined in document 05.

## SSE protocol

Each frame uses event: trace, id: run_id:seq and a JSON data field matching the trace schema. The client starts from after_seq=0. On reconnect it supplies the last applied sequence; accept Last-Event-ID as an alternative. If both exist they must agree, otherwise return 400.

    id: run_example:3
    event: trace
    data: {"schema_version":"1.0.0","event_id":"run_example:3", ...}

The abbreviated frame above is explanatory. Complete valid events are in contracts/examples/sample-events.jsonl.

Send events strictly by seq, deduplicate on the client, and close after delivering the run's terminal event. An already completed run can be streamed from sequence zero for replay. A missing or deleted run returns 404 before opening the stream. A malformed or impossible future cursor returns 400. v1 retains events until explicit deletion; there is no silent stream truncation or time-based cursor expiry.

After applying a snapshot with last_seq N, subscribe from N. Snapshot materialized state and last_seq must be read from one consistent database transaction. The UI uses a separate replay reducer from sequence zero when inspecting full history.

## Event types

The common envelope carries schema_version, event_id, run_id, lane_id or null, seq, emitted_at in UTC, elapsed_ms from the run's monotonic origin, type and payload.

| Types | Purpose |
| --- | --- |
| run.started | Lane IDs and queue time |
| lane.started | Technique, configuration and bundle identity |
| stage.started, stage.completed, stage.failed, stage.skipped | Observable stage lifecycle with unique span_id |
| retrieval.candidates | Native scores, ranks, source identity and branch membership |
| rerank.completed | Before/after rank transitions and reranker score |
| tree.nodes_selected | Actual selected document/node IDs and depth |
| context.selected | Exact labeled evidence included and excluded by budget |
| answer.delta | Append-only answer text with code-point offset |
| answer.completed | Final answer hash, answer kind and citation validation metadata |
| usage.recorded | Reported or estimated provider usage with completeness |
| warning | Safe code and explanatory message |
| lane.completed, lane.failed, lane.cancelled, lane.timed_out | Terminal lane state and final or partial timings |
| run.completed, run.partial, run.failed, run.cancelled | Terminal aggregate state |

Stage names: retrieval, query_embedding, lexical_search, dense_search, fusion, rerank, parent_expansion, document_selection, tree_navigation, context_packing and generation. The retrieval span can parent parallel child spans. Repeated tree steps have different span IDs.

Events carry bounded diagnostic excerpts and artifact references; the evidence endpoint provides full content. Limit one event to 128 KiB and a complete trace to 20 MiB. Stop collecting optional candidate detail if approaching the trace cap, emit TRACE_DETAIL_LIMIT, and preserve answer deltas, timings and terminal events.

## Errors

HTTP errors use an error object with code, message, retryable, details and request_id. Safe details identify invalid fields, unavailable dependencies or resource IDs, never provider authorization headers or full connection strings.

Required codes include VALIDATION_ERROR, UNAUTHORIZED, NOT_FOUND, RESOURCE_BUSY, CONFIG_MISMATCH, INDEX_NOT_READY, CORPUS_UNSUPPORTED, ADAPTER_UNAVAILABLE, PROVIDER_UNAVAILABLE, RATE_LIMITED, PROVIDER_TIMEOUT, WORKER_LOST, INPUT_LIMIT, INVALID_CITATION, EXPORT_FAILED and INTERNAL_ERROR.

Within an active stream, lane failures use structured events rather than replacing the SSE response with an HTTP error body. Failure before stream headers uses the ordinary HTTP error contract.
