"""Tests for MetaHumanStage.load_scenario in-place hot-swap."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from metahuman_actor.settings import settings as global_settings

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _dummy_llm_key(monkeypatch):
    # The stage constructs a real LLM client, which validates that the backend
    # API key is present (no network call is made). Supply a dummy so the tests
    # don't depend on a real key or a local .env in CI.
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-dummy-key")

REPO_PROMPTS = Path(".langfuse_prompts/scenarios").resolve()
LLM = "cerebras/qwen-3-235b-a22b-instruct-2507"


def _copy_prompt_scenario(src_name: str, dst_name: str, *, supplement_text: str | None = None) -> Path:
    """Copy a prompt-tree scenario in .langfuse_prompts and optionally tweak its supplement."""
    src = REPO_PROMPTS / src_name
    dst = REPO_PROMPTS / dst_name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    if supplement_text is not None:
        (dst / "scene_supplement.txt").write_text(supplement_text, encoding="utf-8")
    return dst


def _setup_data_scenarios(tmp_path) -> Path:
    """Copy the data-tree `default` scenario into a temp scenarios root, plus an `alt` clone."""
    tmp_data = tmp_path / "data_scenarios"
    tmp_data.mkdir()
    shutil.copytree(global_settings.scenarios_path / "default", tmp_data / "default")
    shutil.copytree(global_settings.scenarios_path / "default", tmp_data / "alt")
    return tmp_data


async def test_load_scenario_swaps_state(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session
    from metahuman_actor.stage import MetaHumanStage

    tmp_data = _setup_data_scenarios(tmp_path)
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)

    try:
        _copy_prompt_scenario("default", "alt", supplement_text="ALT_SUPPLEMENT {{actor_name}}")
        with langfuse_session(local=True):
            fetch_all_prompts_from_project()
            stage = MetaHumanStage(LLM, scenario_name="default", tts_enabled=False)
            assert stage.scenario.name == "default"
            original_actor = stage.actor
            original_supplement = stage.scene_data.scene_supplement

            await stage.load_scenario("alt")

            assert stage.scenario.name == "alt"
            assert stage.actor is not original_actor
            assert stage.scene_data.scene_idx == 1
            assert "ALT_SUPPLEMENT" in stage.scene_data.scene_supplement
            assert stage.scene_data.scene_supplement != original_supplement
    finally:
        shutil.rmtree(REPO_PROMPTS / "alt", ignore_errors=True)


async def test_load_scenario_missing_raises_and_keeps_state(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session
    from metahuman_actor.scenario import ScenarioNotFoundError
    from metahuman_actor.stage import MetaHumanStage

    tmp_data = _setup_data_scenarios(tmp_path)
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        stage = MetaHumanStage(LLM, scenario_name="default", tts_enabled=False)
        before = stage.scenario.name
        with pytest.raises(ScenarioNotFoundError):
            await stage.load_scenario("nonexistent")
        assert stage.scenario.name == before
