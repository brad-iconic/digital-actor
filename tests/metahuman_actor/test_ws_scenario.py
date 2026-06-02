"""Tests for the load_scenario / list_scenarios WS handlers and the
empty-stage state introduced by client-controlled scenario loading."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from metahuman_actor.settings import settings as global_settings

pytestmark = pytest.mark.asyncio

REPO_PROMPTS = Path(".langfuse_prompts/scenarios").resolve()
LLM = "cerebras/qwen-3-235b-a22b-instruct-2507"

# Source scenario that actually exists in the repo. The fixture clones this
# into a tmp tree under both `default` and `alt` names so the tests below can
# operate on those logical names without depending on a `default` scenario on
# disk.
_SRC_SCENARIO = "zeek"


@pytest.fixture(autouse=True)
def _dummy_llm_key(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-dummy-key")


@pytest.fixture(autouse=True)
def _cleanup_mirrored_prompts():
    """Remove any `default`/`alt` prompt dirs left behind by a test."""
    yield
    for name in ("default", "alt"):
        shutil.rmtree(REPO_PROMPTS / name, ignore_errors=True)


class _FakeWS:
    def __init__(self, incoming: list[dict[str, Any]]):
        self._incoming = [json.dumps(m) for m in incoming]
        self.sent: list[dict[str, Any]] = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def _setup(monkeypatch, tmp_path):
    tmp_data = tmp_path / "data_scenarios"
    tmp_data.mkdir()
    shutil.copytree(global_settings.scenarios_path / _SRC_SCENARIO, tmp_data / "default")
    shutil.copytree(global_settings.scenarios_path / _SRC_SCENARIO, tmp_data / "alt")
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)
    # Mirror the prompt tree so Scenario.load can resolve `default` / `alt`.
    # The autouse `_cleanup_mirrored_prompts` fixture removes these after the test.
    for name in ("default", "alt"):
        dst = REPO_PROMPTS / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(REPO_PROMPTS / _SRC_SCENARIO, dst)


def _make_empty_server(monkeypatch, tmp_path):
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage

    _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, tts_enabled=False)
    return MetaHumanServer(stage, port=0, http_port=None)


async def test_list_scenarios_active_is_null_when_empty(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server = _make_empty_server(monkeypatch, tmp_path)
        ws = _FakeWS([{"type": "list_scenarios"}])
        await server._handle_inbound(ws)
        assert len(ws.sent) == 1
        msg = ws.sent[0]
        assert msg["type"] == "scenarios"
        assert msg["active"] is None
        assert "default" in msg["names"]
        assert "alt" in msg["names"]


async def test_load_scenario_from_empty_succeeds(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server = _make_empty_server(monkeypatch, tmp_path)
        ws = _FakeWS([{"type": "load_scenario", "name": "alt"}])
        await server._handle_inbound(ws)
        assert any(
            m.get("type") == "scenario_loaded" and m.get("name") == "alt"
            for m in ws.sent
        )
        assert server._stage.scenario.name == "alt"


async def test_say_rejected_when_no_scenario(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server = _make_empty_server(monkeypatch, tmp_path)
        ws = _FakeWS([{"type": "say", "text": "hello"}])
        await server._handle_inbound(ws)
        assert any(
            m.get("type") == "error"
            and "no scenario loaded" in m.get("message", "")
            for m in ws.sent
        )
        assert server._stage.scenario is None


async def test_start_game_rejected_when_no_scenario(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server = _make_empty_server(monkeypatch, tmp_path)
        ws = _FakeWS([{"type": "start_game"}])
        await server._handle_inbound(ws)
        assert any(
            m.get("type") == "error"
            and "no scenario loaded" in m.get("message", "")
            for m in ws.sent
        )
        assert server._stage.scenario is None


async def test_load_scenario_missing_returns_error_keeps_empty(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server = _make_empty_server(monkeypatch, tmp_path)
        ws = _FakeWS([{"type": "load_scenario", "name": "nope"}])
        await server._handle_inbound(ws)
        assert any(m.get("type") == "error" for m in ws.sent)
        assert server._stage.scenario is None


async def test_load_scenario_empty_name_returns_error(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server = _make_empty_server(monkeypatch, tmp_path)
        ws = _FakeWS([{"type": "load_scenario", "name": "  "}])
        await server._handle_inbound(ws)
        assert any(
            m.get("type") == "error" and "empty name" in m.get("message", "")
            for m in ws.sent
        )
        assert server._stage.scenario is None
