# Security and operations

## Deployment boundary

Local mode is single-owner and self-hosted. Bind published ports to loopback by default. The optional hosted public beta adds accounts, object-level authorization, quotas and individual provider credentials. See [the hosted runbook](20_HOSTED_DEPLOYMENT.md) for its operating limits and backup requirements; it is not a managed enterprise service.

Local workspace APIs, streaming endpoints and downloads require no application token. Anyone able to reach the local service can use it. Public deployment must explicitly enable hosted mode: all data endpoints require a revocable session and owner-scoped lookup. Sessions use Secure, HttpOnly, SameSite cookies; writes require exact Origin and a CSRF token. Passwords use Argon2id; one-time recovery codes are hashed, rotated on use and revoke existing sessions. The public signup/login/recovery forms use Turnstile plus persistent IP/account rate limits. Turnstile scripts are limited to authentication pages, with full navigation before private content loads. Other pages retain a strict same-origin script policy and sanitized Markdown.

Hosted OpenAI keys are Fernet-encrypted with the deployment master key, never returned to the browser, and loaded separately for each job owner. Hosted profiles accept only https://api.openai.com/v1; there is no environment-key fallback. Keys are omitted from exports and provider fingerprints. Removing/replacing a key affects jobs when they start; an already-running request can still incur charges. Account recovery does not recover a lost master key. Preserve a separate encrypted copy of production configuration.

Run same-origin web/API and reject cross-origin API requests. Do not enable wildcard CORS with credentials or log authentication values supplied to upstream providers.

## Provider and connection secrets

Model profiles are server-controlled and reference environment secrets. The frontend receives profile names, model IDs, capabilities, limits and availability only. A provider base URL is selected by the owner, not accepted as an arbitrary per-question URL.

Encrypt database passwords submitted through the UI with a master key supplied outside the application database. Use a maintained authenticated-encryption implementation, store a key version, and provide a key-rotation procedure. A missing master key disables persistent connection creation.

Logs, traces, errors, exported configuration and crash reports must omit credentials and authorization headers. Protected trace content may contain retrieved source text; do not forward it to external observability vendors by default.

## Network and source access

Allow database destinations through explicit owner configuration, including named private hosts when intentionally supported. Block cloud metadata endpoints and unknown destinations. Resolve and validate addresses on connection, use the configured TLS policy, and do not follow redirects to bypass a destination rule.

Use a read-only database role with permitted relations and columns, a read-only transaction, query timeout, row/text caps and a small connection pool. Do not rely solely on a prompt or a SELECT-prefix string check for safety. Ordinary views can execute functions; the owner must approve the specific source relation and role permissions.

The supported connector captures text snapshots and does not execute model-generated SQL. No automatic network fetches from document links or citation URLs are allowed.

## Untrusted content

Document content, filenames, metadata and database text are untrusted data. They may include instructions that attempt to change system behavior. Keep them in clearly delimited evidence context, give the model no operational tools, and validate citation IDs against the supplied evidence.

Parse with time, memory, page and byte limits. Reject unsupported encrypted or scanned inputs with an actionable message. Serve artifacts with safe content types and dispositions. Sanitize displayed Markdown and disable active PDF content where supported by the viewer.

## Cancellation and retries

Cancellation is cooperative for asynchronous network calls and explicit for owned subprocesses. Check the cancellation token before every provider request, after awaited calls and between tree-navigation iterations. Cancelled outputs may not be appended after the lane terminal event.

Use one automatic retry at most for transient provider errors before any answer text is delivered. Record the attempt and backoff in trace metadata. Do not retry authentication failures, invalid input, cancellations or a partially streamed answer. A user rerun creates another run with new usage.

Provider cancellation may not eliminate billing for work already accepted. Mark incomplete usage accounting as partial; never assert zero cost from a cancelled client request.

## Resource and retention controls

Enforce limits in document 01 before reading large inputs fully when possible. Enforce lane deadlines across retrieval, context and generation. Bound worker memory caches and event queues. Archive generation and file parsing run in separate bounded jobs.

Keep source content, traces and snapshots until the owner deletes them in v1. Disclose this default and offer project deletion as a later small extension if not included in initial UI. Source deletion already removes affected content through the specified cascade.

Deletion must cover raw files, extracted text, chunks, vectors, trees, candidate details, run answers and included-data archives. Connection deletion removes encrypted credentials; it need not remove already captured snapshots unless the user requests their deletion.

## Configuration and health

Provide .env.example without secrets and a validated server configuration file. Required settings include database DSN, artifact root, Qdrant URL, encryption key when connections are enabled, provider profiles, endpoint/host allowlists, concurrency caps and timeouts.

Separate liveness from readiness. Database and artifact storage failures prevent readiness. A missing optional technique dependency affects that technique's availability. Startup applies or checks migrations through one migration job, not competing API and worker auto-migrations.

Document backup and restore of PostgreSQL, artifact storage and matching Qdrant snapshots as a consistent set. For a simple restore path, retain source/index manifests and rebuild Qdrant from source snapshots.

## Testing environments

Automated tests run without real credentials by default, use a deterministic provider and a dedicated test database/Qdrant namespace, and cannot contact arbitrary external services. Live smoke checks require explicitly supplied keys and a small fixed fixture.

Keep test mode isolated from live mode in configuration and UI. If real credentials are absent, show provider setup or the labeled fixture preview. Never silently substitute fake results in a live run.
