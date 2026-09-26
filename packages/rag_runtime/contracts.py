"""Validation reads the authoritative contracts, including external references."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .errors import Problem

CONTRACT_ROOT = Path(__file__).parent / "contracts"
if not CONTRACT_ROOT.exists():
    CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


@lru_cache
def schema_file(name):
    return yaml.safe_load((CONTRACT_ROOT / name).read_text())


@lru_cache
def validator(name, component=None, pointer=None):
    registry = Registry()
    for filename in (
        "pipeline.schema.json",
        "trace-event.schema.json",
        "export-manifest.schema.json",
        "openapi.yaml",
    ):
        registry = registry.with_resource(
            (CONTRACT_ROOT / filename).as_uri(),
            Resource.from_contents(schema_file(filename), default_specification=DRAFT202012),
        )
    target = (CONTRACT_ROOT / name).as_uri()
    if component:
        target += "#/components/schemas/" + component
    elif pointer:
        target += "#" + pointer
    return Draft202012Validator({"$ref": target}, registry=registry, format_checker=FormatChecker())


def validate(value, name="pipeline.schema.json", component=None):
    error = next(validator(name, component).iter_errors(value), None)
    if error:
        # Do not include the rejected value: it can contain credentials or private text.
        raise Problem(
            "VALIDATION_ERROR",
            "The request does not match its contract.",
            details={"field": ".".join(map(str, error.absolute_path)), "rule": error.validator},
        )
    if name == "pipeline.schema.json":
        cfg = value
        if cfg["search"]["context_k"] > cfg["search"]["candidate_k"]:
            raise Problem("VALIDATION_ERROR", "Context passages cannot exceed candidate passages.")
        chunk = cfg["chunking"]
        if chunk and chunk["overlap_tokens"] >= chunk["size_tokens"]:
            raise Problem("VALIDATION_ERROR", "Chunk overlap must be smaller than chunk size.")
        if cfg["parent"] and cfg["parent"]["max_parent_tokens"] <= chunk["size_tokens"]:
            raise Problem("VALIDATION_ERROR", "Parent context must be larger than child chunks.")
    return value


def request(value, component):
    return validate(value, "openapi.yaml", component)
