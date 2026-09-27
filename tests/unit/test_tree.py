import asyncio
from copy import deepcopy
from importlib.metadata import version

import pytest

from rag_runtime.errors import Problem
from rag_runtime.pageindex_adapter import normalize_tree, retrieve_tree
from rag_runtime.providers import Profile, empty_usage
from rag_runtime.trace import Trace
from tests.unit.test_runtime import source


def document():
    src = source("page one\npage two\npage three")
    src["segments"] = [
        dict(start=0, end=9, page=1),
        dict(start=9, end=18, page=2),
        dict(start=18, end=len(src["text"]), page=3),
    ]
    nodes = [
        dict(
            node_id="section-a",
            title="A",
            page_index=1,
            nodes=[
                dict(node_id="a1", title="A1", page_index=1),
                dict(node_id="a2", title="A2", page_index=2),
            ],
        ),
        dict(node_id="section-b", title="B", page_index=3),
    ]
    return dict(
        document_id="doc",
        source=src,
        nodes=normalize_tree(nodes, 3),
        description="Three pages",
        sdk_version=version("pageindex"),
    )


def test_tree_ranges_are_pages_not_node_numbers_and_validate_bounds():
    nodes = document()["nodes"]
    assert nodes[0]["page_end"] == 2 and nodes[0]["children"][0]["page_end"] == 1
    assert nodes[0]["children"][1]["page_end"] == 2 and nodes[1]["page_start"] == 3
    with pytest.raises(Problem):
        normalize_tree([dict(node_id="outside", title="X", page_index=4)], 3)
    with pytest.raises(Problem):
        normalize_tree([dict(node_id="same", page_index=1), dict(node_id="same", page_index=2)], 3)


@pytest.mark.asyncio
async def test_bounded_tree_controller_rejects_invented_ids_repairs_once_and_uses_original_pages():
    document_data = document()
    answers = iter(
        [
            {"ids": ["invented"], "stop": False},
            {"ids": ["section-a"], "stop": False},
            {"ids": ["a2"], "stop": True},
        ]
    )

    class Gateway:
        async def complete(self, profile, messages, **kwargs):
            import json

            return dict(text=json.dumps(next(answers)), usage=empty_usage(), wait_ms=0, recording={})

    profile = Profile(
        id="select",
        label="Test tree selection",
        model="test",
        kind="fixture",
        operations=["tree_selection"],
        tokenizer="cl100k_base",
        max_output_tokens=512,
    )
    config = dict(
        max_documents=3,
        max_depth=4,
        max_nodes=12,
        max_calls=8,
        max_pages=12,
        selection_profile_id="select",
        label="Test tree selection",
        selection_model="test",
    )
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    result = dict(recordings=[], usage=empty_usage(), metrics={"provider_wait_ms": None})
    candidates = await retrieve_tree(
        "Find page two", [document_data], config, {"select": profile}, Gateway(), Trace(emit), None, result
    )
    assert [c["excerpt"] for c in candidates] == ["page two\n"]
    assert candidates[0]["tree_node_ids"] == ["a2"]
    assert len([r for r in result["recordings"] if r["operation"] == "tree_selection"]) == 3
    assert any(p["code"] == "TREE_SELECTION_REPAIR" for k, p in events if k == "warning")
    config["max_calls"] = 1

    class Bad:
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return dict(text="{}", usage=empty_usage(), wait_ms=0, recording={})

    bad = Bad()
    with pytest.raises(Problem, match="selection"):
        await retrieve_tree(
            "X", [document_data], config, {"select": profile}, bad, Trace(emit), None, deepcopy(result)
        )
    assert bad.calls == 1


@pytest.mark.asyncio
async def test_tree_warns_only_when_a_limit_prevents_navigation_or_pages():
    import json

    profile = Profile(id="select", label="Test", model="test", kind="fixture", operations=["tree_selection"], tokenizer="cl100k_base")
    for limit, stop, warning in [("max_depth", False, True), ("max_nodes", False, True), ("max_calls", False, True), ("max_pages", True, True), ("max_calls", True, False)]:
        config = dict(max_documents=3, max_depth=4, max_nodes=12, max_calls=8, max_pages=12, selection_profile_id="select", selection_model="test")
        config[limit] = 1
        events = []

        async def emit(kind, payload):
            events.append((kind, payload))

        class Gateway:
            async def complete(self, *args, **kwargs):
                return dict(text=json.dumps({"ids": ["section-a"], "stop": stop}), usage=empty_usage(), wait_ms=0, recording={})

        result = dict(recordings=[], usage=empty_usage(), metrics={"provider_wait_ms": None})
        candidates = await retrieve_tree("X", [document()], config, {"select": profile}, Gateway(), Trace(emit), None, result)
        warnings = [p for kind, p in events if kind == "warning" and p["code"] == "TREE_BUDGET_REACHED"]
        assert bool(warnings) is warning, limit
        assert len(warnings) <= 1
        assert len(candidates) == (1 if limit == "max_pages" else 2)
        if warning:
            assert limit.removeprefix("max_").rstrip("s") in warnings[0]["message"], limit


@pytest.mark.asyncio
async def test_cancelled_tree_selection_cannot_emit_selection_or_evidence():
    class Slow:
        async def complete(self, *args, **kwargs):
            await asyncio.sleep(30)

    profile = Profile(
        id="select",
        label="Test tree selection", model="test", kind="fixture", operations=["tree_selection"], tokenizer="cl100k_base"
    )
    config = dict(
        max_documents=3,
        max_depth=4,
        max_nodes=12,
        max_calls=8,
        max_pages=12,
        selection_profile_id="select",
        label="Test tree selection",
        selection_model="test",
    )
    events = []

    async def emit(k, p):
        events.append(k)

    task = asyncio.create_task(
        retrieve_tree(
            "X",
            [document()],
            config,
            {"select": profile},
            Slow(),
            Trace(emit),
            None,
            dict(recordings=[], usage=empty_usage(), metrics={"provider_wait_ms": None}),
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "tree.nodes_selected" not in events
    assert events[-1] == "stage.failed"
