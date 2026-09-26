"""Owner-approved connections. Captured sources do not depend on surviving credentials."""

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from rag_runtime.contracts import request as check_request
from rag_runtime.errors import Problem
from rag_runtime.network import resolve_host
from rag_runtime.postgres_source import capture, list_relations, policies
from .content import enqueue
from .database import scoped
from .models import Connection, Job, Project, Source
from .present import present

router = APIRouter(prefix="/api/v1")


def cipher(settings):
    key = settings.master_key.get_secret_value()
    if not key:
        raise Problem(
            "MASTER_KEY_REQUIRED",
            "Configure the external encryption master key to save or use database connections.",
            409,
        )
    try:
        return Fernet(key.encode())
    except ValueError:
        raise Problem("MASTER_KEY_INVALID", "The configured encryption master key is invalid.", 409) from None


def password(settings, connection):
    try:
        return cipher(settings).decrypt(connection.encrypted_secret.encode()).decode()
    except InvalidToken:
        raise Problem(
            "MASTER_KEY_INVALID", "The current master key cannot decrypt this connection.", 409
        ) from None


@router.post("/projects/{project_id}/connections", status_code=201)
async def create_connection(project_id: str, body: dict, request: Request):
    check_request(body, "CreateConnection")
    settings = request.app.state.settings
    encrypted = cipher(settings).encrypt(body["password"].encode()).decode()
    await resolve_host(body["host"], body["port"], settings.database_host_allowlist)
    if not policies(body, settings.database_relation_allowlist):
        raise Problem(
            "RELATION_DENIED", "Configure approved relations and columns for this database before connecting."
        )
    with request.app.state.store.session() as s:
        scoped(s, Project, project_id, lock=True)
        record = Connection(
            project_id=project_id,
            public_config=dict({k: v for k, v in body.items() if k != "password"}, kind="postgres"),
            encrypted_secret=encrypted,
        )
        s.add(record)
        s.flush()
        return present(s, record)


@router.get("/projects/{project_id}/connections")
def connections(
    project_id: str, request: Request, limit: int = Query(50, ge=1, le=100), cursor: str | None = None
):
    with request.app.state.store.session() as s:
        scoped(s, Project, project_id)
        query = select(Connection).where(Connection.project_id == project_id).order_by(Connection.id)
        if cursor:
            scoped(s, Connection, cursor, project_id)
            query = query.where(Connection.id > cursor)
        rows = list(s.scalars(query.limit(limit + 1)))
        return dict(
            items=[present(s, r) for r in rows[:limit]],
            next_cursor=rows[limit - 1].id if len(rows) > limit else None,
        )


@router.get("/connections/{connection_id}")
def connection(connection_id: str, request: Request):
    with request.app.state.store.session() as s:
        return present(s, scoped(s, Connection, connection_id))


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: str, request: Request):
    with request.app.state.store.session() as s:
        record = scoped(s, Connection, connection_id)
        scoped(s, Project, record.project_id, lock=True)
        pending = s.scalar(
            select(Job.id)
            .join(Source, Source.id == Job.resource_id)
            .where(
                Source.project_id == record.project_id,
                Source.source_metadata["connection_id"].as_string() == record.id,
                Job.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        if pending:
            raise Problem(
                "RESOURCE_BUSY", "Wait for or cancel snapshot capture before removing this connection.", 409
            )
        s.delete(record)
    return Response(status_code=204)


def credentials(request, connection_id):
    with request.app.state.store.session() as s:
        record = scoped(s, Connection, connection_id)
        return record.public_config, password(request.app.state.settings, record)


@router.get("/connections/{connection_id}/relations")
async def relations(connection_id: str, request: Request):
    config, secret = credentials(request, connection_id)
    settings = request.app.state.settings
    return dict(
        items=await list_relations(
            config, secret, settings.database_host_allowlist, settings.database_relation_allowlist
        )
    )


@router.post("/connections/{connection_id}/preview")
async def preview(connection_id: str, body: dict, request: Request):
    check_request(body, "CapturePostgres")
    if body["connection_id"] != connection_id:
        raise Problem("NOT_FOUND", "The connection does not match this request.", 404)
    config, secret = credentials(request, connection_id)
    settings = request.app.state.settings
    return await capture(
        config,
        secret,
        settings.database_host_allowlist,
        settings.database_relation_allowlist,
        body,
        preview=True,
    )


@router.post("/projects/{project_id}/sources/postgres", status_code=202)
def capture_postgres(project_id: str, body: dict, request: Request):
    check_request(body, "CapturePostgres")
    with request.app.state.store.session() as s:
        scoped(s, Project, project_id, lock=True)
        record = scoped(s, Connection, body["connection_id"], project_id)
        password(request.app.state.settings, record)
        if not any(
            p["schema"] == body["schema"]
            and p["relation"] == body["relation"]
            and set(
                body["key_columns"]
                + body["text_columns"]
                + ([body["updated_at_column"]] if body["updated_at_column"] else [])
            )
            <= set(p["columns"])
            for p in policies(record.public_config, request.app.state.settings.database_relation_allowlist)
        ):
            raise Problem(
                "RELATION_DENIED", "The owner has not approved this relation and its selected columns."
            )
        source = Source(
            project_id=project_id,
            kind="postgres",
            display_name=body["display_name"],
            source_metadata=dict(format="postgres", connection_id=record.id, selection=body),
        )
        s.add(source)
        s.flush()
        enqueue(s, project_id, "ingest_source", source)
        return present(s, source)
