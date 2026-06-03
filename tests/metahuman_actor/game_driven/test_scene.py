"""Unit tests for GameDrivenScene using a stub stage."""
from __future__ import annotations

import pytest

from digital_actor.data_models import PromptInfo
from digital_actor.dialogue import PLAYER_ROLE_NAME, NARRATOR_ROLE_NAME
from digital_actor.messenger import OutboundPayload
from digital_actor.stage_context import set_stage

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene import GameDrivenScene, FollowupHint
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData

from .conftest import write_scenario_tree


class StubStage:
    """Minimal stage_context surface for driving GameDrivenScene in tests."""

    def __init__(self, llm_reply="A canned line."):
        self._llm_reply = llm_reply
        self.elapsed_time = 0.0
        self.tts_client = None  # disables TTS; run_tts emits a single final frame
        self.delivered: list[OutboundPayload] = []
        self.prompts: list[str] = []

    async def llm_acomplete(self, prompt_info: PromptInfo, obs_name="completion") -> str:
        self.prompts.append(prompt_info.prompt)
        return self._llm_reply

    def llm_complete(self, prompt_info: PromptInfo, obs_name="completion") -> str:
        self.prompts.append(prompt_info.prompt)
        return self._llm_reply

    @property
    def scene_data(self):
        return self._scene_data

    def set_scene_data(self, sd):
        self._scene_data = sd

    def deliver_text(self, line, **kwargs):
        self.delivered.append(OutboundPayload(actor_name=line.name, text=line.text, line_id=line.line_id))

    def deliver_speech(self, line, chunk, **kwargs):
        self.delivered.append(
            OutboundPayload(
                actor_name=line.name,
                audio_chunk=chunk,
                line_id=line.line_id,
                is_final_audio=kwargs.get("is_final_audio", False),
            )
        )

    def deliver_event(self, event):
        pass


@pytest.fixture
def scene_and_stage(local_prompts):
    # local_prompts activates local langfuse mode pointed at tmp_path and seeds the
    # dialogue/common/query templates. Build the scenario tree there, then load
    # scene_data through get_prompt.
    write_scenario_tree(local_prompts)
    scenario = GameDrivenScenario.load("tavern")
    scene_data = GameDrivenSceneData.load(
        scenario, scene="scene_1", character="zeek", interaction="converse"
    )
    actor = MetaHumanDigitalActor({"id": "zeek", "display_name": "Zeek"})
    stage = StubStage()
    stage.set_scene_data(scene_data)
    set_stage(stage)
    scene = GameDrivenScene(actor=actor, scene_data=scene_data, suggested_delay_seconds=6.0)
    return scene, stage


@pytest.mark.asyncio
async def test_respond_records_player_and_generates_line(scene_and_stage):
    scene, stage = scene_and_stage
    line = await scene.respond("Hello there", world_state={"time_of_day": "night"})
    roles = [m.name for m in scene.actor.history.messages]
    assert PLAYER_ROLE_NAME in roles
    assert scene.actor.name in roles
    text_frames = [p for p in stage.delivered if p.text is not None]
    assert any(p.text == "A canned line." for p in text_frames)
    assert line.text == "A canned line."


@pytest.mark.asyncio
async def test_respond_prompt_includes_world_state_block(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.respond("Hello", world_state={"time_of_day": "night"})
    assert any("time_of_day: night" in p for p in stage.prompts)


@pytest.mark.asyncio
async def test_respond_empty_text_raises(scene_and_stage):
    scene, stage = scene_and_stage
    with pytest.raises(ValueError):
        await scene.respond("   ", world_state={})


@pytest.mark.asyncio
async def test_trigger_generates_line(scene_and_stage):
    scene, stage = scene_and_stage
    line = await scene.trigger("greet", info={}, world_state={})
    assert line.text == "A canned line."
    assert any("The player approaches" in p for p in stage.prompts)


@pytest.mark.asyncio
async def test_trigger_with_narrator_adds_narrator_line(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.trigger("player_drew_weapon", info={"weapon": "sword"}, world_state={})
    narrator_lines = [m for m in scene.actor.history.messages if m.name == NARRATOR_ROLE_NAME]
    assert any("The player draws their sword." == m.text for m in narrator_lines)


@pytest.mark.asyncio
async def test_trigger_without_narrator_adds_no_narrator_line(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.trigger("greet", info={}, world_state={})
    narrator_lines = [m for m in scene.actor.history.messages if m.name == NARRATOR_ROLE_NAME]
    assert narrator_lines == []


@pytest.mark.asyncio
async def test_unknown_trigger_raises_keyerror(scene_and_stage):
    scene, stage = scene_and_stage
    with pytest.raises(KeyError):
        await scene.trigger("does_not_exist", info={}, world_state={})


@pytest.mark.asyncio
async def test_trigger_prompt_includes_substituted_info(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.trigger("player_drew_weapon", info={"weapon": "axe"}, world_state={})
    assert any("The player drew axe. React." in p for p in stage.prompts)


@pytest.mark.asyncio
async def test_respond_returns_followup_hint_when_requested(scene_and_stage, monkeypatch):
    scene, stage = scene_and_stage

    async def fake_query(prompt_info, obs_name="completion"):
        if obs_name == "query_followup":
            return "YES"
        return "A canned line."

    stage.llm_acomplete = fake_query  # type: ignore[assignment]
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=True
    )
    assert hint is not None
    assert hint.available is True
    assert hint.line_id == line.line_id
    assert hint.suggested_delay_seconds == scene.suggested_delay_seconds


@pytest.mark.asyncio
async def test_respond_no_hint_when_not_requested(scene_and_stage):
    scene, stage = scene_and_stage
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=False
    )
    assert hint is None


@pytest.mark.asyncio
async def test_followup_hint_available_false_when_query_no(scene_and_stage):
    scene, stage = scene_and_stage

    async def fake_query(prompt_info, obs_name="completion"):
        if obs_name == "query_followup":
            return "NO"
        return "A canned line."

    stage.llm_acomplete = fake_query  # type: ignore[assignment]
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=True
    )
    assert hint is not None
    assert hint.available is False


@pytest.mark.asyncio
async def test_followup_query_failure_returns_no_hint(scene_and_stage):
    scene, stage = scene_and_stage

    async def fake_query(prompt_info, obs_name="completion"):
        if obs_name == "query_followup":
            raise RuntimeError("llm down")
        return "A canned line."

    stage.llm_acomplete = fake_query  # type: ignore[assignment]
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=True
    )
    # Query failure is silent: line still produced, no hint.
    assert line.text == "A canned line."
    assert hint is None
