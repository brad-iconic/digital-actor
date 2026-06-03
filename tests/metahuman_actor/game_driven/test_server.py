"""Tests for GameDrivenServer message dispatch using a fake websocket."""
from __future__ import annotations

import json

import pytest

from metahuman_actor.game_driven.scene import FollowupHint
from metahuman_actor.game_driven.server import GameDrivenServer
from metahuman_actor.game_driven.stage import GameDrivenStage

from .conftest import write_scenario_tree


@pytest.fixture(autouse=True)
def _dummy_llm_key(monkeypatch):
    # Constructing GameDrivenStage builds an LLM client which checks for the key.
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, raw: str):
        self.sent.append(json.loads(raw))


@pytest.fixture
def server(local_prompts):
    write_scenario_tree(local_prompts)
    stage = GameDrivenStage(
        llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False
    )
    return GameDrivenServer(stage)


@pytest.mark.asyncio
async def test_list_scenarios_returns_names_and_null_active(server):
    ws = FakeWS()
    await server._handle_message({"type": "list_scenarios"}, ws)
    assert ws.sent[-1]["type"] == "scenarios"
    assert ws.sent[-1]["active"] is None
    assert "tavern" in ws.sent[-1]["names"]


@pytest.mark.asyncio
async def test_respond_before_load_errors(server):
    ws = FakeWS()
    await server._handle_message(
        {"type": "respond", "npc": "zeek", "text": "hi", "world_state": {}}, ws
    )
    assert ws.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_load_scenario_emits_scenario_loaded(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    frame = ws.sent[-1]
    assert frame["type"] == "scenario_loaded"
    assert frame["name"] == "tavern"
    assert frame["scene"] == "scene_1"
    assert frame["interactions"] == {"zeek": "converse"}


@pytest.mark.asyncio
async def test_load_unknown_scenario_errors(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "nope"}, ws)
    assert ws.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_respond_with_followup_emits_hint(server, monkeypatch):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)

    async def fake_respond_with_hint(text, world_state, emotions=None, request_followup_hint=False):
        from digital_actor.dialogue import DialogueLine

        line = DialogueLine(name="Zeek", text="Hi.", line_id="L1")
        hint = FollowupHint(line_id="L1", available=True, suggested_delay_seconds=6.0) if request_followup_hint else None
        return line, hint

    server._stage._scene.respond_with_hint = fake_respond_with_hint  # type: ignore
    await server._handle_message(
        {"type": "respond", "npc": "zeek", "text": "hi", "world_state": {}, "request_followup_hint": True},
        ws,
    )
    hint_frames = [f for f in ws.sent if f["type"] == "followup_hint"]
    assert hint_frames
    assert hint_frames[-1]["line_id"] == "L1"
    assert hint_frames[-1]["available"] is True
    assert hint_frames[-1]["npc"] == "zeek"


@pytest.mark.asyncio
async def test_respond_unknown_npc_errors(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    await server._handle_message(
        {"type": "respond", "npc": "grog", "text": "hi", "world_state": {}}, ws
    )
    assert ws.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_set_scene_emits_scene_changed(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    # scene_2 does not exist in this minimal tree -> error
    await server._handle_message({"type": "set_scene", "scene": "scene_2"}, ws)
    assert ws.sent[-1]["type"] == "error"
