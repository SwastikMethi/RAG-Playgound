from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseRelationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=300)
    port: int = Field(5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=200)
    schema_name: str = Field(alias="schema", min_length=1, max_length=63)
    relation: str = Field(min_length=1, max_length=63)
    columns: list[str] = Field(min_length=1, max_length=100)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore", hide_input_in_errors=True)
    mode: Literal["live", "fixture", "test"] = "live"
    deployment: Literal["local", "hosted"] = "local"
    public_origin: str = ""
    turnstile_site_key: str = ""
    turnstile_secret_key: SecretStr = SecretStr("")
    worker_slots: int = Field(5, ge=1, le=5)
    worker_idle_seconds: int = Field(0, ge=0, le=600)
    worker_max_seconds: int = Field(0, ge=0, le=7200)
    max_projects_per_user: int = Field(5, ge=1)
    max_upload_bytes_per_user: int = Field(500 * 1024**2, ge=1)
    max_artifact_bytes_per_user: int = Field(2 * 1024**3, ge=1)
    max_vectors_per_user: int = Field(100_000, ge=1)
    max_queued_per_user: int = Field(64, ge=1)
    max_queued_jobs: int = Field(256, ge=1)
    min_free_bytes: int = Field(20 * 1024**3, ge=0)
    database_url: str = "postgresql+psycopg://rag:local-development-only@127.0.0.1:6544/ragplayground"
    qdrant_url: str = "http://127.0.0.1:6344"
    qdrant_api_key: SecretStr = SecretStr("")
    artifact_root: Path = Path(".data/artifacts")
    artifact_bucket: str | None = None
    wake_queue_url: str = ""
    aws_region: str = "us-east-1"
    profiles_path: Path = Path("config/profiles.yaml")
    master_key: SecretStr = SecretStr("")
    database_host_allowlist: list[str] = []
    database_relation_allowlist: list[dict] = []
    provider_host_allowlist: list[str] = ["api.openai.com"]
    max_compare_runs: int = Field(2, ge=1, le=2)
    provider_concurrency: int = Field(4, ge=1, le=16)
    embedding_concurrency: int = Field(4, ge=1, le=16)
    lease_seconds: int = Field(30, ge=10)
    heartbeat_seconds: int = Field(5, ge=1)
    parser_timeout_seconds: int = Field(120, ge=1, le=600)
    parser_memory_mb: int = Field(2048, ge=256)
    reranker_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    qdrant_collection_prefix: str = "rag_v1"
    web_dist: Path = Path("apps/web/dist")

    @model_validator(mode="after")
    def hosted_configuration(self):
        if self.deployment == "hosted":
            from urllib.parse import urlsplit
            from cryptography.fernet import Fernet
            url = urlsplit(self.public_origin)
            if (url.scheme != "https" or not url.hostname or url.path or url.query
                    or url.fragment or url.username or url.password):
                raise ValueError("Hosted mode requires an exact HTTPS public origin without a trailing slash.")
            Fernet(self.master_key.get_secret_value().encode())
            if not self.turnstile_site_key or not self.turnstile_secret_key.get_secret_value():
                raise ValueError("Hosted mode requires Turnstile site and secret keys.")
        return self

    @field_validator("database_relation_allowlist")
    @classmethod
    def relation_policy(cls, value):
        return [DatabaseRelationPolicy.model_validate(p).model_dump(by_alias=True) for p in value]
