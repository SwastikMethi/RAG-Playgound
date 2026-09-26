#!/usr/bin/env python3
"""Validate this specification pack and its synthetic examples.

Requires PyYAML for OpenAPI reading. If jsonschema and openapi-spec-validator
are installed, also use their standards-based validators. The built-in checker
supports only the JSON Schema keywords used by this pack and rejects unknown
validation keywords; it is not a general JSON Schema implementation.
"""
from __future__ import annotations
import argparse
import ast
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

try:
    import yaml
except ImportError:
    raise SystemExit("Install PyYAML, or run: pip install -r tools/requirements.txt")

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / "contracts"
CACHE = {}

class ValidationError(ValueError):
    pass

def ensure(condition, message):
    if not condition:
        raise ValidationError(message)

def load(path):
    path = Path(path).resolve()
    if path not in CACHE:
        text = path.read_text(encoding="utf-8")
        CACHE[path] = yaml.safe_load(text) if path.suffix in {".yaml", ".yml"} else json.loads(text)
    return CACHE[path]

def resolve(reference, base):
    path_part, _, fragment = reference.partition("#")
    ensure(not re.match(r"^[a-zA-Z]+:", path_part), "Remote schema references are not allowed in this pack")
    target = (base.parent / path_part).resolve() if path_part else base
    ensure(target.is_relative_to(ROOT), "Schema reference leaves the pack")
    node = load(target)
    if fragment:
        ensure(fragment.startswith("/"), "Only JSON Pointer fragments are used in this pack")
        for part in fragment[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            node = node[int(part)] if isinstance(node, list) else node[part]
    return node, target

KEYWORDS = {
    "$schema", "$ref", "$defs", "title", "description", "type", "properties",
    "required", "additionalProperties", "items", "minItems", "maxItems",
    "uniqueItems", "minLength", "maxLength", "pattern", "minimum", "maximum",
    "enum", "const", "anyOf", "allOf", "if", "then", "else", "format",
    "default", "writeOnly", "readOnly", "examples"
}

def check_schema_shape(schema, base):
    if isinstance(schema, bool):
        return
    ensure(isinstance(schema, dict), f"Invalid schema node in {base.name}")
    ensure(not set(schema) - KEYWORDS, f"Unsupported schema keywords: {set(schema) - KEYWORDS}")
    if "$ref" in schema:
        resolve(schema["$ref"], base)
    if "required" in schema:
        ensure(len(schema["required"]) == len(set(schema["required"])), "Duplicate required fields")
        if "properties" in schema:
            ensure(set(schema["required"]) <= set(schema["properties"]), "Required field missing from properties")
    for key in ("properties", "$defs"):
        for child in schema.get(key, {}).values():
            check_schema_shape(child, base)
    for key in ("items", "additionalProperties", "if", "then", "else"):
        if isinstance(schema.get(key), (dict, bool)):
            check_schema_shape(schema[key], base)
    for key in ("allOf", "anyOf"):
        for child in schema.get(key, []):
            check_schema_shape(child, base)

def matches_type(value, name):
    return {
        "null": value is None,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }[name]

def validate(value, schema, base, path="$"):
    if schema is True:
        return
    if schema is False:
        raise ValidationError(f"{path}: forbidden value")
    if "$ref" in schema:
        target, target_file = resolve(schema["$ref"], base)
        validate(value, target, target_file, path)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ensure(any(matches_type(value, name) for name in names), f"{path}: expected type {names}")
    if "const" in schema:
        ensure(value == schema["const"], f"{path}: wrong constant")
    if "enum" in schema:
        ensure(value in schema["enum"], f"{path}: value outside enum")
    for child in schema.get("allOf", []):
        validate(value, child, base, path)
    if "anyOf" in schema:
        errors = []
        for child in schema["anyOf"]:
            try:
                validate(value, child, base, path)
                break
            except ValidationError as exc:
                errors.append(str(exc))
        else:
            raise ValidationError(f"{path}: no anyOf branch matched: {errors[:2]}")
    if "if" in schema:
        try:
            validate(value, schema["if"], base, path)
            branch = "then"
        except ValidationError:
            branch = "else"
        if branch in schema:
            validate(value, schema[branch], base, path)
    if isinstance(value, dict):
        for required in schema.get("required", []):
            ensure(required in value, f"{path}: missing {required}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                validate(item, props[key], base, f"{path}.{key}")
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                ensure(extra is not False, f"{path}: unknown property {key}")
                if isinstance(extra, dict):
                    validate(item, extra, base, f"{path}.{key}")
    if isinstance(value, list):
        ensure(len(value) >= schema.get("minItems", 0), f"{path}: too few items")
        ensure(len(value) <= schema.get("maxItems", float("inf")), f"{path}: too many items")
        if schema.get("uniqueItems"):
            ensure(len({json.dumps(v, sort_keys=True) for v in value}) == len(value), f"{path}: duplicate items")
        if "items" in schema:
            for index, item in enumerate(value):
                validate(item, schema["items"], base, f"{path}[{index}]")
    if isinstance(value, str):
        ensure(len(value) >= schema.get("minLength", 0), f"{path}: too short")
        ensure(len(value) <= schema.get("maxLength", float("inf")), f"{path}: too long")
        if "pattern" in schema:
            ensure(re.search(schema["pattern"], value) is not None, f"{path}: pattern mismatch")
        if schema.get("format") == "date-time":
            try:
                ensure(datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None, f"{path}: missing timezone")
            except ValueError as exc:
                raise ValidationError(f"{path}: invalid date-time") from exc
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ensure(value >= schema.get("minimum", -float("inf")), f"{path}: below minimum")
        ensure(value <= schema.get("maximum", float("inf")), f"{path}: above maximum")

def walk_refs(value, base):
    if isinstance(value, dict):
        if "$ref" in value:
            resolve(value["$ref"], base)
        for child in value.values():
            walk_refs(child, base)
    elif isinstance(value, list):
        for child in value:
            walk_refs(child, base)

def expect_invalid(value, schema, base):
    try:
        validate(value, schema, base)
    except ValidationError:
        return
    raise ValidationError("An intentionally invalid example was accepted")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    checks = []
    expected_docs = [
        "README.md", "AGENTS.md", "CODEX_START_PROMPT.md",
        "docs/01_PRODUCT_REQUIREMENTS.md", "docs/02_USER_EXPERIENCE.md",
        "docs/03_ARCHITECTURE.md", "docs/04_RETRIEVAL_TECHNIQUES.md",
        "docs/05_DATA_AND_INDEXING.md", "docs/06_API_AND_EVENTS.md",
        "docs/07_TIMING_AND_REPLAY.md", "docs/08_CODE_EXPORT.md",
        "docs/09_SECURITY_AND_OPERATIONS.md", "docs/10_IMPLEMENTATION_PLAN.md",
        "docs/11_ACCEPTANCE_TESTS.md", "docs/12_DECISIONS_AND_SOURCES.md",
        "docs/13_DESIGN_AND_SIMULATION_STANDARDS.md",
    ]
    for name in expected_docs:
        ensure((ROOT/name).is_file(), f"Missing {name}")
    checks.append("Required implementation documents exist")
    for file in [ROOT / name for name in expected_docs] + list((ROOT/"fixtures").rglob("*.md")) + list((C/"examples").glob("*.md")):
        text = file.read_text()
        ensure(text.strip(), f"Empty Markdown file: {file}")
        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = (file.parent/target.split("#",1)[0]).resolve()
            ensure(path.exists(), f"Broken local link: {file.name} -> {target}")
    checks.append("Markdown local links resolve")
    ast.parse((ROOT/"tools/validate_pack.py").read_text())
    checks.append("Included Python validator parses")
    schemas = {}
    for file in C.glob("*.schema.json"):
        schema = load(file)
        ensure(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", "Wrong schema dialect")
        check_schema_shape(schema, file)
        walk_refs(schema, file)
        schemas[file.name] = schema
    checks.append("Schema keyword shapes and local references are consistent")
    examples = []
    techniques = set()
    for file in sorted((C/"examples").glob("pipeline-*.json")):
        cfg = load(file)
        validate(cfg, schemas["pipeline.schema.json"], C/"pipeline.schema.json")
        ensure(cfg["search"]["context_k"] <= cfg["search"]["candidate_k"], "context_k exceeds candidate_k")
        if cfg["chunking"]:
            ensure(cfg["chunking"]["overlap_tokens"] < cfg["chunking"]["size_tokens"], "Chunk overlap is invalid")
        if cfg["parent"]:
            ensure(cfg["parent"]["max_parent_tokens"] > cfg["chunking"]["size_tokens"], "Parent is not larger than child")
        techniques.add(cfg["technique"])
        examples.append((cfg, C/"pipeline.schema.json"))
    ensure(techniques == {"bm25","dense","hybrid","hybrid_rerank","parent_child","pageindex"}, "Six techniques are not covered")
    checks.append("Six configurations satisfy schemas and cross-field limits")
    invalid = copy.deepcopy(load(C/"examples/pipeline-bm25.json"))
    invalid["embedding"] = copy.deepcopy(load(C/"examples/pipeline-dense.json")["embedding"])
    expect_invalid(invalid, schemas["pipeline.schema.json"], C/"pipeline.schema.json")
    invalid = copy.deepcopy(load(C/"examples/pipeline-dense.json"))
    invalid["unknown_field"] = True
    expect_invalid(invalid, schemas["pipeline.schema.json"], C/"pipeline.schema.json")
    invalid = copy.deepcopy(load(C/"examples/pipeline-pageindex.json"))
    invalid["tree"]["max_calls"] = 99
    expect_invalid(invalid, schemas["pipeline.schema.json"], C/"pipeline.schema.json")
    checks.append("Invalid technique fields, unknown properties and call caps are rejected")
    api_path = C/"openapi.yaml"
    api = load(api_path)
    ensure(api["openapi"] == "3.1.0", "Wrong OpenAPI version")
    walk_refs(api, api_path)
    for schema in api["components"]["schemas"].values():
        check_schema_shape(schema, api_path)
    operation_ids = set()
    for path, item in api["paths"].items():
        for method, op in item.items():
            ensure(method in {"get","post","put","delete","patch"}, "Unexpected operation method")
            ensure(op["operationId"] not in operation_ids, "Duplicate operationId")
            operation_ids.add(op["operationId"])
            path_vars = set(re.findall(r"{([^}]+)}",path))
            declared = {p["name"] for p in op.get("parameters",[]) if p["in"] == "path"}
            ensure(path_vars == declared, f"Path parameter mismatch: {path}")
            ensure(all(p["required"] for p in op.get("parameters",[]) if p["in"] == "path"), "Optional path parameter")
            ensure(any(code.startswith("2") for code in op["responses"]), f"No success response: {path}")
            if path != "/health":
                ensure(op.get("security",api["security"]), f"Unprotected endpoint: {path}")
    req = load(C/"examples/create-run.json")
    validate(req, api["components"]["schemas"]["CreateRun"], api_path)
    checks.append("OpenAPI operations, parameters, authorization and references are internally consistent")
    manifest = load(ROOT/"fixtures/source-manifest.json")
    source_map = {}
    for source in manifest["sources"]:
        path = ROOT/source["path"]
        ensure(hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"], "Source hash mismatch")
        source_map[source["source_id"]] = path.read_text()
    for question in load(ROOT/"fixtures/questions.json")["questions"]:
        for source in question["source_paths"]:
            ensure((ROOT/source).is_file(), "Question source is missing")
    checks.append("Synthetic source hashes and question references match files")
    events = [json.loads(line) for line in (C/"examples/sample-events.jsonl").read_text().splitlines() if line.strip()]
    answers, spans, lane_start, lane_terminal, first_delta, contexts = {}, {}, {}, {}, {}, {}
    final_kinds = {}
    run_id = events[0]["run_id"]
    prior_ms = -1
    for seq, event in enumerate(events,1):
        validate(event, schemas["trace-event.schema.json"], C/"trace-event.schema.json")
        ensure(event["seq"] == seq and event["event_id"] == f"{run_id}:{seq}", "Trace sequence/ID mismatch")
        ensure(event["run_id"] == run_id, "Mixed run IDs")
        ensure(event["elapsed_ms"] >= prior_ms, "Trace clock goes backward")
        prior_ms = event["elapsed_ms"]
        lane, typ, payload, ms = event["lane_id"], event["type"], event["payload"], event["elapsed_ms"]
        if typ == "lane.started":
            ensure(lane not in lane_start, "Lane started twice")
            lane_start[lane] = ms
            answers[lane] = ""
        if lane:
            ensure(lane in lane_start and lane not in lane_terminal, "Event outside active lane")
        if typ == "stage.started":
            key = (lane,payload["span_id"])
            ensure(key not in spans, "Repeated span identity")
            if payload["parent_span_id"]:
                ensure((lane,payload["parent_span_id"]) in spans, "Missing parent span")
            spans[key] = {"start":ms,"stage":payload["stage"],"end":None}
        if typ == "stage.completed":
            state = spans[(lane,payload["span_id"])]
            ensure(state["end"] is None and state["stage"] == payload["stage"], "Bad span completion")
            ensure(abs(ms-state["start"]-payload["duration_ms"]) < 0.001, "Fixture span timing mismatch")
            state["end"] = ms
        if typ in {"retrieval.candidates","context.selected"}:
            evidence = payload.get("candidates",payload.get("evidence",[]))
            for item in evidence:
                location = item["location"]
                source = source_map[item["source_id"]]
                ensure(source[location["char_start"]:location["char_end"]] == item["excerpt"], "Evidence span differs from source")
            if typ == "context.selected":
                contexts[lane] = {item["label"] for item in evidence}
                ensure(payload["token_count"] <= payload["budget_tokens"], "Context budget exceeded")
        if typ == "answer.delta":
            ensure(len(answers[lane]) == payload["offset_chars"], "Answer offset mismatch")
            answers[lane] += payload["text"]
            first_delta.setdefault(lane,ms)
        if typ == "answer.completed":
            ensure(hashlib.sha256(answers[lane].encode()).hexdigest() == payload["text_sha256"], "Answer hash mismatch")
            ensure(set(payload["valid_citation_labels"]) <= contexts[lane], "Citation absent from context")
            final_kinds[lane] = payload["answer_kind"]
        if typ == "lane.completed":
            ensure(payload["answer_kind"] == final_kinds[lane], "Answer kind mismatch")
            ensure(payload["metrics"]["total_ms"] == ms-lane_start[lane], "Lane total mismatch")
            ensure(payload["metrics"]["ttft_ms"] == first_delta[lane]-lane_start[lane], "TTFT mismatch")
            lane_terminal[lane] = ms
    ensure(events[-1]["type"] == "run.completed", "Missing terminal run event")
    ensure(set(lane_start) == set(lane_terminal), "Unfinished fixture lane")
    ensure(all(state["end"] is not None for state in spans.values()), "Unfinished fixture span")
    ensure(set(events[-1]["payload"]["lane_ids"]) == set(lane_terminal), "Final lane IDs differ")
    checks.append("45 synthetic trace events satisfy shapes, lifecycle, timings, sources, citations and answer hashes")
    export_path = C/"examples/sample-export-manifest.json"
    export = load(export_path)
    validate(export, schemas["export-manifest.schema.json"], C/"export-manifest.schema.json")
    ensure(all(v["status"] == "not_run" for v in export["verification"].values()), "Example claims unperformed verification")
    cfg = load(C/"examples/pipeline-hybrid_rerank.json")
    expected_hash = hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    ensure(export["pipeline_sha256"] == expected_hash, "Export pipeline hash mismatch")
    checks.append("Export example preserves configuration hash and makes no verification claims")
    engine = "built_in_pack_schema_subset"
    standard_openapi = "not_run_dependency_unavailable"
    try:
        import jsonschema
    except ImportError:
        pass
    else:
        for name,schema in schemas.items():
            jsonschema.Draft202012Validator.check_schema(schema)
        examples += [(e,C/"trace-event.schema.json") for e in events]
        examples.append((export,C/"export-manifest.schema.json"))
        for example,file in examples:
            schema = load(file)
            resolver = jsonschema.RefResolver(base_uri=file.as_uri(),referrer=schema)
            jsonschema.Draft202012Validator(schema,resolver=resolver,format_checker=jsonschema.FormatChecker()).validate(example)
        engine = "jsonschema_draft202012_plus_pack_semantics"
        checks.append("Standard JSON Schema meta-validation and example validation passed")
    try:
        from openapi_spec_validator import validate as validate_openapi
    except ImportError:
        pass
    else:
        validate_openapi(api,base_uri=api_path.as_uri())
        standard_openapi = "passed"
        checks.append("Standard OpenAPI validation passed")
    report = {
        "status":"passed",
        "scope":"Implementation documentation, contracts and synthetic fixtures only; no application is implemented or benchmarked.",
        "schema_engine":engine,
        "standard_openapi_validation":standard_openapi,
        "implementation_documents":len(expected_docs),
        "pipeline_examples":len(techniques),
        "trace_events":len(events),
        "api_operations":len(operation_ids),
        "checks":checks,
    }
    if args.report:
        args.report.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))

if __name__ == "__main__":
    try:
        main()
    except (ValidationError, KeyError, ValueError, OSError) as exc:
        print(f"VALIDATION FAILED: {exc}",file=sys.stderr)
        raise SystemExit(1)
