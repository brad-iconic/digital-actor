"""Render the per-request world_state dict into a prompt block.

The game sends a flat dict of runtime variables on every respond/trigger.
We render it mechanically as `key: value` lines — no Jinja, no schema — so
game-side designers can add or change variables without touching prompts.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def render_world_state(world_state: Mapping[str, Any] | None) -> str:
    """Return world_state as newline-joined ``key: value`` lines.

    List/tuple values are comma-joined. Empty or ``None`` returns ``""`` so
    the caller can omit the surrounding section entirely.
    """
    if not world_state:
        return ""
    lines: list[str] = []
    for key, value in world_state.items():
        if isinstance(value, (list, tuple)):
            rendered = ", ".join(str(v) for v in value)
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)
