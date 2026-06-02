"""Tests for the Scenario value object."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from metahuman_actor.scenario import (
    PersonaNotFoundError,
    Scenario,
    ScenarioNotFoundError,
    _overlay_settings,
    list_available_scenarios,
)
from metahuman_actor.settings import settings as global_settings


def _mk(name: str = "forest") -> Scenario:
    return Scenario(
        name=name,
        persona_path=Path("/tmp/persona.json"),
        settings=global_settings.digital_actor_server,
    )


def test_prompts_root_uses_name():
    assert _mk().prompts_root == "scenarios/forest"


def test_data_root_lives_under_scenarios_path():
    assert _mk().data_root == global_settings.scenarios_path / "forest"


def test_scene_dir_joins_scene_idx():
    assert _mk().scene_dir(3) == global_settings.scenarios_path / "forest" / "scene3"


def test_overlay_returns_base_when_no_overlay_keys(tmp_path):
    base = global_settings.digital_actor_server
    overlay = tmp_path / "settings.yaml"
    overlay.write_text("digital_actor_server: {}\n", encoding="utf-8")
    merged = _overlay_settings(base, overlay)
    assert merged.idle_timeout == base.idle_timeout
    assert merged.default_followup_timeout == base.default_followup_timeout


def test_overlay_replaces_only_specified_fields(tmp_path):
    base = global_settings.digital_actor_server
    overlay = tmp_path / "settings.yaml"
    overlay.write_text(
        textwrap.dedent(
            """
            digital_actor_server:
              idle_timeout: 999
            """
        ).strip(),
        encoding="utf-8",
    )
    merged = _overlay_settings(base, overlay)
    assert merged.idle_timeout == 999
    assert merged.default_followup_timeout == base.default_followup_timeout
    assert merged.playback_end_buffer_sec == base.playback_end_buffer_sec


def test_overlay_ignores_missing_top_level_block(tmp_path):
    base = global_settings.digital_actor_server
    overlay = tmp_path / "settings.yaml"
    overlay.write_text("unrelated_key: 1\n", encoding="utf-8")
    merged = _overlay_settings(base, overlay)
    assert merged == base


def _make_scenario_on_disk(root, name, *, with_persona=True, persona_variants=(), with_overlay=False):
    d = root / name
    d.mkdir(parents=True)
    if with_persona:
        (d / "persona.json").write_text(json.dumps({"id": "x", "display_name": "X"}), encoding="utf-8")
    for v in persona_variants:
        (d / f"persona_{v}.json").write_text(json.dumps({"id": "x", "display_name": "X"}), encoding="utf-8")
    if with_overlay:
        (d / "settings.yaml").write_text("digital_actor_server:\n  idle_timeout: 42\n", encoding="utf-8")
    return d


def test_load_success(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_path, raising=False)
    _make_scenario_on_disk(tmp_path, "forest")
    s = Scenario.load("forest")
    assert s.name == "forest"
    assert s.persona_path == tmp_path / "forest" / "persona.json"
    assert s.prompts_root == "scenarios/forest"


def test_load_missing_directory_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_path, raising=False)
    with pytest.raises(ScenarioNotFoundError):
        Scenario.load("nonexistent")


def test_load_missing_persona_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_path, raising=False)
    _make_scenario_on_disk(tmp_path, "forest", with_persona=False)
    with pytest.raises(PersonaNotFoundError):
        Scenario.load("forest")


def test_load_persona_variant(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_path, raising=False)
    _make_scenario_on_disk(tmp_path, "forest", persona_variants=("neutts",))
    s = Scenario.load("forest", persona_variant="neutts")
    assert s.persona_path == tmp_path / "forest" / "persona_neutts.json"


def test_load_applies_settings_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_path, raising=False)
    _make_scenario_on_disk(tmp_path, "forest", with_overlay=True)
    s = Scenario.load("forest")
    assert s.settings.idle_timeout == 42


def test_list_returns_dirs_with_persona(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_path, raising=False)
    _make_scenario_on_disk(tmp_path, "alpha")
    _make_scenario_on_disk(tmp_path, "bravo")
    _make_scenario_on_disk(tmp_path, "no_persona", with_persona=False)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "loose_file.txt").write_text("x", encoding="utf-8")
    assert list_available_scenarios() == ["alpha", "bravo"]


def test_list_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_path / "missing", raising=False)
    assert list_available_scenarios() == []
