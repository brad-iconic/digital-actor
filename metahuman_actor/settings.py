from __future__ import annotations

from pathlib import Path

import pydantic
import yaml

_ROOT = Path(__file__).resolve().parent.parent


class DigitalActorServerSettings(pydantic.BaseModel):
    prompt_label: str | None = None
    idle_timeout: float | None = None
    default_followup_timeout: float | None = None
    query_followup_timeout: float | None = None
    actor_query_failure_timeout: float | None = None
    # Trailing buffer (sec) added to the server-side playback-end estimate
    # before releasing the response lock. Compensates for client-side audio
    # buffer warmup so the next line's chunks don't arrive while the
    # previous line is still being played.
    playback_end_buffer_sec: float = 0.5


class Settings(pydantic.BaseModel):
    digital_actor_server: DigitalActorServerSettings = pydantic.Field(
        default_factory=DigitalActorServerSettings
    )
    scenarios_path: Path = pydantic.Field(
        default_factory=lambda: _ROOT / "metahuman_actor" / "scenarios"
    )

    @property
    def root(self) -> Path:
        return _ROOT

    @classmethod
    def load(cls) -> Settings:
        with open(_ROOT / "settings.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.model_validate(
            {
                "digital_actor_server": data.get("digital_actor_server", {}),
            }
        )


settings = Settings.load()
