"""Loader for the game-driven scenario on-disk layout.

Layout (see spec):

    scenarios/<scenario>/
      scenario.json                 default_character/scene/interaction
      back_story.txt
      personas/<character>.json
      <scene>/
        scene_description.txt
        characters/<character>/
          character_back_story.txt
          <interaction>/
            steer_back_instructions.txt
            opening_speech.txt        (optional)
            checkpoints.json          (optional)
            triggers/<name>/prompt.txt (+ optional narrator.txt)

This object resolves and validates *paths*; reading prompt bodies happens in
GameDrivenSceneData.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from langfuse_utils.core import resolve_local_langfuse_root


def _scenarios_root() -> Path:
    """Directory containing game-driven scenario trees.

    New-layout scenarios live under the local prompt root at ``scenarios/`` so
    their prompt content is reachable by get_prompt names like
    ``scenarios/<name>/...`` AND their structure is discoverable on disk by the
    loader. Default local root is ``.langfuse_prompts/`` (or LOCAL_LANGFUSE_PATH).
    """
    return resolve_local_langfuse_root() / "scenarios"


class GameDrivenScenarioNotFoundError(FileNotFoundError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Game-driven scenario {name!r} not found under {_scenarios_root()}"
        )


@dataclass(frozen=True)
class GameDrivenScenario:
    name: str
    default_character: str
    default_scene: str
    default_interaction: str
    characters: list[str]

    @property
    def data_root(self) -> Path:
        return _scenarios_root() / self.name

    @property
    def prompts_root(self) -> str:
        # Prompt names are resolved by get_prompt under the local prompt root.
        # Scenario trees live at <root>/scenarios/<name>, so names are
        # "scenarios/<name>/<scene>/...". Keeps content + structure in one place
        # and in the Langfuse namespace for a clean future upload.
        return f"scenarios/{self.name}"

    def persona_path(self, character: str) -> Path:
        return self.data_root / "personas" / f"{character}.json"

    def scene_dir(self, scene: str) -> Path:
        return self.data_root / scene

    def character_dir(self, scene: str, character: str) -> Path:
        return self.scene_dir(scene) / "characters" / character

    def interaction_dir(self, scene: str, character: str, interaction: str) -> Path:
        return self.character_dir(scene, character) / interaction

    def has_scene(self, scene: str) -> bool:
        return self.scene_dir(scene).is_dir()

    def has_interaction(self, scene: str, character: str, interaction: str) -> bool:
        return self.interaction_dir(scene, character, interaction).is_dir()

    @classmethod
    def load(cls, name: str) -> GameDrivenScenario:
        """Load a scenario's config from ``scenarios/<name>/scenario.json``.

        Raises:
            GameDrivenScenarioNotFoundError: if the scenario directory or its
                ``scenario.json`` is missing.

        A malformed ``scenario.json`` (invalid JSON, or missing a required key)
        propagates the natural ``json.JSONDecodeError`` / ``KeyError`` — the
        server layer surfaces it to the client as an error frame. This mirrors
        the existing ``metahuman_actor.scenario.Scenario.load`` behaviour.
        """
        data_root = _scenarios_root() / name
        if not data_root.is_dir():
            raise GameDrivenScenarioNotFoundError(name)
        config_path = data_root / "scenario.json"
        if not config_path.is_file():
            raise GameDrivenScenarioNotFoundError(name)
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        # Normalize the character set: an explicit "characters" list wins;
        # otherwise fall back to the single "default_character" (back-compat).
        characters = config.get("characters")
        default_character = config.get("default_character")
        if characters:
            if not default_character:
                default_character = characters[0]
        else:
            characters = [default_character]
        return cls(
            name=name,
            default_character=default_character,
            default_scene=config["default_scene"],
            default_interaction=config["default_interaction"],
            characters=list(characters),
        )


def list_game_driven_scenarios() -> list[str]:
    """Return sorted names of scenarios that have a scenario.json."""
    root = _scenarios_root()
    if not root.is_dir():
        return []
    names: list[str] = []
    for entry in root.iterdir():
        if entry.name.startswith("."):
            continue
        if not entry.is_dir() or entry.is_symlink():
            continue
        if not (entry / "scenario.json").is_file():
            continue
        names.append(entry.name)
    return sorted(names)
