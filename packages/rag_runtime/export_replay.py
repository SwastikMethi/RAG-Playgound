"""Private offline verification. Recorded responses never enter production queries."""

from copy import deepcopy
from .contracts import digest
from .errors import Problem
from .providers import Profile, Gateway, empty_usage
from .runtime import execute
from .vectors import Scope, VectorStore


class RecordedProfile(Profile):
    @property
    def unavailable_reason(self):
        return None  # Only used with RecordedGateway below; it has no network implementation.


class RecordedGateway:
    def __init__(self, records):
        self.records = deepcopy(records)
        self.used = set()

    def take(self, operation, field, value):
        for i, record in enumerate(self.records):
            if i not in self.used and record["operation"] == operation and record.get(field) == value:
                self.used.add(i)
                return record
        raise Problem("REPLAY_MISMATCH", "A recorded external response does not match the replay request.")

    async def embed(self, profile, inputs):
        record = self.take("embedding", "request_sha256", digest(inputs))
        if record["profile_fingerprint"] != profile.fingerprint():
            raise Problem("REPLAY_MISMATCH", "The recorded embedding profile changed.")
        return dict(vectors=record["response"], wait_ms=0, usage=empty_usage(), recording=record)

    async def complete(self, profile, messages, **options):
        record = self.take("tree_selection", "input_sha256", digest(messages))
        return dict(text=record["text"], usage=record["usage"], wait_ms=0, recording=record)

    async def stream(self, profile, config, messages):
        record = self.take("generation", "request_sha256", digest(dict(config=config, messages=messages)))
        if record["profile_fingerprint"] != profile.fingerprint():
            raise Problem("REPLAY_MISMATCH", "The recorded answer profile changed.")
        # Exercise assembly over multiple Unicode-safe deltas, independent of original coalescing.
        for start in range(0, len(record["response"]), 31):
            yield dict(text=record["response"][start : start + 31])
        yield dict(usage=record["usage"])

    async def rerank(self, question, candidates, config):
        from .reranker import request_hash

        if not candidates:
            return dict(candidates=[], wait_ms=0, recording=None)
        record = self.take("reranking", "request_sha256", request_hash(question, candidates, config))
        return dict(candidates=record["response"], wait_ms=0, recording=record)


def evidence_identity(items):
    return [
        {
            k: e[k]
            for k in (
                "candidate_id",
                "evidence_id",
                "source_id",
                "source_name",
                "excerpt",
                "location",
                "label",
                "included_in_context",
            )
        }
        for e in items
    ]


def replay_profiles(raw_profiles, cls):
    profiles = {}
    for i, raw in enumerate(raw_profiles):
        key = raw["id"] if raw["id"] not in profiles else f"{raw['id']}:{i}"
        profiles[key] = cls.model_validate(raw)
    return profiles


async def verify_replay(request):
    offline = request["mode"] == "offline"
    config, prepared = request["config"], request["prepared"]
    cls = RecordedProfile if offline else Profile
    profiles = replay_profiles(request["profiles"], cls)
    gateway = RecordedGateway(request["recordings"]) if offline else Gateway()
    vector_store = VectorStore(":memory:") if config["embedding"] else None
    try:
        if vector_store:
            await vector_store.put(
                Scope(**prepared["scope"]),
                prepared["chunks"],
                prepared["vectors"],
                config["embedding"]["dimensions"],
            )

        async def emit(kind, payload):
            pass

        options = dict(rerank_fn=gateway.rerank) if offline else {}
        result = await execute(
            request["question"],
            config,
            prepared,
            profiles,
            gateway,
            emit,
            vector_store=vector_store,
            **options,
        )
        evidence_matches = evidence_identity(result["evidence"]) == evidence_identity(request["evidence"])
        answer_matches = result["answer"] == request["answer"]
        if offline and (not evidence_matches or not answer_matches):
            raise Problem(
                "REPLAY_MISMATCH",
                "Replayed evidence, source mapping or answer assembly differs from the saved lane.",
            )
        if offline and len(gateway.used) != len(gateway.records):
            raise Problem("REPLAY_MISMATCH", "The replay did not consume every recorded external boundary.")
        return dict(
            evidence_matches=evidence_matches,
            answer_matches=answer_matches,
            boundaries=sorted({r["operation"] for r in request["recordings"]}),
            answer_sha256=digest(result["answer"].encode()),
            evidence_sha256=digest(evidence_identity(result["evidence"])),
        )
    finally:
        if vector_store:
            vector_store.close()
