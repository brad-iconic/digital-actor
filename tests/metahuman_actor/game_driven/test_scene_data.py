"""Tests for GameDrivenSceneData loading (via get_prompt) and trigger discovery."""
from __future__ import annotations

import pytest

from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData

from .conftest import write_scenario_tree


def _scenario(langfuse_root, **kwargs):
    write_scenario_tree(langfuse_root, **kwargs)
    return GameDrivenScenario.load("tavern")


def test_loads_lore_fields(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.scene_back_story == "The tavern arc."
    assert data.character_back_story == "Zeek is wary."
    assert data.scene_description == "scene_1 desc."
    assert data.steer_back_instruction == "converse steer."
    assert data.opening_speech == "[Zeek]: Well met."
    assert data.prev_scene_description == ""
    assert data.scene_supplement == ""


def test_discovers_triggers(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert set(data.triggers.keys()) == {"greet", "player_drew_weapon"}


def test_no_triggers_folder_yields_empty_registry(local_prompts):
    scenario = _scenario(local_prompts, with_triggers=False)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.triggers == {}


def test_optional_opening_speech_absent(local_prompts):
    scenario = _scenario(local_prompts)
    (scenario.interaction_dir("scene_1", "zeek", "converse") / "opening_speech.txt").unlink()
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.opening_speech == ""


def test_checkpoints_default_empty_when_absent(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.checkpoints.is_finished() is True


def test_render_trigger_prompt_substitutes_info(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    rendered = data.triggers["player_drew_weapon"].render_prompt({"weapon": "sword"})
    assert rendered == "The player drew sword. React."


def test_render_trigger_narrator_substitutes_info(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    rendered = data.triggers["player_drew_weapon"].render_narrator({"weapon": "sword"})
    assert rendered == "The player draws their sword."


def test_render_trigger_narrator_none_when_no_template(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.triggers["greet"].render_narrator({}) is None
