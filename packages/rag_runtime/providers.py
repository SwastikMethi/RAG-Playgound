"""Owner-controlled profiles; credentials never enter portable configuration."""
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .contracts import digest
from .errors import Problem


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    model: str
    operations: list[Literal["generation", "embedding", "tree_selection", "tree_indexing", "reranking"]]
    base_url: str = ""
    api_key_env: str = ""
    kind: Literal["openai", "fixture"] = "openai"
    max_input_tokens: int = Field(8192, ge=256)
    max_output_tokens: int | None = Field(None, ge=64)
    dimensions: int | None = Field(None, ge=1, le=65536)
    tokenizer: str | None = None
    supports_temperature: bool = True
    supports_seed: bool = False
    revision: str = "1"

    @property
    def key(self):
        return os.environ.get(self.api_key_env, "")

    @property
    def unavailable_reason(self):
        if self.kind == "fixture":
            return None
        if not self.key:
            return "Configure the server-side credential for this profile."
        if "embedding" in self.operations and (not self.dimensions or not self.tokenizer):
            return "Embedding dimensions and a compatible tokenizer must be configured."
        return None

    def public(self):
        return dict(id=self.id, label=self.label, models=[self.model], operations=self.operations,
                    available=self.unavailable_reason is None, unavailable_reason=self.unavailable_reason,
                    max_input_tokens=self.max_input_tokens, max_output_tokens=self.max_output_tokens,
                    dimensions=self.dimensions)

    def fingerprint(self):
        return digest(self.model_dump(exclude={"api_key_env", "label"}))


def load_profiles(settings):
    if settings.mode in {"fixture", "test"}:
        return {p.id: p for p in [
            Profile(id="fixture-answer", label="Fixture answer (synthetic)", model="fixture-answer-v1",
                    kind="fixture", operations=["generation", "tree_selection"],
                    max_output_tokens=4096, tokenizer="cl100k_base"),
            Profile(id="fixture-embedding", label="Fixture embeddings (synthetic)", model="fixture-embedding-v1",
                    kind="fixture", operations=["embedding"], dimensions=64, tokenizer="cl100k_base"),
        ]}
    path = Path(settings.profiles_path)
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    profiles = {}
    for raw in (data or {}).get("profiles", []):
        profile = Profile.model_validate(raw)
        url = urlsplit(profile.base_url)
        if profile.kind != "openai" or url.scheme not in {"https", "http"} or not url.hostname:
            raise Problem("VALIDATION_ERROR", "Live profiles require an explicit compatible provider endpoint.")
        if url.username or url.password or url.query or url.fragment or url.hostname not in settings.provider_host_allowlist:
            raise Problem("VALIDATION_ERROR", "Provider endpoint must match the owner allowlist and contain no credentials.")
        if url.hostname in {"169.254.169.254", "100.100.100.200", "metadata.google.internal"}:
            raise Problem("VALIDATION_ERROR", "Metadata service endpoints are not permitted.")
        if profile.id in profiles:
            raise Problem("VALIDATION_ERROR", "Provider profile identifiers must be unique.")
        profiles[profile.id] = profile
    return profiles
