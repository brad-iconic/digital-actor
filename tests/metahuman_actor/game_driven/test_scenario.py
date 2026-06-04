"""Tests for the GameDrivenScenario loader."""
from __future__ import annotations

import json

import pytest

from metahuman_actor.game_driven.scenario import (
    GameDrivenScenario,
    GameDrivenScenarioNotFoundError,
    list_game_driven_scenarios,
)


def _make_tree(scenarios_root, name="tavern"):
    """Create a minimal scenario tree under <scenarios_root>/<name>."""
    d = scenarios_root / name
    (d / "personas").mkdir(parents=True)
    (d / "personas" / "zeek.json").write_text(
        json.dumps({"id": "zeek", "display_name": "Zeek"}), encoding="utf-8"
    )
    (d / "scenario.json").write_text(
        json.dumps(
            {
                "default_character": "zeek",
                "default_scene": "scene_1",
                "default_interaction": "converse",
            }
        ),
        encoding="utf-8",
    )
    (d / "back_story.txt").write_text("The tavern.", encoding="utf-8")
    interaction = d / "scene_1" / "characters" / "zeek" / "converse"
    interaction.mkdir(parents=True)
    (d / "scene_1" / "scene_description.txt").write_text("Dim tavern.", encoding="utf-8")
    (d / "scene_1" / "characters" / "zeek" / "character_back_story.txt").write_text(
        "Zeek is wary.", encoding="utf-8"
    )
    (interaction / "steer_back_instructions.txt").write_text("Stay on topic.", encoding="utf-8")
    return d


@pytest.fixture
def scenarios_root(tmp_path, monkeypatch):
    """Set LOCAL_LANGFUSE_PATH=tmp_path; scenario trees live at tmp_path/scenarios/<name>."""
    monkeypatch.setenv("LOCAL_LANGFUSE_PATH", str(tmp_path))
    root = tmp_path / "scenarios"
    root.mkdir()
    return root


def test_load_success(scenarios_root):
    _make_tree(scenarios_root)
    s = GameDrivenScenario.load("tavern")
    assert s.name == "tavern"
    assert s.default_character == "zeek"
    assert s.default_scene == "scene_1"
    assert s.default_interaction == "converse"


def test_persona_path_resolves(scenarios_root):
    _make_tree(scenarios_root)
    s = GameDrivenScenario.load("tavern")
    assert s.persona_path("zeek") == scenarios_root / "tavern" / "personas" / "zeek.json"


def test_interaction_dir_resolves(scenarios_root):
    _make_tree(scenarios_root)
    s = GameDrivenScenario.load("tavern")
    expected = scenarios_root / "tavern" / "scene_1" / "characters" / "zeek" / "converse"
    assert s.interaction_dir("scene_1", "zeek", "converse") == expected


def test_has_scene_and_has_interaction(scenarios_root):
    _make_tree(scenarios_root)
    s = GameDrivenScenario.load("tavern")
    assert s.has_scene("scene_1") is True
    assert s.has_scene("scene_99") is False
    assert s.has_interaction("scene_1", "zeek", "converse") is True
    assert s.has_interaction("scene_1", "zeek", "barter") is False


def test_load_missing_directory_raises(scenarios_root):
    with pytest.raises(GameDrivenScenarioNotFoundError):
        GameDrivenScenario.load("nope")


def test_prompts_root_uses_scenarios_prefix(scenarios_root):
    _make_tree(scenarios_root)
    s = GameDrivenScenario.load("tavern")
    assert s.prompts_root == "scenarios/tavern"


def test_list_returns_scenarios_with_scenario_json(scenarios_root):
    _make_tree(scenarios_root, "alpha")
    _make_tree(scenarios_root, "bravo")
    (scenarios_root / "legacy").mkdir()  # no scenario.json -> excluded
    (scenarios_root / ".hidden").mkdir()
    assert list_game_driven_scenarios() == ["alpha", "bravo"]


def test_characters_defaults_to_single_when_no_list(scenarios_root):
    # _make_tree writes scenario.json with default_character only, no characters list.
    _make_tree(scenarios_root)
    s = GameDrivenScenario.load("tavern")
    assert s.characters == ["zeek"]


def test_characters_reads_explicit_list(scenarios_root):
    import json
    _make_tree(scenarios_root)
    (scenarios_root / "tavern" / "scenario.json").write_text(
        json.dumps({
            "characters": ["dorn", "barkeep"],
            "default_character": "dorn",
            "default_scene": "scene_1",
            "default_interaction": "converse",
        }),
        encoding="utf-8",
    )
    s = GameDrivenScenario.load("tavern")
    assert s.characters == ["dorn", "barkeep"]
    assert s.default_character == "dorn"


def test_default_character_defaults_to_first_when_absent(scenarios_root):
    import json
    _make_tree(scenarios_root)
    (scenarios_root / "tavern" / "scenario.json").write_text(
        json.dumps({
            "characters": ["dorn", "barkeep"],
            "default_scene": "scene_1",
            "default_interaction": "converse",
        }),
        encoding="utf-8",
    )
    s = GameDrivenScenario.load("tavern")
    assert s.characters == ["dorn", "barkeep"]
    assert s.default_character == "dorn"  # defaults to characters[0]
