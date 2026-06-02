"""Tests for MetaHumanStage load/unload lifecycle and hot-swap."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from metahuman_actor.settings import settings as global_settings

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _dummy_llm_key(monkeypatch):
    # The stage constructs a real LLM client which validates the API key is
    # present (no network call). Supply a dummy so tests don't need real keys.
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-dummy-key")


@pytest.fixture(autouse=True)
def _cleanup_mirrored_prompts():
    """Remove any `default`/`alt` prompt dirs left behind by a test."""
    yield
    for name in ("default", "alt"):
        shutil.rmtree(Path(".langfuse_prompts/scenarios").resolve() / name, ignore_errors=True)


REPO_PROMPTS = Path(".langfuse_prompts/scenarios").resolve()
LLM = "cerebras/qwen-3-235b-a22b-instruct-2507"


def _copy_prompt_scenario(src_name: str, dst_name: str, *, supplement_text: str | None = None) -> Path:
    src = REPO_PROMPTS / src_name
    dst = REPO_PROMPTS / dst_name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    if supplement_text is not None:
        (dst / "scene_supplement.txt").write_text(supplement_text, encoding="utf-8")
    return dst


# Source scenario that actually exists in the repo. The fixture clones this
# into a tmp tree under both `default` and `alt` names so the tests below can
# operate on those logical names without depending on a `default` scenario on
# disk.
_SRC_SCENARIO = "zeek"


def _setup_data_scenarios(tmp_path) -> Path:
    tmp_data = tmp_path / "data_scenarios"
    tmp_data.mkdir()
    shutil.copytree(global_settings.scenarios_path / _SRC_SCENARIO, tmp_data / "default")
    shutil.copytree(global_settings.scenarios_path / _SRC_SCENARIO, tmp_data / "alt")
    # Mirror the prompt tree so Scenario.load can resolve `default` / `alt`.
    for name in ("default", "alt"):
        dst = REPO_PROMPTS / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(REPO_PROMPTS / _SRC_SCENARIO, dst)
    return tmp_data


async def test_construct_empty(monkeypatch, tmp_path):
    from metahuman_actor.stage import MetaHumanStage

    stage = MetaHumanStage(LLM, tts_enabled=False)
    assert stage.scenario is None
    assert stage.scene_data is None
    assert stage.actor is None
    assert stage.tts_client is None


async def test_load_scenario_from_empty(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session
    from metahuman_actor.stage import MetaHumanStage

    tmp_data = _setup_data_scenarios(tmp_path)
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        stage = MetaHumanStage(LLM, tts_enabled=False)
        await stage.load_scenario("default")
        assert stage.scenario is not None and stage.scenario.name == "default"
        assert stage.actor is not None
        assert stage.scene_data is not None and stage.scene_data.scene_idx == 1


async def test_unload_scenario_returns_to_empty(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session
    from metahuman_actor.stage import MetaHumanStage

    tmp_data = _setup_data_scenarios(tmp_path)
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        stage = MetaHumanStage(LLM, tts_enabled=False)
        await stage.load_scenario("default")
        await stage.unload_scenario()
        assert stage.scenario is None
        assert stage.scene_data is None
        assert stage.actor is None
        assert stage.tts_client is None


async def test_unload_scenario_when_empty_is_noop():
    from metahuman_actor.stage import MetaHumanStage

    stage = MetaHumanStage(LLM, tts_enabled=False)
    await stage.unload_scenario()
    assert stage.scenario is None


async def test_hot_swap_replaces_state(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session
    from metahuman_actor.stage import MetaHumanStage

    tmp_data = _setup_data_scenarios(tmp_path)
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)

    try:
        _copy_prompt_scenario(
            "default", "alt", supplement_text="ALT_SUPPLEMENT {{actor_name}}"
        )
        with langfuse_session(local=True):
            fetch_all_prompts_from_project()
            stage = MetaHumanStage(LLM, tts_enabled=False)
            await stage.load_scenario("default")
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


async def test_load_missing_from_empty_stays_empty(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session
    from metahuman_actor.scenario import ScenarioNotFoundError
    from metahuman_actor.stage import MetaHumanStage

    tmp_data = _setup_data_scenarios(tmp_path)
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        stage = MetaHumanStage(LLM, tts_enabled=False)
        with pytest.raises(ScenarioNotFoundError):
            await stage.load_scenario("nonexistent")
        assert stage.scenario is None


async def test_load_missing_after_loaded_keeps_prior(monkeypatch, tmp_path):
    from langfuse_utils import fetch_all_prompts_from_project, langfuse_session
    from metahuman_actor.scenario import ScenarioNotFoundError
    from metahuman_actor.stage import MetaHumanStage

    tmp_data = _setup_data_scenarios(tmp_path)
    monkeypatch.setattr(global_settings, "scenarios_path", tmp_data, raising=False)

    with langfuse_session(local=True):
        fetch_all_prompts_from_project()
        stage = MetaHumanStage(LLM, tts_enabled=False)
        await stage.load_scenario("default")
        before = stage.scenario.name
        with pytest.raises(ScenarioNotFoundError):
            await stage.load_scenario("nonexistent")
        assert stage.scenario.name == before
