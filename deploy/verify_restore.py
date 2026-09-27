"""Read-only restore check: artifact hashes, decryptability and scoped vector counts.

Run inside the restored API container before allowing public traffic or starting workers.
"""
import hashlib
import json
from sqlalchemy import select
from app.connections import cipher
from app.database import Store
from app.models import Artifact, Connection, IndexBundle, Job, Project, User
from app.settings import Settings
from rag_runtime.vectors import Scope, VectorStore


def verify(settings):
    store = Store(settings.database_url, settings.artifact_root, settings.lease_seconds, settings)
    vectors = VectorStore(settings.qdrant_url, settings.qdrant_collection_prefix)
    counts = dict(artifacts=0, credentials=0, vector_scopes=0)
    try:
        with store.session() as s:
            if settings.deployment == "hosted" and s.scalar(select(Project.id).where(Project.owner_id.is_(None)).limit(1)):
                raise RuntimeError("Restore contains unowned projects in hosted mode.")
            for artifact in s.scalars(select(Artifact).execution_options(yield_per=100)):
                with store.path(artifact).open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != artifact.content_sha256:
                        raise RuntimeError("Restored artifact failed its integrity check.")
                counts["artifacts"] += 1
            encrypted = list(s.scalars(select(User.encrypted_openai_key).where(User.encrypted_openai_key.is_not(None))))
            encrypted += list(s.scalars(select(Connection.encrypted_secret)))
            for value in encrypted:
                cipher(settings).decrypt(value.encode())
                counts["credentials"] += 1
            for job in s.scalars(select(Job).join(IndexBundle, IndexBundle.id == Job.resource_id).where(
                    Job.kind == "prepare_index", IndexBundle.status == "ready")):
                scope = job.progress.get("vector_scope")
                if not scope:
                    continue
                collection = vectors.collection(job.progress["vector_dimensions"])
                actual = vectors.client.count(collection, count_filter=Scope(**scope).filter(), exact=True).count
                if actual != job.progress.get("reserved_vectors"):
                    raise RuntimeError("Restored vector count does not match its durable reservation.")
                counts["vector_scopes"] += 1
        return counts
    finally:
        vectors.close()
        store.engine.dispose()


if __name__ == "__main__":
    print(json.dumps(verify(Settings())))
