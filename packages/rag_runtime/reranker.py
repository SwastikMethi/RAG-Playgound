"""Actual local cross-encoder inference; public assets are installed separately."""

import asyncio
import json
import sys
import time
from pathlib import Path

from .contracts import digest
from .errors import Problem
from .process import run_json

MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
_gates = {}


def unavailable_reason(config):
    if config["model"] != MODEL or config["model_revision"] != REVISION:
        return "Choose the packaged, pinned MiniLM reranker revision."
    if config["max_input_tokens"] > 512:
        return "This cross-encoder supports at most 512 scoring tokens."
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(MODEL, "model.safetensors", revision=REVISION)
    if not isinstance(cached, str):
        return "Install the pinned local reranker weights with tools/prepare_models.py."
    if config["device"] != "cpu":
        import torch

        if not torch.cuda.is_available():
            return "CUDA is unavailable. Choose CPU for the local reranker."
    return None


def score(question, candidates, config):
    reason = unavailable_reason(config)
    if reason:
        raise Problem("MODEL_NOT_READY", reason, 409)
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(
        MODEL,
        revision=REVISION,
        local_files_only=True,
        trust_remote_code=False,
        device=config["device"],
        max_length=config["max_input_tokens"],
        model_kwargs={"use_safetensors": True},
    )
    scores = model.predict(
        [(question, hit["excerpt"]) for hit in candidates], batch_size=16, show_progress_bar=False
    )
    ordered = sorted(zip(candidates, scores), key=lambda pair: (-float(pair[1]), pair[0]["candidate_id"]))
    return [
        dict(hit, rank=i, score=float(value), score_type="reranker")
        for i, (hit, value) in enumerate(ordered, 1)
    ]


def request_hash(question, candidates, config):
    return digest(
        dict(
            question=question,
            config=config,
            candidates=[dict(candidate_id=c["candidate_id"], excerpt=c["excerpt"]) for c in candidates],
        )
    )


async def rerank(question, candidates, config):
    if not candidates:
        return dict(candidates=[], wait_ms=0, recording=None)
    key = id(asyncio.get_running_loop())
    gate = _gates.setdefault(key, asyncio.Semaphore(1))
    began = time.monotonic()
    async with gate:
        wait = (time.monotonic() - began) * 1000
        request = dict(question=question, candidates=candidates, config=config)
        result = await run_json(["-m", "rag_runtime.reranker"], timeout=300, input_data=request)
    return dict(
        candidates=result["candidates"],
        wait_ms=wait,
        recording=dict(
            operation="reranking",
            request_sha256=request_hash(question, candidates, config),
            response=result["candidates"],
        ),
    )


if __name__ == "__main__":
    try:
        request = json.loads(Path(sys.argv[1]).read_text())
        print(json.dumps(dict(candidates=score(**request))))
    except Problem as exc:
        print(json.dumps(dict(error=exc.public())))
        sys.exit(1)
