"""Shared fixtures for game_driven tests.

The new dialogue path reads all prompt content via langfuse_utils.get_prompt.
In tests we activate local prompt mode pointed at a tmp_path tree so get_prompt
resolves the fixture prompts (and scenario.json / personas are also read from
the same tree, since the scenario data tree lives under the langfuse root).
"""
from __future__ import annotations

import json

import pytest

from langfuse_utils import langfuse_session


def write_scenario_tree(
    langfuse_root,
    *,
    name="tavern",
    scenes=("scene_1",),
    interactions=("converse",),
    with_triggers=True,
):
    """Create a game-driven scenario tree under <langfuse_root>/scenarios/<name>.

    The loader resolves scenarios under the local prompt root at scenarios/, and
    get_prompt resolves names like "scenarios/<name>/scene_1/..." to these files.

    Returns the scenario directory path.
    """
    scen = langfuse_root / "scenarios" / name
    (scen / "personas").mkdir(parents=True)
    (scen / "personas" / "zeek.json").write_text(
        json.dumps({"id": "zeek", "display_name": "Zeek"}), encoding="utf-8"
    )
    (scen / "scenario.json").write_text(
        json.dumps(
            {
                "default_character": "zeek",
                "default_scene": scenes[0],
                "default_interaction": interactions[0],
            }
        ),
        encoding="utf-8",
    )
    (scen / "back_story.txt").write_text("The tavern arc.", encoding="utf-8")
    for scene in scenes:
        (scen / scene).mkdir(parents=True, exist_ok=True)
        (scen / scene / "scene_description.txt").write_text(f"{scene} desc.", encoding="utf-8")
        char = scen / scene / "characters" / "zeek"
        char.mkdir(parents=True, exist_ok=True)
        (char / "character_back_story.txt").write_text("Zeek is wary.", encoding="utf-8")
        for interaction in interactions:
            inter = char / interaction
            inter.mkdir(parents=True, exist_ok=True)
            (inter / "steer_back_instructions.txt").write_text(
                f"{interaction} steer.", encoding="utf-8"
            )
            (inter / "opening_speech.txt").write_text("[Zeek]: Well met.", encoding="utf-8")
            if with_triggers:
                greet = inter / "triggers" / "greet"
                greet.mkdir(parents=True)
                (greet / "prompt.txt").write_text(
                    "The player approaches. Greet them.", encoding="utf-8"
                )
                weapon = inter / "triggers" / "player_drew_weapon"
                weapon.mkdir(parents=True)
                (weapon / "prompt.txt").write_text(
                    "The player drew {{weapon}}. React.", encoding="utf-8"
                )
                (weapon / "narrator.txt").write_text(
                    "The player draws their {{weapon}}.", encoding="utf-8"
                )
    return scen


def _seed_shared_prompts(langfuse_root):
    """Copy the repo's dialogue/ + common/ templates into the test root.

    The scene (later tasks) builds prompts via get_prompt("dialogue/get_respond_line")
    etc., which must resolve under the test's LOCAL_LANGFUSE_PATH. We copy the real
    templates so tests exercise the real templates, not stubs. Safe if some dirs
    don't exist yet (they're created in a later task).
    """
    import shutil
    from pathlib import Path

    repo_prompts = Path(__file__).resolve().parents[3] / ".langfuse_prompts"
    for sub in ("dialogue", "common", "query"):
        src = repo_prompts / sub
        if src.is_dir():
            shutil.copytree(src, langfuse_root / sub, dirs_exist_ok=True)


@pytest.fixture
def local_prompts(tmp_path, monkeypatch):
    """Activate local langfuse mode pointed at tmp_path.

    Seeds the shared dialogue/common/query templates into tmp_path so the
    scene's get_prompt calls resolve. Yields tmp_path (the local prompt root).
    Tests create their scenario tree under <tmp_path>/scenarios/<name> via
    write_scenario_tree; the loader finds it under <root>/scenarios/.
    """
    monkeypatch.setenv("LOCAL_LANGFUSE_PATH", str(tmp_path))
    _seed_shared_prompts(tmp_path)
    with langfuse_session(local=True):
        yield tmp_path
