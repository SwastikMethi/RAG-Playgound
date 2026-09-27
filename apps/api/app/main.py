import time
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import func, select, text

from rag_runtime import __version__
from rag_runtime.contracts import digest, request as check_request
from rag_runtime.errors import Problem
from rag_runtime.operational import log_event
from rag_runtime.providers import load_profiles
from rag_runtime.registry import capabilities, check_config
from .database import Store, scoped
from .content import router as content_router
from .runs import router as runs_router
from .cancellation import router as cancellation_router
from .connections import router as connections_router
from .exports import router as exports_router
from .deletion import router as deletion_router
from .models import Configuration, Project
from .present import page_records, present
from .settings import Settings
from .security import BoundedBody
from . import auth


def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings()
        cfg = app.state.settings
        app.state.profiles = load_profiles(cfg)
        app.state.store = Store(cfg.database_url, cfg.artifact_root, cfg.lease_seconds, cfg)
        app.state.dummy_password_hash = auth.hash_password("unavailable-account-placeholder")
        yield
        app.state.store.engine.dispose()

    app = FastAPI(title="RAG Playground", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        started, request_id = time.monotonic(), str(uuid4())
        path = request.url.path
        cfg = app.state.settings
        if path.startswith("/api/") and path != "/api/v1/health":
            origin = request.headers.get("origin")
            expected = cfg.public_origin if cfg.deployment == "hosted" else str(request.base_url).rstrip("/")
            if ((origin and origin.rstrip("/") != expected) or
                    (cfg.deployment == "hosted" and request.method not in {"GET", "HEAD", "OPTIONS"} and origin != expected)):
                return JSONResponse(
                    {"error": Problem("FORBIDDEN", "This request must use the same origin.", 403).public()},
                    403,
                )
        try:
            if path.startswith("/api/"):
                await run_in_threadpool(auth.request_identity, request)
            response = await call_next(request)
        except Problem as error:
            response = JSONResponse({"error": error.public()}, status_code=error.status)
        if path.startswith("/api/"):
            log_event(
                "http",
                request_id=request_id,
                route=getattr(request.scope.get("route"), "path", "unmatched"),
                method=request.method,
                status=response.status_code,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                "Cache-Control": "no-store" if path.startswith("/api/") else "no-cache",
            }
        )
        if path in {"/login", "/signup", "/recover"}:
            response.headers["Content-Security-Policy"] = response.headers["Content-Security-Policy"].replace("script-src 'self'", "script-src 'self' https://challenges.cloudflare.com") + "; frame-src https://challenges.cloudflare.com"
        return response

    app.add_middleware(BoundedBody)

    @app.exception_handler(Problem)
    async def problem_handler(request, error):
        return JSONResponse({"error": error.public()}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return JSONResponse({"error": Problem("VALIDATION_ERROR", "Check the request fields.").public()}, 422)

    @app.exception_handler(TimeoutError)
    async def timeout_handler(request, error):
        return JSONResponse(
            {
                "error": Problem(
                    "DATABASE_TIMEOUT", "The database operation exceeded its time limit."
                ).public()
            },
            422,
        )

    @app.exception_handler(Exception)
    async def internal_handler(request, error):
        # No provider bodies, documents, passwords or exception reprs in operational responses.
        return JSONResponse(
            {
                "error": Problem(
                    "INTERNAL_ERROR", "The operation failed. Check service readiness.", 500
                ).public()
            },
            500,
        )

    @app.get("/api/v1/health")
    def health():
        return dict(status="ok", version=__version__)

    @app.get("/api/v1/system/readiness")
    def readiness():
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            with app.state.store.session() as s:
                versions = set(s.scalars(text("SELECT version_num FROM alembic_version")))
                if versions != set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads()):
                    raise RuntimeError("Migrations pending")
            probe = app.state.store.root / ".readiness"
            probe.write_text("")
            probe.unlink()
            status = "ok"
        except Exception:
            status = "degraded"
        return dict(status=status, version=__version__)

    @app.get("/api/v1/system/profiles")
    def profiles(request: Request):
        return dict(items=[p.public() for p in request.state.profiles.values()])

    @app.get("/api/v1/system/capabilities")
    def registry(request: Request):
        return capabilities(request.state.profiles, app.state.settings)

    @app.get("/api/v1/projects")
    def projects(request: Request, limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None, max_length=200)):
        with request.state.store.session() as s:
            query = select(Project)
            if request.state.store.owner_id is not None:
                query = query.where(Project.owner_id == request.state.store.owner_id)
            return page_records(s, query, Project, limit, cursor)

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: dict, request: Request):
        check_request(body, "CreateProject")
        if not body["name"].strip():
            raise Problem("VALIDATION_ERROR", "Enter a project name.")
        with request.state.store.session() as s:
            project = Project(name=body["name"].strip(), owner_id=request.state.store.owner_id)
            s.add(project)
            s.flush()
            return present(s, project)

    @app.get("/api/v1/projects/{project_id}")
    def project(project_id: str, request: Request):
        with request.state.store.session() as s:
            return present(s, scoped(s, Project, project_id))

    @app.get("/api/v1/projects/{project_id}/configurations")
    def configurations(
        project_id: str,
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None, max_length=200),
    ):
        with request.state.store.session() as s:
            scoped(s, Project, project_id)
            return page_records(
                s,
                select(Configuration).where(Configuration.project_id == project_id),
                Configuration,
                limit,
                cursor,
            )

    @app.post("/api/v1/projects/{project_id}/configurations", status_code=201)
    def save_configuration(project_id: str, body: dict, request: Request):
        check_request(body, "SaveConfiguration")
        check_config(body["config"], request.state.profiles, require_available=False)
        with request.state.store.session() as s:
            scoped(s, Project, project_id, lock=True)
            config = Configuration(
                project_id=project_id,
                name=body["name"],
                config=body["config"],
                config_sha256=digest(body["config"]),
            )
            if body.get("based_on_config_id"):
                prior = scoped(s, Configuration, body["based_on_config_id"], project_id)
                config.family_id, config.based_on_config_id = prior.family_id, prior.id
                config.revision = 1 + s.scalar(
                    select(func.max(Configuration.revision)).where(
                        Configuration.family_id == prior.family_id, Configuration.project_id == project_id
                    )
                )
            s.add(config)
            s.flush()
            return present(s, config)

    @app.get("/api/v1/configurations/{config_id}")
    def configuration(config_id: str, request: Request):
        with request.state.store.session() as s:
            return present(s, scoped(s, Configuration, config_id))

    app.include_router(auth.router)

    @app.get("/login", include_in_schema=False)
    @app.get("/signup", include_in_schema=False)
    @app.get("/recover", include_in_schema=False)
    def auth_page():
        return FileResponse(app.state.settings.web_dist / "index.html")

    app.include_router(content_router)
    app.include_router(runs_router)
    app.include_router(cancellation_router)
    app.include_router(connections_router)
    app.include_router(exports_router)
    app.include_router(deletion_router)
    app.mount(
        "/",
        StaticFiles(
            directory=settings.web_dist if settings else Path("apps/web/dist"), html=True, check_dir=False
        ),
        name="web",
    )
    return app


app = create_app()
