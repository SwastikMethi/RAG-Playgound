from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
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
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")
    app_token: SecretStr
    mode: Literal["live", "fixture", "test"] = "live"
    database_url: str = "postgresql+psycopg://rag:local-development-only@127.0.0.1:6544/ragplayground"
    qdrant_url: str = "http://127.0.0.1:6344"
    artifact_root: Path = Path(".data/artifacts")
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

    @field_validator("database_relation_allowlist")
    @classmethod
    def relation_policy(cls, value):
        return [DatabaseRelationPolicy.model_validate(p).model_dump(by_alias=True) for p in value]

    @field_validator("app_token")
    @classmethod
    def token_length(cls, value):
        if len(value.get_secret_value()) < 24:
            raise ValueError("Set RAG_APP_TOKEN to at least 24 random characters.")
        return value
