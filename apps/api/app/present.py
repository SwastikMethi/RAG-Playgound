"""Only contract fields leave the API; database and secret fields are private."""

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from rag_runtime.contracts import schema_file, validate
from . import models as m


def present(session, obj):
    names = {m.Configuration: "Configuration", m.IndexBundle: "IndexBundle", m.Connection: "PublicConnection"}
    name = names.get(type(obj), type(obj).__name__)
    schema = schema_file("openapi.yaml")["components"]["schemas"][name]
    values = {key: getattr(obj, key) for key in schema["properties"] if hasattr(obj, key)}
    if isinstance(obj, m.Source):
        values["metadata"] = obj.source_metadata
    if isinstance(obj, m.Connection):
        values.update(obj.public_config)
    if isinstance(obj, m.Corpus):
        values["source_ids"] = list(
            session.scalars(
                select(m.CorpusSource.source_id)
                .where(m.CorpusSource.corpus_version_id == obj.id)
                .order_by(m.CorpusSource.ordinal)
            )
        )
    if isinstance(obj, m.IndexBundle):
        values.update(
            preparation_ms=obj.setup_metrics.get("preparation_ms"),
            preparation_reused=obj.setup_metrics.get("preparation_reused", False),
        )
    if isinstance(obj, m.Lane):
        feedback = session.get(m.Feedback, obj.id)
        values.update(
            technique=obj.config_snapshot["technique"],
            feedback=present(session, feedback) if feedback else dict(helpful="unset", note=""),
        )
    if isinstance(obj, m.Run):
        values["lanes"] = [
            present(session, lane)
            for lane in session.scalars(
                select(m.Lane).where(m.Lane.run_id == obj.id).order_by(m.Lane.created_at, m.Lane.id)
            )
        ]
        preference = session.get(m.Preference, obj.id)
        values["preference"] = (
            present(session, preference)
            if preference
            else dict(preferred_lane_id=None, tied_lane_ids=[], note="")
        )
    if isinstance(obj, m.Export):
        values["download_url"] = f"/api/v1/exports/{obj.id}/download" if obj.status == "ready" else None
    result = jsonable_encoder(values)
    validate(result, "openapi.yaml", name)
    return result
