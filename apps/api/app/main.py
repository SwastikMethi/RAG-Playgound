import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import func, select, text

from rag_runtime import __version__
from rag_runtime.contracts import digest, request as check_request
from rag_runtime.errors import Problem
from rag_runtime.providers import load_profiles
from rag_runtime.registry import capabilities, check_config
from .database import Store, scoped
from .content import router as content_router
from .runs import router as runs_router
from .cancellation import router as cancellation_router
from .models import Configuration, Project
from .present import present
from .settings import Settings


def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings()
        cfg = app.state.settings
        app.state.profiles = load_profiles(cfg)
        app.state.store = Store(cfg.database_url, cfg.artifact_root, cfg.lease_seconds)
        yield
        app.state.store.engine.dispose()

    app = FastAPI(title="RAG Playground", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        path = request.url.path
        token = app.state.settings.app_token.get_secret_value()
        if path.startswith("/api/") and path != "/api/v1/health":
            value = request.headers.get("authorization", "")
            if not hmac.compare_digest(value.encode(), f"Bearer {token}".encode()):
                return JSONResponse(
                    {"error": Problem("UNAUTHORIZED", "Enter the application token.", 401).public()}, 401
                )
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"error": Problem("FORBIDDEN", "This request must use the same origin.", 403).public()},
                    403,
                )
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                "Cache-Control": "no-store" if path.startswith("/api/") else "no-cache",
            }
        )
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, error):
        return JSONResponse({"error": error.public()}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return JSONResponse({"error": Problem("VALIDATION_ERROR", "Check the request fields.").public()}, 422)

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
            with app.state.store.session() as s:
                s.execute(text("SELECT 1 FROM alembic_version"))
            probe = app.state.store.root / ".readiness"
            probe.write_text("")
            probe.unlink()
            status = "ok"
        except Exception:
            status = "degraded"
        return dict(status=status, version=__version__)

    @app.get("/api/v1/system/profiles")
    def profiles():
        return dict(items=[p.public() for p in app.state.profiles.values()])

    @app.get("/api/v1/system/capabilities")
    def registry():
        return capabilities(app.state.profiles, app.state.settings)

    @app.get("/api/v1/projects")
    def projects():
        with app.state.store.session() as s:
            return dict(
                items=[present(s, p) for p in s.scalars(select(Project).order_by(Project.created_at))]
            )

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: dict):
        check_request(body, "CreateProject")
        if not body["name"].strip():
            raise Problem("VALIDATION_ERROR", "Enter a project name.")
        with app.state.store.session() as s:
            project = Project(name=body["name"].strip())
            s.add(project)
            s.flush()
            return present(s, project)

    @app.get("/api/v1/projects/{project_id}")
    def project(project_id: str):
        with app.state.store.session() as s:
            return present(s, scoped(s, Project, project_id))

    @app.get("/api/v1/projects/{project_id}/configurations")
    def configurations(project_id: str):
        with app.state.store.session() as s:
            scoped(s, Project, project_id)
            return dict(
                items=[
                    present(s, c)
                    for c in s.scalars(
                        select(Configuration)
                        .where(Configuration.project_id == project_id)
                        .order_by(Configuration.created_at)
                    )
                ]
            )

    @app.post("/api/v1/projects/{project_id}/configurations", status_code=201)
    def save_configuration(project_id: str, body: dict):
        check_request(body, "SaveConfiguration")
        check_config(body["config"], app.state.profiles, require_available=False)
        with app.state.store.session() as s:
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
    def configuration(config_id: str):
        with app.state.store.session() as s:
            return present(s, scoped(s, Configuration, config_id))

    app.include_router(content_router)
    app.include_router(runs_router)
    app.include_router(cancellation_router)
    app.mount(
        "/",
        StaticFiles(
            directory=settings.web_dist if settings else Path("apps/web/dist"), html=True, check_dir=False
        ),
        name="web",
    )
    return app


app = create_app()
