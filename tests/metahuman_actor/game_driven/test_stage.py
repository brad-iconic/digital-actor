"""Tests for GameDrivenStage lifecycle and switching (TTS disabled)."""
from __future__ import annotations

import pytest

from metahuman_actor.game_driven.stage import GameDrivenStage

from .conftest import write_scenario_tree


@pytest.fixture(autouse=True)
def _dummy_llm_key(monkeypatch):
    # SingleSceneStage constructs a real LLM client which validates the API key
    # is present (no network call). Supply a dummy so tests don't need real keys.
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-dummy-key")


@pytest.fixture
def stage(local_prompts):
    # Two scenes, two interactions, so set_scene / set_interaction have targets.
    # scene_description renders as "<scene> desc." and steer as "<interaction> steer."
    write_scenario_tree(
        local_prompts,
        scenes=("scene_1", "scene_2"),
        interactions=("converse", "barter"),
    )
    return GameDrivenStage(llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False)


@pytest.fixture
def multi_stage(local_prompts):
    write_scenario_tree(
        local_prompts,
        scenes=("scene_1", "scene_2"),
        interactions=("converse", "barter"),
        characters=(("dorn", "Dorn"), ("barkeep", "Barkeep")),
    )
    return GameDrivenStage(llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False)


@pytest.mark.asyncio
async def test_load_multi_populates_all_characters(multi_stage):
    await multi_stage.load_scenario("tavern")
    assert multi_stage.scenario is not None
    assert set(multi_stage.character_ids()) == {"dorn", "barkeep"}
    assert multi_stage.active_character == "dorn"
    assert "Dorn is wary." == multi_stage.scene_data_for("dorn").character_back_story
    assert "Barkeep is wary." == multi_stage.scene_data_for("barkeep").character_back_story


@pytest.mark.asyncio
async def test_interactions_map_has_all_characters(multi_stage):
    await multi_stage.load_scenario("tavern")
    assert multi_stage.interactions_map() == {"dorn": "converse", "barkeep": "converse"}


@pytest.mark.asyncio
async def test_unload_clears_all_characters(multi_stage):
    await multi_stage.load_scenario("tavern")
    await multi_stage.unload_scenario()
    assert multi_stage.scenario is None
    assert multi_stage.character_ids() == []
    assert multi_stage.active_character is None
    assert multi_stage.scene_data is None


@pytest.mark.asyncio
async def test_active_scene_data_follows_active_pointer(multi_stage):
    await multi_stage.load_scenario("tavern")
    multi_stage._active_character = "barkeep"
    assert multi_stage.scene_data.character_back_story == "Barkeep is wary."
    multi_stage._active_character = "dorn"
    assert multi_stage.scene_data.character_back_story == "Dorn is wary."


@pytest.mark.asyncio
async def test_set_interaction_changes_only_one_character(multi_stage):
    await multi_stage.load_scenario("tavern")
    await multi_stage.set_interaction("dorn", "barter")
    assert multi_stage.interactions_map() == {"dorn": "barter", "barkeep": "converse"}


@pytest.mark.asyncio
async def test_set_scene_resets_all_interactions(multi_stage):
    await multi_stage.load_scenario("tavern")
    await multi_stage.set_interaction("dorn", "barter")
    await multi_stage.set_scene("scene_2")
    assert multi_stage.current_scene == "scene_2"
    assert multi_stage.interactions_map() == {"dorn": "converse", "barkeep": "converse"}


@pytest.mark.asyncio
async def test_starts_empty(stage):
    assert stage.scenario is None
    assert stage.scene_data is None


@pytest.mark.asyncio
async def test_load_scenario_populates(stage):
    await stage.load_scenario("tavern")
    assert stage.scenario is not None
    assert stage.scene_data is not None
    assert stage.current_scene == "scene_1"
    assert stage.interactions_map()["zeek"] == "converse"
    assert stage.character_ids() == ["zeek"]
    assert stage.active_character == "zeek"


@pytest.mark.asyncio
async def test_unload_returns_to_empty(stage):
    await stage.load_scenario("tavern")
    await stage.unload_scenario()
    assert stage.scenario is None
    assert stage.scene_data is None
    assert stage.character_ids() == []
    assert stage.active_character is None


@pytest.mark.asyncio
async def test_unload_when_empty_is_noop(stage):
    await stage.unload_scenario()  # must not raise
    assert stage.scenario is None


@pytest.mark.asyncio
async def test_set_interaction_swaps_and_preserves_history(stage):
    await stage.load_scenario("tavern")
    stage._characters["zeek"].actor.history.add_message("Player", "earlier message")
    await stage.set_interaction("zeek", "barter")
    assert stage.interactions_map()["zeek"] == "barter"
    assert "barter steer." == stage.scene_data.steer_back_instruction
    assert any(
        m.text == "earlier message"
        for m in stage._characters["zeek"].actor.history.messages
    )


@pytest.mark.asyncio
async def test_set_interaction_unknown_raises_and_keeps_state(stage):
    await stage.load_scenario("tavern")
    with pytest.raises(Exception):
        await stage.set_interaction("zeek", "nonexistent")
    assert stage.interactions_map()["zeek"] == "converse"


@pytest.mark.asyncio
async def test_set_scene_swaps_and_resets_interaction(stage):
    await stage.load_scenario("tavern")
    await stage.set_interaction("zeek", "barter")
    stage._characters["zeek"].actor.history.add_message("Player", "carry me")
    await stage.set_scene("scene_2")
    assert stage.current_scene == "scene_2"
    assert stage.interactions_map()["zeek"] == "converse"
    assert "scene_2 desc." == stage.scene_data.scene_description
    assert any(
        m.text == "carry me"
        for m in stage._characters["zeek"].actor.history.messages
    )


@pytest.mark.asyncio
async def test_set_scene_unknown_raises_and_keeps_state(stage):
    await stage.load_scenario("tavern")
    with pytest.raises(Exception):
        await stage.set_scene("scene_99")
    assert stage.current_scene == "scene_1"
