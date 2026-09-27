# Running the application

See [implementation status](../IMPLEMENTATION_STATUS.md) for actual verification coverage. This release is single-owner and binds to loopback. The workspace opens without a login or application token. Before exposing it beyond your machine, add access control through a trusted HTTPS reverse proxy or restricted network.

## Local processes

The [README](../README.md) has the startup commands. Use Python 3.12, Node 22+ and the committed `uv.lock` and `package-lock.json`. `tools/init_env.py` creates `.env` with private permissions and a fresh encryption key; it never overwrites existing settings. Set the provider API key locally. Never commit it or place it in example files.

After the one-time setup, run `./start.sh`. It starts development storage at loopback ports 6544 and 6344, waits for Docker services, applies migrations, builds the frontend and starts the API and worker in the background. Production builds are served by the API at port 8780. Startup verifies API readiness and worker initialization. Run `./stop.sh` to stop those processes and the two storage containers without removing uploads, indexes or volumes. Both scripts work from another directory when invoked by their path. They require the installed `.venv`; startup also requires `.env`, frontend dependencies, npm and a running Docker engine.

Process records are under `.data/run`; logs are `.data/logs/api.log` and `.data/logs/worker.log` (replaced on each fresh start). Repeated starts reuse the running pair. Stop checks process identity before signaling, including child processes, and repeated stops are safe. Stop and start again after changing settings or code. Finish or cancel active work before stopping; interrupted jobs follow the existing lease-recovery behavior. These scripts manage the local-process setup; keep it separate from the full container stack below.

For frontend development, run `npm run dev` alongside the API (Vite proxies `/api` to port 8780). The worker must remain running for ingestion, preparation, comparison, deletion and export jobs.

Download the public parser/reranker assets with `uv run python tools/prepare_models.py --pdf --reranker`. The reranker uses pinned safetensors on CPU; the Linux lock uses CPU-only PyTorch packages via the [official uv integration pattern](https://docs.astral.sh/uv/guides/integration/pytorch/). No model weights are included in exports. Model setup may take several minutes and needs internet access. PageIndex additionally uses the configured answer provider while constructing its index; it accepts only text-layer PDF corpora.

## Docker Compose

After configuring `.env`, use:

```sh
docker compose build
docker compose run --rm worker python tools/prepare_models.py --reranker --pdf
docker compose up -d
```

The migration job completes before API/worker startup. API and worker share artifact and model volumes; PostgreSQL and Qdrant remain private by default. Open http://127.0.0.1:8780. Start this stack separately from host processes to avoid two workers or conflicting storage paths. `docker compose stop` stops services without deleting volumes. This local stack uses a development-only PostgreSQL password; keep its database port private.

## Modes, credentials and troubleshooting

- `RAG_MODE=live` uses real configured providers. Missing keys, provider failures and unsupported settings fail explicitly. There is no fixture fallback. `RAG_MODE=fixture` on both API and worker enables synthetic answers and embeddings, visibly labeled in saved runs and exports.
- `config/profiles.yaml` is owner-managed. Model identities, roles, dimensions, tokenizer and supported generation options must match the endpoint. `RAG_PROVIDER_HOST_ALLOWLIST` permits exact hosts. Requests validate DNS destinations, pin the resolved address and preserve TLS server-name verification. Redirects and metadata/link-local destinations are refused. To change credentials, update `.env` and restart API/worker; profile identity changes require compatible new preparation.
- For GPT-6 Luna, set `completion_token_parameter: max_completion_tokens` and `reasoning_effort: none` in its answer profile. This supports the playground's temperature setting and bounded visible answers. Both streaming answers and PageIndex completion calls use these options. Older profiles keep `max_tokens` and omit reasoning effort by default; their fingerprints and prepared vector indexes remain compatible. Other reasoning settings require matching model capabilities, including `supports_temperature: false` where custom temperature is unsupported. Profile availability only checks local configuration; it does not verify upstream parameter support.
- `/api/v1/health` reports process liveness. The readiness endpoint checks database migration head and writable artifact storage. Neither requires a token. Setup shows profile and technique availability without billing model calls. A configured key does not prove provider access or quota. Qdrant failures are reported on affected vector operations.
- A queued item usually means the worker is stopped or capacity is in use. Check `.data/logs/worker.log` for the local scripts, or `docker compose logs worker` for the full container stack. Retry by starting a new preparation/run after correcting the cause. Worker loss fails unfinished work explicitly after its lease expires; it never silently repeats billable model calls.
- If reranking is unavailable, install the `rerank` extra and prepare weights. If parsing fails because model assets are absent, prepare the PDF assets. Scanned or encrypted PDFs require a supported text-layer copy; the parser does not enable OCR.
- Cancellation is best effort for upstream HTTP work and may incur provider charges. Owned parser, tree-indexing and reranker subprocesses are terminated. One lane can stop without stopping the others. Disconnecting a browser does not cancel work; reconnect/history uses persisted events.

## Retention, backup and restore

Sources, corpus/configuration revisions, runs, traces and exports remain until explicitly deleted. The source deletion inspector lists impact and requires confirmation. Busy dependent jobs block deletion. Cleanup removes dependent database records, protected artifacts, exports and scoped vectors. Failed cleanup stays visible and retryable; it cannot be used for new runs. Downloaded copies cannot be recalled. Failed/cancelled preparation vector scopes are reconciled automatically after a grace period.

For a consistent backup, stop API and worker first, then capture all three stores: PostgreSQL (`pg_dump -Fc`), the artifact volume and Qdrant storage/snapshots. Keep the matching configuration, lockfile/runtime revision and `.env` separately in encrypted private storage. Copy stopped Docker volumes with your backup tooling; do not copy a running PostgreSQL data directory. Record the backup timestamp and restore all stores from the same checkpoint into a fresh stack, restore the external master key and run migration/readiness checks before restarting work. Test a source preview, old run replay and an export after restoring.

The master key encrypts saved source-database credentials. Losing it makes those connections unreadable; frozen snapshots remain usable. Rotate safely by capturing any required sources, deleting stored connections while the old key is available, changing the key, restarting services and recreating connections.

## Supported limits and checks

Files: 20 MiB each; corpus: 50 sources, 100 MiB, 500 PDF pages, two million characters and 10,000 chunks. PostgreSQL snapshots: 10,000 rows or 20 MiB selected text. Questions: at most six lanes, two active comparisons; four answer-provider operations and four embeddings concurrently, one local reranker. Defaults: 512/64 chunking, 20 candidates, five context units, 3,000 context tokens, 512 output tokens. PageIndex retrieval: three PDFs, depth four, 12 nodes, eight model calls and 12 pages. Exports: 150 MiB. Events: 128 KiB each and 20 MiB per run. Unknown timings/costs remain unavailable; fixture timings do not represent model performance.

The vector runtime materializes at most the v1 10,000-chunk ceiling; increase it only with a paginated implementation. Offline exports replay recorded model/embedding/reranker boundaries and run the actual retrieval/context controller; live verification is a separately requested, potentially billable comparison. Answer differences are not automatically quality judgments.

```sh
uv run python tools/validate_pack.py
uv run pytest
npm test
npm run build
npm run test:e2e
```

Python integration checks use `ragplayground_test` and dedicated vector prefixes. Browser checks run a real API and worker on port 8781 with fixture providers. Keep production traffic away from these test resources. The pack validator checks specifications; it does not test application behavior.

## PostgreSQL text sources

The playground's own database and a source database are separate connections. Source connections require `RAG_MASTER_KEY`, an external Fernet key, and exact owner-controlled destination and relation policies in `.env`. Generate the key using the command in `.env.example`; back it up separately from PostgreSQL.

For example:

```dotenv
RAG_DATABASE_HOST_ALLOWLIST=["db.internal"]
RAG_DATABASE_RELATION_ALLOWLIST=[{"host":"db.internal","port":5432,"database":"knowledge","schema":"public","relation":"articles","columns":["id","body"]}]
```

Prepare a dedicated role in that source database. Set its password securely using your database administration tool, then grant only the required access:

```sql
CREATE ROLE rag_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE knowledge TO rag_reader;
GRANT USAGE ON SCHEMA public TO rag_reader;
GRANT SELECT (id, body) ON public.articles TO rag_reader;
```

The role must not inherit write privileges on the selected relation. Only explicitly approved relations and columns appear in the browser. Approve views only after reviewing the functions they call. Use `verify-full` TLS for remote sources and configure the PostgreSQL client trust roots on the server. `disable` is available for an intentional local development connection.

Connect through the source panel, inspect the allowed relation, choose non-null unique key columns and text columns, then preview or capture. A read-only repeatable-read transaction freezes at most 10,000 rows and 20 MiB of selected text. The interface discloses truncated captures. Queries read this frozen source and never reconnect. Refresh creates a new source and corpus revision; previous runs retain their old snapshot. Deleting a connection removes credentials while retaining already captured sources.
