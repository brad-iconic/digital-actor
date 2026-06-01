"""Tests for the load_scenario / list_scenarios WS handlers."""
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


@pytest.fixture(autouse=True)
def _dummy_llm_key(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-dummy-key")


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
    shutil.copytree(global_settings.scenarios_path / "default", tmp_data / "default")
    shutil.copytree(global_settings.scenarios_path / "default", tmp_data / "alt")
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)
    # Mirror the prompt tree for `alt`.
    dst_alt = REPO_PROMPTS / "alt"
    if dst_alt.exists():
        shutil.rmtree(dst_alt)
    shutil.copytree(REPO_PROMPTS / "default", dst_alt)
    return dst_alt


def _make_server(monkeypatch, tmp_path):
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage

    dst_alt = _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, scenario_name="default", tts_enabled=False)
    server = MetaHumanServer(stage, port=0, http_port=None)
    return server, dst_alt


async def test_list_scenarios_returns_names_and_active(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server, dst_alt = _make_server(monkeypatch, tmp_path)
        try:
            ws = _FakeWS([{"type": "list_scenarios"}])
            await server._handle_inbound(ws)
            assert len(ws.sent) == 1
            msg = ws.sent[0]
            assert msg["type"] == "scenarios"
            assert "default" in msg["names"]
            assert "alt" in msg["names"]
            assert msg["active"] == "default"
        finally:
            shutil.rmtree(dst_alt, ignore_errors=True)


async def test_load_scenario_success(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server, dst_alt = _make_server(monkeypatch, tmp_path)
        try:
            ws = _FakeWS([{"type": "load_scenario", "name": "alt"}])
            await server._handle_inbound(ws)
            assert any(
                m.get("type") == "scenario_loaded" and m.get("name") == "alt"
                for m in ws.sent
            )
            assert server._stage.scenario.name == "alt"
        finally:
            shutil.rmtree(dst_alt, ignore_errors=True)


async def test_load_scenario_missing_returns_error(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        server, dst_alt = _make_server(monkeypatch, tmp_path)
        try:
            ws = _FakeWS([{"type": "load_scenario", "name": "nope"}])
            await server._handle_inbound(ws)
            assert any(m.get("type") == "error" for m in ws.sent)
            assert server._stage.scenario.name == "default"
        finally:
            shutil.rmtree(dst_alt, ignore_errors=True)
