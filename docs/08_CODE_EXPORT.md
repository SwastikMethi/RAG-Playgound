# Portable implementation export

## User outcome

The user selects a completed lane and downloads a Python application implementing its exact configuration. The export includes the shared runtime source and dependency locks, so it does not depend on a live playground account or undocumented playground endpoints.

Export is available for every implemented v1 adapter. A missing external credential or optional dependency is disclosed in setup and verification; it cannot be hidden behind a fake implementation.

## Export options

Default include_data is false. The archive includes code and a source manifest with safe IDs and content fingerprints, but no original documents, text excerpts, database rows, traces containing content or credentials. The user supplies their files again through the generated ingest command.

If include_data is true, include the exact source snapshots used by the lane, clearly list the included content, and require the user to opt in. For database sources include captured selected text records and metadata, never connection credentials. The source snapshot is enough to rebuild the experiment; a live database connection is unnecessary.

Expose verification mode offline or live. Offline is the default and performs no new billed provider calls. A live replay is an explicit user choice and reports expected provider usage before execution.

## Archive layout

    README.md
    manifest.json
    pipeline.json
    pyproject.toml
    uv.lock
    .env.example
    Dockerfile
    compose.yaml
    src/rag_runtime/
    app/main.py
    scripts/ingest.py
    scripts/query.py
    scripts/verify.py
    tests/
    data/                     only with explicit include_data
    source-manifest.json
    THIRD_PARTY_NOTICES.md

Include only runtime modules and dependencies needed by the chosen technique where practical. The generated app exposes /health and /query and binds to loopback by default. Include Qdrant in Compose only when required. Never bundle the owner's PostgreSQL instance or application access token.

The README gives exact install, provider setup, index rebuild, query and verification commands that the generated application actually implements. It explains source types, indexing time, current limits, model dependencies and any unsupported source features.

## Manifest

Use contracts/export-manifest.schema.json. Record manifest version, technique, exported and original pipeline configuration hashes, runtime revision, dependency lock hash, corpus fingerprint, source hashes and safe file aliases, prompt revision and hash, tokenizer and model revisions, vector dimension, included-data flag, verification results and known limitations.

Replace internal profile IDs with portable aliases and environment variable names. Include the configured model identifier and allowlisted endpoint requirement; never include API keys. Do not serialize arbitrary database connection strings into the manifest or generated logs.

Preserve portable source IDs in source-manifest.json. Map them to neutral file aliases and expected hashes so reingestion can recover the same candidate/evidence identities even in a different project or Qdrant collection. A source hash mismatch stops parity replay and requests an explicit new ingestion. Include-data=false also excludes the user's original question and answer; verification summaries contain no private excerpts.

Remote provider model revision can be unknown. Record it honestly. A floating model name cannot support a claim of exact future text reproducibility.

## Shared implementation

The export copies or builds the same rag_runtime package revision used in the measured run. The API server is a thin wrapper. Do not ask an LLM to independently rewrite the selected pipeline, and do not maintain separate retrieval implementations for the web runner and exporter.

Artifacts are content-addressed. An export may rebuild indexes from included or newly supplied sources. If prebuilt artifacts are included in a later version, their format and library compatibility must be checked before loading. Never serialize executable Python objects from user-controlled content.

## Verification ladder

| Level | Required checks | Honest claim |
| --- | --- | --- |
| static | Schema validation, import/compile checks, dependency declaration, path/secret scan and archive traversal check | Package structure checked |
| offline_replay | Run exported runtime against exact snapshots with recorded external responses; compare evidence IDs/order, context text, source mappings and answer assembly | Runtime and retrieval replay checked without new model calls |
| live_replay | Rebuild or use verified indexes and run the original question with current configured providers; report evidence differences and answer/citation checks | Live replay performed at a recorded time |

Offline replay uses the actual BM25/fusion/packing algorithms and recorded embedding, reranker or tree-selection outputs where external nondeterminism must be controlled. Document the mocked boundaries in verification metadata. It does not establish fresh provider performance.

For PageIndex, replay recorded node selections and source-page reads through the exported controller. Validate the tree adapter and evidence mapping. Only an explicit live replay can test new tree-model decisions.

The builder can verify against private source snapshots in an isolated temporary directory while producing an archive with include_data=false. Delete temporary test data after validation and verify that no content leaked into the archive.

Byte-identical answer text is not a live parity requirement. Deterministic offline context/evidence behavior must match; live differences are reported with their provenance. Never put a verified badge on a level that was not run.

## Failure behavior

A failed build or parity check produces an error with a report and leaves the lane usable. Failed exports are not offered as verified downloads. A user may download a statically valid package when live checks were not requested, with a clear static or offline verification label.

Cap archive size at 150 MiB in v1 and reject larger include-data requests before building. Sanitize file names, prevent symlinks and traversal, use a bounded temporary directory, and require authorization for downloads.
