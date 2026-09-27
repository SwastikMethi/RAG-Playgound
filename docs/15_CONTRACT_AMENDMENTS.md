# Pre-release contract amendments

These changes implement gaps identified in the approved plan, before any released clients or persisted application runs exist. The API prefix and existing pipeline/event semantics remain v1. New diagnostic fields are optional so the supplied recordings remain valid.

- Run snapshots include saved preference and each lane's feedback. Workflow restoration reduces the retained event stream from zero rather than treating the partial HTTP snapshot as a complete workflow state.
- Existing stage events may contain typed, bounded observed details. Evidence may retain parent/child links, matched terms and tree node IDs. Tree selections may retain titles. A protected lane-scoped artifact route returns full step detail only when that artifact is explicitly referenced by the lane.
- Job cancellation covers ingestion, preparation, comparison and export. Cancelling a comparison delegates to its run. Deletion cleanup is not interruptible; failure remains retryable. Cancelled preparation/export resources use their existing failed state with a CANCELLED error, while the job state is cancelled.
- A protected PostgreSQL preview route uses the capture selection, validates the same allowlists, and returns at most five records with bounded text. It creates no source revision.
- Protected readiness reports required storage availability without exposing secrets. Technique capabilities include effective default configurations, requirements and explicit server mode. History accepts question and terminal-state filters.
- The pack validator uses the supported OpenAPI validation entry point, and scans specification files rather than dependency caches. Application validation remains separate.

## Persisted execution mode and request boundaries

Run responses now require `mode` (`live`, `fixture`, `test`) so saved fixture answers remain labeled even after provider setup changes. Migration 0002 preserves previous fixture runs. Private operations declare safe 403 cross-origin and 413 oversized-body errors. Received bytes are bounded even without Content-Length; multipart uploads allow 21 MiB including framing, other JSON requests 256 KiB.
