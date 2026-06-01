from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from metahuman_actor.settings import DigitalActorServerSettings, settings


class ScenarioNotFoundError(FileNotFoundError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Scenario {name!r} not found under {settings.scenarios_path}")


class PersonaNotFoundError(FileNotFoundError):
    def __init__(self, persona_path: Path) -> None:
        self.persona_path = persona_path
        super().__init__(f"Persona file not found: {persona_path}")


def _overlay_settings(
    base: DigitalActorServerSettings, overlay_path: Path
) -> DigitalActorServerSettings:
    with open(overlay_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    block = data.get("digital_actor_server", {})
    if not block:
        return base
    base_dict = base.model_dump()
    base_dict.update(block)
    return DigitalActorServerSettings.model_validate(base_dict)


@dataclass(frozen=True)
class Scenario:
    name: str
    persona_path: Path
    settings: DigitalActorServerSettings

    @property
    def prompts_root(self) -> str:
        return f"scenarios/{self.name}"

    @property
    def data_root(self) -> Path:
        return settings.scenarios_path / self.name

    def scene_dir(self, scene_idx: int) -> Path:
        return self.data_root / f"scene{scene_idx}"

    @classmethod
    def load(cls, name: str, persona_variant: str | None = None) -> "Scenario":
        data_root = settings.scenarios_path / name
        if not data_root.is_dir():
            raise ScenarioNotFoundError(name)

        filename = (
            f"persona_{persona_variant}.json" if persona_variant else "persona.json"
        )
        persona_path = data_root / filename
        if not persona_path.is_file():
            raise PersonaNotFoundError(persona_path)

        overlay = data_root / "settings.yaml"
        merged = (
            _overlay_settings(settings.digital_actor_server, overlay)
            if overlay.is_file()
            else settings.digital_actor_server
        )
        return cls(name=name, persona_path=persona_path, settings=merged)


def list_available_scenarios() -> list[str]:
    if not settings.scenarios_path.is_dir():
        return []
    names: list[str] = []
    for entry in settings.scenarios_path.iterdir():
        if entry.name.startswith("."):
            continue
        if not entry.is_dir() or entry.is_symlink():
            continue
        if not (entry / "persona.json").is_file():
            continue
        names.append(entry.name)
    return sorted(names)
