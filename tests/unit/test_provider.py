import json
from pathlib import Path

import httpx
import pytest

from rag_runtime.errors import Problem
from rag_runtime.providers import Profile


def test_owner_profile_ids_keep_preexisting_saved_configurations_valid():
    from app.settings import Settings
    from rag_runtime.providers import load_profiles
    from rag_runtime.registry import check_config, defaults

    profiles = load_profiles(
        Settings(
            mode="live",
            profiles_path=Path(__file__).parents[2] / "config/profiles.yaml",
            _env_file=None,
        )
    )
    config = defaults("dense", profiles)
    assert config is not None
    config["generation"].update(
        profile_id="openai-answer", model="gpt-4.1-mini-2025-04-14"
    )
    config["embedding"].update(
        profile_id="openai-embedding", model="text-embedding-3-small", dimensions=1536
    )

    check_config(config, profiles, require_available=False, require_local_adapters=False)


def test_historical_profile_ids_resolve_new_models_and_keep_production_bundle_hash():
    from app.settings import Settings
    from rag_runtime.providers import load_profiles
    from rag_runtime.registry import (
        check_config,
        config_profiles,
        preparation_identity,
        resolve_profile,
    )

    profiles = load_profiles(
        Settings(
            mode="live",
            profiles_path=Path(__file__).parents[2] / "config/profiles.yaml",
            _env_file=None,
        )
    )
    config = {
        "schema_version": "1.0.0",
        "technique": "dense",
        "chunking": {
            "strategy": "fixed_tokens",
            "size_tokens": 512,
            "overlap_tokens": 64,
            "tokenizer": "cl100k_base",
            "tokenizer_revision": "0.14.0",
        },
        "embedding": {
            "profile_id": "openai-embedding",
            "model": "text-embedding-3-large",
            "dimensions": 3072,
            "document_prefix": "",
            "query_prefix": "",
        },
        "search": {
            "candidate_k": 20,
            "context_k": 5,
            "bm25": None,
            "dense": {"metric": "cosine", "mode": "exact", "hnsw_ef": None, "min_score": None},
            "rrf": None,
        },
        "reranker": None,
        "parent": None,
        "tree": None,
        "generation": {
            "profile_id": "openai-answer",
            "model": "gpt-6-luna",
            "temperature": 0,
            "max_output_tokens": 512,
            "context_budget_tokens": 3000,
            "prompt_id": "grounded_answer_v1",
            "seed": None,
        },
        "limits": {"lane_timeout_ms": 90000},
    }

    answer = resolve_profile(profiles, "openai-answer", "gpt-6-luna", "generation", False)
    embedding = resolve_profile(
        profiles, "openai-embedding", "text-embedding-3-large", "embedding", False
    )
    assert (answer.id, answer.model) == ("openai-answer", "gpt-6-luna")
    assert (embedding.id, embedding.model, embedding.dimensions) == (
        "openai-embedding",
        "text-embedding-3-large",
        3072,
    )
    assert {
        operation: profile.model
        for operation, profile in config_profiles(config, profiles, False).items()
    } == {
        "generation": "gpt-6-luna",
        "embedding": "text-embedding-3-large",
    }
    check_config(config, profiles, require_available=False, require_local_adapters=False)
    assert preparation_identity(
        config,
        "84e7b529d9f51a8b065579dce6a1bced3eabf025e81c8652bad43b8456c819b6",
        profiles,
    ) == "4b6f51555d4638fa6625cb44a7b9e8e88c1b10101150f77a91513e176623e6d2"


def test_historical_profile_alias_rejects_unknown_ambiguous_and_cross_provider_matches():
    from rag_runtime.registry import resolve_profile

    historical = Profile(
        id="historical",
        label="Historical",
        model="old",
        operations=["generation"],
        kind="fixture",
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    compatible = historical.model_copy(update={"id": "new", "model": "new"})

    exact = historical.model_copy(update={"model": "new"})
    assert resolve_profile(
        {"historical": exact, "duplicate": compatible},
        "historical",
        "new",
        "generation",
        False,
    ) is exact

    with pytest.raises(Problem, match="unavailable or has changed"):
        resolve_profile({"historical": historical}, "missing", "new", "generation", False)
    with pytest.raises(Problem, match="unavailable or has changed"):
        resolve_profile(
            {"historical": historical, "one": compatible, "two": compatible.model_copy(update={"id": "two"})},
            "historical",
            "new",
            "generation",
            False,
        )
    with pytest.raises(Problem, match="unavailable or has changed"):
        resolve_profile(
            {
                "historical": historical,
                "new": compatible.model_copy(
                    update={"kind": "openai", "base_url": "https://api.openai.com/v1"}
                ),
            },
            "historical",
            "new",
            "generation",
            False,
        )


def test_config_profiles_keeps_distinct_models_that_share_a_historical_id():
    from rag_runtime.registry import config_profiles

    historical = Profile(
        id="answer",
        label="Historical",
        model="old",
        operations=["generation", "tree_indexing", "tree_selection"],
        kind="fixture",
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    profiles = {
        "answer": historical,
        "generation": historical.model_copy(
            update={"id": "generation", "model": "luna", "operations": ["generation"]}
        ),
        "index": historical.model_copy(
            update={"id": "index", "model": "sol", "operations": ["tree_indexing"]}
        ),
        "selection": historical.model_copy(
            update={"id": "selection", "model": "astra", "operations": ["tree_selection"]}
        ),
    }
    config = {
        "generation": {"profile_id": "answer", "model": "luna"},
        "embedding": None,
        "tree": {
            "index_profile_id": "answer",
            "index_model": "sol",
            "selection_profile_id": "answer",
            "selection_model": "astra",
        },
    }

    resolved = config_profiles(config, profiles, False)

    assert set(resolved) == {"generation", "tree_indexing", "tree_selection"}
    assert {profile.model for profile in resolved.values()} == {"luna", "sol", "astra"}


def test_export_replay_indexes_duplicate_historical_ids_without_collapsing_models():
    from rag_runtime.export_replay import replay_profiles
    from rag_runtime.registry import resolve_profile

    snapshots = [
        Profile(
            id="answer",
            label=model,
            model=model,
            operations=[operation],
            kind="fixture",
            max_output_tokens=512,
            tokenizer="cl100k_base",
        ).model_dump()
        for model, operation in (
            ("luna", "generation"),
            ("sol", "tree_indexing"),
            ("astra", "tree_selection"),
        )
    ]

    profiles = replay_profiles(snapshots, Profile)

    assert resolve_profile(profiles, "answer", "luna", "generation").model == "luna"
    assert resolve_profile(profiles, "answer", "sol", "tree_indexing").model == "sol"
    assert resolve_profile(profiles, "answer", "astra", "tree_selection").model == "astra"


def test_generation_comparison_treats_only_compatible_profile_aliases_as_equal():
    from app.runs import generation_identity

    historical = Profile(
        id="historical",
        label="Historical",
        model="old",
        operations=["generation"],
        kind="fixture",
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    current = historical.model_copy(update={"id": "current", "model": "new"})
    other_provider = current.model_copy(update={"id": "other", "kind": "openai"})
    profiles = {profile.id: profile for profile in (historical, current, other_provider)}
    generation = {
        "profile_id": "historical",
        "model": "new",
        "temperature": 0,
        "max_output_tokens": 512,
        "context_budget_tokens": 3000,
        "prompt_id": "grounded_answer_v1",
        "seed": None,
    }

    assert generation_identity(generation, profiles) == generation_identity(
        {**generation, "profile_id": "current"}, profiles
    )
    assert generation_identity(generation, profiles) != generation_identity(
        {**generation, "profile_id": "other"}, profiles
    )


@pytest.mark.asyncio
async def test_provider_retries_before_text_but_never_after_partial_answer(monkeypatch):
    from rag_runtime.providers import Gateway

    monkeypatch.setenv("TEST_MODEL_KEY", "secret-never-in-events")
    profile = Profile(
        id="test",
        label="Test",
        model="model",
        operations=["generation"],
        base_url="https://provider.invalid/v1",
        api_key_env="TEST_MODEL_KEY",
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    attempts = []

    def handle(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"message": "private provider detail"}})
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"Hello 🪐"}}]}\n\ndata: [DONE]\n\n'
        )

    gateway = Gateway(transport=httpx.MockTransport(handle))
    config = dict(model="model", temperature=0, max_output_tokens=64, seed=None)
    chunks = [c async for c in gateway.stream(profile, config, [{"role": "user", "content": "hello"}])]
    assert len(attempts) == 2 and "".join(c.get("text", "") for c in chunks) == "Hello 🪐"
    assert "secret-never-in-events" not in str(chunks)
    attempts.clear()

    def broken(request):
        attempts.append(request)
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"Partial"}}]}\n\ndata: broken-json\n\n'
        )

    gateway = Gateway(transport=httpx.MockTransport(broken))
    with pytest.raises(Problem):
        async for _ in gateway.stream(profile, config, [{"role": "user", "content": "hello"}]):
            pass
    assert len(attempts) == 1


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("modern", [False, True])
async def test_completion_options_reach_both_provider_boundaries(monkeypatch, streaming, modern):
    from rag_runtime.providers import Gateway

    monkeypatch.setenv("TEST_MODEL_KEY", "secret-never-in-events")
    options = (
        dict(completion_token_parameter="max_completion_tokens", reasoning_effort="none") if modern else {}
    )
    profile = Profile(
        id="test",
        label="Test",
        model="gpt-6-luna" if modern else "legacy-model",
        operations=["generation", "tree_selection"],
        base_url="https://provider.invalid/v1",
        api_key_env="TEST_MODEL_KEY",
        max_output_tokens=512,
        tokenizer="cl100k_base",
        **options,
    )

    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == profile.model and payload["temperature"] == 0
        assert payload["stream"] is streaming
        if modern:
            assert payload["max_completion_tokens"] == 64 and "max_tokens" not in payload
            assert payload["reasoning_effort"] == "none"
        else:
            assert payload["max_tokens"] == 64 and "max_completion_tokens" not in payload
            assert "reasoning_effort" not in payload
        if streaming:
            assert payload["stream_options"] == {"include_usage": True}
            return httpx.Response(
                200,
                text=(
                    'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
                    'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": '{"ok":true}'}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        )

    gateway = Gateway(transport=httpx.MockTransport(respond))
    messages = [{"role": "user", "content": "Reply OK."}]
    if streaming:
        generation = dict(max_output_tokens=64, temperature=0, seed=None)
        chunks = [c async for c in gateway.stream(profile, generation, messages)]
        assert "".join(c.get("text", "") for c in chunks) == "OK"
        assert chunks[-1]["usage"]["output_tokens"] == 1
    else:
        result = await gateway.complete(profile, messages, max_tokens=64, json_mode=True)
        assert json.loads(result["text"]) == {"ok": True} and result["usage"]["output_tokens"] == 1


@pytest.mark.parametrize(
    "operation,legacy_fingerprint",
    [
        ("generation", "9769ae81c874bd60b5a67fa353c03039cecb92696af4071563136141377fb8ff"),
        ("embedding", "9c7b8627191b6120eb35323dd4a2fed622fa4b63875cfb292f23b84220a246ff"),
    ],
)
def test_default_completion_options_keep_existing_profile_fingerprints(operation, legacy_fingerprint):
    profile = Profile(
        id="test",
        label="Test",
        model="model",
        operations=[operation],
        base_url="https://provider.invalid/v1",
        api_key_env="TEST_MODEL_KEY",
        max_output_tokens=512 if operation == "generation" else None,
        dimensions=3 if operation == "embedding" else None,
        tokenizer="cl100k_base",
    )
    assert profile.fingerprint() == legacy_fingerprint
    if operation == "generation":
        modern = Profile.model_validate(
            {
                **profile.model_dump(),
                "completion_token_parameter": "max_completion_tokens",
                "reasoning_effort": "none",
            }
        )
        assert modern.fingerprint() != legacy_fingerprint
        assert Profile.model_validate(modern.model_dump()).fingerprint() == modern.fingerprint()


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("status", [400, 422])
async def test_rejected_provider_settings_are_actionable_and_redacted(monkeypatch, streaming, status):
    from rag_runtime.providers import Gateway

    monkeypatch.setenv("TEST_MODEL_KEY", "secret-never-in-events")
    profile = Profile(
        id="test",
        label="Test",
        model="model",
        operations=["generation"],
        base_url="https://provider.invalid/v1",
        api_key_env="TEST_MODEL_KEY",
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "error": {
                    "code": "unsupported_parameter",
                    "param": "max_tokens",
                    "message": "private document text and secret-never-in-events",
                }
            },
        )

    gateway = Gateway(transport=httpx.MockTransport(reject))
    with pytest.raises(Problem, match="request settings") as failure:
        if streaming:
            async for _ in gateway.stream(
                profile,
                dict(max_output_tokens=64, temperature=0, seed=None),
                [{"role": "user", "content": "private document text"}],
            ):
                pass
        else:
            await gateway.complete(profile, [{"role": "user", "content": "private document text"}], retries=1)
    assert len(requests) == 1 and not failure.value.retryable
    assert "private document" not in str(failure.value.public())
    assert "secret-never-in-events" not in str(failure.value.public())
