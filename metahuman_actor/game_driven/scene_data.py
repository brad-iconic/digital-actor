"""Scene-bound content for one (scene, character, interaction) triple.

All prompt content is loaded via langfuse_utils.get_prompt so it flips
local<->Langfuse with no code change and stays observable in traces. Trigger
*structure* is discovered by listing the triggers/ folder on disk; each
trigger's body is then loaded by name through get_prompt. Exposes the
attribute names MetaHumanDigitalActor.get_next_line_prompt_info reads from
stage_context.scene_data, so the actor's prompt building works unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from digital_actor.checkpoints import SceneCheckpoints
from langfuse_utils import get_prompt

from metahuman_actor.game_driven.scenario import GameDrivenScenario


def _get(name: str) -> str:
    """Compile a required prompt to a string."""
    return get_prompt(name).compile()


def _get_optional(name: str) -> str:
    """Compile an optional prompt; return '' if it doesn't exist."""
    try:
        return get_prompt(name).compile()
    except FileNotFoundError:
        return ""


@dataclass(frozen=True)
class TriggerConfig:
    """One discovered trigger: its prompt name and optional narrator name.

    Rendering goes through get_prompt(...).compile(**info) so {{var}}
    placeholders in the trigger files are substituted from the event info.
    """

    name: str
    prompt_name: str
    narrator_name: str | None = None

    def render_prompt(self, info: dict[str, str]) -> str:
        return get_prompt(self.prompt_name).compile(**info)

    def render_narrator(self, info: dict[str, str]) -> str | None:
        if self.narrator_name is None:
            return None
        return get_prompt(self.narrator_name).compile(**info)


@dataclass(frozen=True)
class GameDrivenSceneData:
    scene: str
    character: str
    interaction: str

    scene_back_story: str
    character_back_story: str
    scene_description: str
    steer_back_instruction: str
    opening_speech: str

    triggers: dict[str, TriggerConfig] = field(default_factory=dict)
    checkpoints: SceneCheckpoints = field(
        default_factory=lambda: SceneCheckpoints.from_dict({"nodes": []})
    )

    # Fields the actor reads but the new layout has no source for.
    prev_scene_description: str = ""
    scene_supplement: str = ""

    @classmethod
    def load(
        cls,
        scenario: GameDrivenScenario,
        *,
        scene: str,
        character: str,
        interaction: str,
    ) -> GameDrivenSceneData:
        root = scenario.prompts_root  # "scenarios/<name>"
        inter_prefix = f"{root}/{scene}/characters/{character}/{interaction}"

        # checkpoints.json is structured data, not a prompt — read directly.
        checkpoints_path = (
            scenario.interaction_dir(scene, character, interaction) / "checkpoints.json"
        )
        if checkpoints_path.is_file():
            with open(checkpoints_path, encoding="utf-8") as f:
                checkpoints = SceneCheckpoints.from_dict(json.load(f))
        else:
            checkpoints = SceneCheckpoints.from_dict({"nodes": []})

        return cls(
            scene=scene,
            character=character,
            interaction=interaction,
            scene_back_story=_get(f"{root}/back_story"),
            character_back_story=_get(f"{root}/{scene}/characters/{character}/character_back_story"),
            scene_description=_get(f"{root}/{scene}/scene_description"),
            steer_back_instruction=_get(f"{inter_prefix}/steer_back_instructions"),
            opening_speech=_get_optional(f"{inter_prefix}/opening_speech"),
            triggers=cls._discover_triggers(scenario, scene, character, interaction),
            checkpoints=checkpoints,
        )

    @staticmethod
    def _discover_triggers(
        scenario: GameDrivenScenario, scene: str, character: str, interaction: str
    ) -> dict[str, TriggerConfig]:
        triggers_root = (
            scenario.interaction_dir(scene, character, interaction) / "triggers"
        )
        registry: dict[str, TriggerConfig] = {}
        if not triggers_root.is_dir():
            return registry
        prefix = f"{scenario.prompts_root}/{scene}/characters/{character}/{interaction}/triggers"
        for entry in sorted(triggers_root.iterdir()):
            if not entry.is_dir() or not (entry / "prompt.txt").is_file():
                continue
            has_narrator = (entry / "narrator.txt").is_file()
            registry[entry.name] = TriggerConfig(
                name=entry.name,
                prompt_name=f"{prefix}/{entry.name}/prompt",
                narrator_name=f"{prefix}/{entry.name}/narrator" if has_narrator else None,
            )
        return registry
