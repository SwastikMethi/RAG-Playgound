# Hosted public beta implementation

Approved scope: Oracle Always Free ARM VM; same-origin FastAPI/React, worker,
PostgreSQL, Qdrant and Caddy; DuckDNS HTTPS; fresh cloud data. Public username
signup, Argon2id passwords, single-use recovery codes, revocable cookie sessions,
complete owner isolation and individual Fernet-encrypted OpenAI keys. All six
techniques and restricted PostgreSQL snapshots remain supported. Local loopback
mode and its existing data stay unchanged.

### Task 1: Accounts, authorization and individual provider credentials
Add migrations, auth endpoints, strict hosted configuration, ownership checks,
per-user profiles and worker/export credential isolation. Test with two accounts,
real PostgreSQL and deterministic provider boundaries. Never use a shared key in
hosted mode. Update contracts. Run pytest tests/integration/test_hosted.py.

### Task 2: Resource limits and accessible account screens
Add atomic hosted storage/queue/vector quotas and rate limits; retain 50 files per
corpus. Build login/signup/recovery/account/key screens using current UI tokens.
Verify recovery, CSRF, logout, expiry, isolation and quota failures; run the full
Python/frontend suites and browser checks at desktop/mobile sizes.

### Task 3: Production infrastructure and runbook
Add private production Compose with persistent volumes, Caddy TLS, safe defaults,
ARM builds, production secret setup, health checks and backup/restore scripts.
Use 2 worker slots, 1 active comparison, 5 projects/user, 500 MiB raw uploads,
2 GiB artifacts, 100,000 vector points, 64 queued jobs/user, 256 total, and a
20 GiB disk reserve. Validate Compose, scripts and ARM runtime; update status.

### Task 4: Release validation and independent review
Run existing release checks, a bounded live six-technique/standalone export smoke,
visual review, restart and isolated backup/restore checks. Review the complete
branch and fix important findings. Deploy only with a configured free VM;
never provision paid fallback. User has no Oracle account/VM yet, so leave a
concrete tested handoff for account creation rather than claim a live URL.

## Launch inputs
Oracle account/Always Free capacity, VM SSH access, DuckDNS hostname, Turnstile
site/secret keys, fresh master/database secrets. No production OpenAI environment
key: each user supplies their own. Recovery-critical secrets must be backed up
outside the VM. Oracle capacity/reclamation and individual OpenAI charges remain
explicit deployment limitations.
