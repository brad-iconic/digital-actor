# Game-Driven Dialogue Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a request-driven dialogue server (`GameDrivenScene` + stage + WS server) that produces in-character NPC lines on demand from game requests, alongside the existing authoritative server, without modifying the shared `digital_actor` library.

**Architecture:** New code lives entirely under `metahuman_actor/`. A new on-disk scenario layout (scenario → scene → character → interaction, with a flat `personas/` registry) is loaded by a new loader. `GameDrivenScene` implements the library's `BaseScene` directly (no tick, no followup timers, no playback estimation), reusing `SceneDigitalActor`, `DialogueHistory`, and `stage_context`. A new `WebSocketServer` subclass speaks a new wire protocol. The two servers share a port but never run at once — each has its own entry point.

**Tech Stack:** Python 3.12+, pydantic v2, asyncio, `websockets`, pytest. Prompt rendering via `langfuse_utils.get_prompt(name).compile(**kwargs)`. Package manager: `uv`.

---

## Background the engineer needs

Read the design spec first: `docs/superpowers/specs/2026-06-03-game-driven-dialogue-server-design.md`.

Key facts about the existing code (do not modify these — only read/reuse):

- **`langfuse_utils.get_prompt(name)`** returns a prompt object; call `.compile(**kwargs)` to render it to a string. `name` is a slash path like `"scenarios/zeek/scene_1/scene_description"` (no extension). The loader resolves it under the local prompt root, trying `<name>.txt`, then `<name>.json`, then `<name>`. **Deeply nested names work** — e.g. `"scenarios/zeek_gd/scene_1/characters/zeek/converse/steer_back_instructions"` resolves to that `.txt` under the root. `.compile(**kwargs)` substitutes `{{var}}` / `{{{var}}}` placeholders and resolves `@@@langfusePrompt:name=<other>@@@` inline includes.
- **ALL prompt content in the new path MUST go through `get_prompt`** — lore, trigger bodies, trigger narrators, and the top-level templates. This is the single seam that (a) flips local↔remote with no code change and (b) keeps every prompt observable/linkable in Langfuse traces. Never read a prompt body with `Path.read_text` — that would make it invisible to Langfuse forever. (The scenario *loader* still uses the filesystem to discover *structure* — which scenes/interactions/triggers exist — but it hands prompt *names* to `get_prompt`, never file contents.)
- **Local mode + root:** local mode is active when the process opened a session via `langfuse_session(local=True)` (the server passes this when `--langfuse-local` is set). The local root comes from the `LOCAL_LANGFUSE_PATH` env var (default `.langfuse_prompts/`). **In tests**, activate it with `monkeypatch.setenv("LOCAL_LANGFUSE_PATH", str(tmp_path))` and wrap the test body in `with langfuse_session(local=True):` so `get_prompt` resolves fixtures under `tmp_path`. A reusable fixture for this is defined in Task 4 and reused by Tasks 6 and 9.
- **`digital_actor.scene.BaseScene`** is an ABC with abstract `async on_user_input`, `async tick`, `async on_game_event(name, info)`, `async on_interrupt(line_id, elapsed_seconds)`, and `reset()`. We implement it but most methods are minimal.
- **`digital_actor.actor.SceneDigitalActor`** owns `.history` (a `DialogueHistory`), `.name`, and provides `async generate_next_text(...)`, `async run_tts(line)`, and `async history.summarize_if_needed()`. `history.add_message(role, text)` returns a `DialogueLine` with a `.line_id`.
- **`digital_actor.dialogue`** exposes `PLAYER_ROLE_NAME`, `NARRATOR_ROLE_NAME`, and `DialogueLine`.
- **`digital_actor.stage_context.stage_context`** is the access point actors use for `llm_acomplete`, `deliver_text`, `deliver_speech`, `llm_client`, `tts_client`, `elapsed_time`, and `scene_data`. `set_stage(stage)` registers the active stage. `MetaHumanDigitalActor.get_next_line_prompt_info` reads `stage_context.scene_data.*` — so the stage's `scene_data` property MUST return an object exposing the fields the actor reads (`scene_back_story`, `character_back_story`, `prev_scene_description`, `scene_description`, `steer_back_instruction`, `scene_supplement`).
- **`digital_actor.messenger.WebSocketServer`** — subclass and override `_handle_inbound(self, ws)` and `_handle_connection(self, ws)`. Call `await self._dispatch(msg, ws)` only for built-in types we want (we will NOT use most). `self._stage` is the stage; `self._runtime` is a `Runtime` that calls `stage.step` on tick — we will still let it run but the scene's `tick()` is a no-op.
- **`digital_actor.messenger.OutboundPayload`** is the frame the messenger delivers. `stage_context.deliver_text(line, ...)` and `deliver_speech(line, chunk, ...)` already build these. For new frame types (`followup_hint`, `scene_changed`, etc.) we send JSON directly over `ws` from the server, NOT through the messenger.
- **Existing `MetaHumanStage.load_scenario`** (read `metahuman_actor/stage.py`) is the template for atomic load: build everything locally, then swap.
- **`MetaHumanDigitalActor(persona: dict)`** — constructed from a parsed persona JSON dict with keys `id`, `display_name`, and optional `voice`.
- **`tts_lib.get_tts_client(provider, voice_id=, model_id=)`** builds a TTS client; returns something with `.sample_rate` and `async generate_audio(text)`.

### Test conventions

- Tests live under `tests/metahuman_actor/`. Use `pytest`, `tmp_path`, `monkeypatch`.
- Run a single test: `uv run pytest tests/metahuman_actor/test_x.py::test_name -v`
- Run a file: `uv run pytest tests/metahuman_actor/test_x.py -v`
- Async tests: the repo uses `pytest-asyncio`. Mark async tests with `@pytest.mark.asyncio` (check an existing async test, e.g. `tests/metahuman_actor/test_ws_scenario.py`, for the exact marker/auto-mode in use, and match it).

---

## File structure

New files (all created by this plan):

- `metahuman_actor/game_driven/__init__.py` — package marker.
- `metahuman_actor/game_driven/scenario.py` — `GameDrivenScenario` loader for the new on-disk layout + `list_game_driven_scenarios()`.
- `metahuman_actor/game_driven/scene_data.py` — `GameDrivenSceneData` (lore + trigger registry + checkpoints) and `TriggerConfig`. Reads all prompt content via `get_prompt` (NOT direct disk reads); discovers the trigger registry by listing the `triggers/` folder on disk and then loads each trigger body via `get_prompt`.
- `metahuman_actor/game_driven/world_state.py` — renders the `world_state` dict into the `## Current situation` prompt block.
- `metahuman_actor/game_driven/scene.py` — `GameDrivenScene` implementing `BaseScene`.
- `metahuman_actor/game_driven/stage.py` — `GameDrivenStage` (scenario lifecycle, scene/interaction switching).
- `metahuman_actor/game_driven/server.py` — `GameDrivenServer` (WS protocol) + `main()` + `__main__` block.

New prompt templates (created under `.langfuse_prompts/`):

- `.langfuse_prompts/dialogue/get_respond_line.txt`
- `.langfuse_prompts/dialogue/get_trigger_line.txt`

New test files:

- `tests/metahuman_actor/game_driven/__init__.py`
- `tests/metahuman_actor/game_driven/test_world_state.py`
- `tests/metahuman_actor/game_driven/test_scenario.py`
- `tests/metahuman_actor/game_driven/test_scene_data.py`
- `tests/metahuman_actor/game_driven/test_scene.py`
- `tests/metahuman_actor/game_driven/test_stage.py`
- `tests/metahuman_actor/game_driven/test_server.py`

A test fixture scenario tree is created on disk under `tmp_path` by helper functions in the tests (mirroring `test_scenario.py`'s `_make_scenario_on_disk`). Because prompt content flows through `get_prompt`, the fixture tree is placed under a `LOCAL_LANGFUSE_PATH` pointed at `tmp_path` and a local langfuse session is opened for the test (see the `local_prompts` fixture in Task 4).

Additional test file:

- `tests/metahuman_actor/game_driven/conftest.py` — the shared `local_prompts` fixture (env + local session pointed at `tmp_path`) reused across scene-data, scene, and stage tests.

**Future-Langfuse note (informational, not a task):** the scenario *loader* discovers structure (scenes, interactions, triggers) by walking the filesystem. When prompts later move to Langfuse, directory-walking won't enumerate remote prompts — the structure will need to come from an explicit manifest (e.g. fields in `scenario.json` listing scenes/interactions and each interaction listing its trigger names). v1 keeps filesystem discovery; this is flagged so the migration isn't a surprise.

---

## Task 1: Package scaffolding

**Files:**
- Create: `metahuman_actor/game_driven/__init__.py`
- Create: `tests/metahuman_actor/game_driven/__init__.py`

- [ ] **Step 1: Create the package markers**

`metahuman_actor/game_driven/__init__.py`:

```python
"""Game-driven (request-driven) dialogue server.

The server produces in-character NPC lines only when the game requests one.
It owns no clock: no tick-driven behaviour, no followup/idle timers, no
playback estimation. See docs/superpowers/specs/2026-06-03-game-driven-dialogue-server-design.md.
"""
```

`tests/metahuman_actor/game_driven/__init__.py`:

```python
```

- [ ] **Step 2: Verify the package imports**

Run: `uv run python -c "import metahuman_actor.game_driven"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add metahuman_actor/game_driven/__init__.py tests/metahuman_actor/game_driven/__init__.py
git commit -m "scaffold metahuman_actor.game_driven package"
```

---

## Task 2: World-state rendering

The game sends a `world_state` dict on every `respond`/`trigger`. The server renders it mechanically as a `## Current situation` block of `key: value` lines. No Jinja, no schema. Empty dict → empty string (the caller omits the section).

**Files:**
- Create: `metahuman_actor/game_driven/world_state.py`
- Test: `tests/metahuman_actor/game_driven/test_world_state.py`

- [ ] **Step 1: Write the failing test**

`tests/metahuman_actor/game_driven/test_world_state.py`:

```python
"""Tests for world_state rendering into a prompt block."""
from metahuman_actor.game_driven.world_state import render_world_state


def test_empty_dict_renders_empty_string():
    assert render_world_state({}) == ""


def test_none_renders_empty_string():
    assert render_world_state(None) == ""


def test_single_scalar():
    assert render_world_state({"time_of_day": "night"}) == "time_of_day: night"


def test_multiple_scalars_one_per_line_insertion_order():
    out = render_world_state({"time_of_day": "night", "reputation": "hostile"})
    assert out == "time_of_day: night\nreputation: hostile"


def test_bool_and_number_values():
    out = render_world_state({"armed": True, "gold": 5})
    assert out == "armed: True\ngold: 5"


def test_list_value_is_comma_joined():
    out = render_world_state({"recent_actions": ["stole gold", "killed guard"]})
    assert out == "recent_actions: stole gold, killed guard"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_world_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metahuman_actor.game_driven.world_state'`.

- [ ] **Step 3: Write minimal implementation**

`metahuman_actor/game_driven/world_state.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_world_state.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/world_state.py tests/metahuman_actor/game_driven/test_world_state.py
git commit -m "add world_state prompt rendering"
```

---

## Task 3: Scenario loader for the new layout

`GameDrivenScenario` discovers a scenario's structure: scenario config (`scenario.json`), persona files (`personas/*.json`), scenes (`scene_*/` directories), and per-scene/character/interaction content. It does NOT read prompt bodies (that's `GameDrivenSceneData` in Task 4) — it resolves paths and validates structure.

The on-disk layout (see spec):

```
scenarios/<scenario>/
  scenario.json                 {"default_character", "default_scene", "default_interaction"}
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
```

For v1, the loader exposes the *default* character/scene/interaction and helpers to resolve a `(scene, character, interaction)` triple to its directory.

**The loader roots scenarios at `<local-prompt-root>/scenarios/`** (via `resolve_local_langfuse_root()`), NOT `settings.scenarios_path`. This keeps prompt *content* (read by `get_prompt`) and structure *discovery* (filesystem walk) under one root, and puts new scenarios in the Langfuse namespace for a clean future upload. `prompts_root` is therefore `f"scenarios/{name}"`, so Task 4's names like `"scenarios/tavern/scene_1/scene_description"` resolve to `<root>/scenarios/tavern/scene_1/scene_description.txt` — the same file `data_root` points at.

**Files:**
- Create: `metahuman_actor/game_driven/scenario.py`
- Test: `tests/metahuman_actor/game_driven/test_scenario.py`

- [ ] **Step 1: Write the failing test**

`tests/metahuman_actor/game_driven/test_scenario.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scenario.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metahuman_actor.game_driven.scenario'`.

- [ ] **Step 3: Write minimal implementation**

`metahuman_actor/game_driven/scenario.py`:

```python
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

from langfuse_utils import resolve_local_langfuse_root


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
        data_root = _scenarios_root() / name
        if not data_root.is_dir():
            raise GameDrivenScenarioNotFoundError(name)
        config_path = data_root / "scenario.json"
        if not config_path.is_file():
            raise GameDrivenScenarioNotFoundError(name)
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        return cls(
            name=name,
            default_character=config["default_character"],
            default_scene=config["default_scene"],
            default_interaction=config["default_interaction"],
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scenario.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/scenario.py tests/metahuman_actor/game_driven/test_scenario.py
git commit -m "add GameDrivenScenario loader for new layout"
```

---

## Task 4: Scene-data model (lore + trigger registry)

`GameDrivenSceneData` loads the prompt content for one `(scene, character, interaction)` triple **through `get_prompt`** and discovers the trigger registry by listing the `triggers/` folder. It exposes the fields `MetaHumanDigitalActor.get_next_line_prompt_info` reads from `stage_context.scene_data` (`scene_back_story`, `character_back_story`, `prev_scene_description`, `scene_description`, `steer_back_instruction`, `scene_supplement`), so the actor's existing prompt-building works unchanged.

Prompt **names** are built from `scenario.prompts_root` plus the relative path, e.g. `f"{prompts_root}/{scene}/characters/{character}/{interaction}/steer_back_instructions"`. `get_prompt` resolves these under the local prompt root (or Langfuse remotely). Trigger prompt/narrator substitution uses `.compile(**info)` (`{{var}}` placeholders) — consistent with every other prompt and observable in traces.

**Prompt-root alignment (important):** for `get_prompt(name)` to resolve, the name must be relative to the local prompt root (`LOCAL_LANGFUSE_PATH`, default `.langfuse_prompts/`). Scenarios live at `<root>/scenarios/<name>/`, so `scenario.prompts_root` is `f"scenarios/{name}"`. In tests, the `local_prompts` fixture sets `LOCAL_LANGFUSE_PATH = tmp_path` and `write_scenario_tree` places the tree at `tmp_path/scenarios/<name>/...`, so `get_prompt("scenarios/tavern/scene_1/scene_description")` resolves to `tmp_path/scenarios/tavern/scene_1/scene_description.txt` — exactly where the loader's `data_root` points. Structure discovery (Task 3) and prompt content (Task 4) read from the same root.

`prev_scene_description` and `scene_supplement` have no source in the new layout, so they are empty strings. `checkpoints` defaults to an empty graph when no `checkpoints.json` exists. (Checkpoints are structured JSON, not prompts — loaded by reading the file directly; that's fine.)

A `_get_optional(name)` helper returns `""` when `get_prompt(name)` raises `FileNotFoundError`, for optional prompts like `opening_speech` and trigger `narrator`.

**Files:**
- Create: `tests/metahuman_actor/game_driven/conftest.py` (shared `local_prompts` fixture)
- Create: `metahuman_actor/game_driven/scene_data.py`
- Test: `tests/metahuman_actor/game_driven/test_scene_data.py`

- [ ] **Step 1: Write the shared fixture (conftest.py)**

`tests/metahuman_actor/game_driven/conftest.py`:

```python
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

    The scene builds prompts via get_prompt("dialogue/get_respond_line") etc.,
    which must resolve under the test's LOCAL_LANGFUSE_PATH. We copy the real
    templates (created in Task 5 and already present in .langfuse_prompts/) so
    tests exercise the real templates, not stubs.
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
```

The `from metahuman_actor.settings import settings as global_settings` import in conftest is no longer needed (the loader uses the langfuse root, not `scenarios_path`). Drop it from the conftest imports.

Note: `Path(__file__).resolve().parents[3]` resolves the repo root from `tests/metahuman_actor/game_driven/conftest.py` (3 levels up: `game_driven` → `metahuman_actor` → `tests` → repo root). Verify this depth matches the actual tree when implementing; adjust the index if the test path differs.

Note on prompt-root alignment: `GameDrivenScenario` (Task 3) roots scenarios at `<local-prompt-root>/scenarios/<name>` and its `prompts_root` is `f"scenarios/{name}"`. The `local_prompts` fixture sets `LOCAL_LANGFUSE_PATH = tmp_path` and writes the tree at `tmp_path/scenarios/<name>/...`. So a prompt name `"scenarios/<name>/scene_1/scene_description"` resolves to the same file the loader's `data_root` points at. Content + structure share one root.

- [ ] **Step 2: Write the failing test**

`tests/metahuman_actor/game_driven/test_scene_data.py`:

```python
"""Tests for GameDrivenSceneData loading (via get_prompt) and trigger discovery."""
from __future__ import annotations

import pytest

from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData

from .conftest import write_scenario_tree


def _scenario(langfuse_root, **kwargs):
    write_scenario_tree(langfuse_root, **kwargs)
    return GameDrivenScenario.load("tavern")


def test_loads_lore_fields(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.scene_back_story == "The tavern arc."
    assert data.character_back_story == "Zeek is wary."
    assert data.scene_description == "scene_1 desc."
    assert data.steer_back_instruction == "converse steer."
    assert data.opening_speech == "[Zeek]: Well met."
    assert data.prev_scene_description == ""
    assert data.scene_supplement == ""


def test_discovers_triggers(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert set(data.triggers.keys()) == {"greet", "player_drew_weapon"}


def test_no_triggers_folder_yields_empty_registry(local_prompts):
    scenario = _scenario(local_prompts, with_triggers=False)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.triggers == {}


def test_optional_opening_speech_absent(local_prompts):
    scenario = _scenario(local_prompts)
    # Remove the opening_speech prompt file.
    (scenario.interaction_dir("scene_1", "zeek", "converse") / "opening_speech.txt").unlink()
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.opening_speech == ""


def test_checkpoints_default_empty_when_absent(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.checkpoints.is_finished() is True


def test_render_trigger_prompt_substitutes_info(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    rendered = data.triggers["player_drew_weapon"].render_prompt({"weapon": "sword"})
    assert rendered == "The player drew sword. React."


def test_render_trigger_narrator_substitutes_info(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    rendered = data.triggers["player_drew_weapon"].render_narrator({"weapon": "sword"})
    assert rendered == "The player draws their sword."


def test_render_trigger_narrator_none_when_no_template(local_prompts):
    scenario = _scenario(local_prompts)
    data = GameDrivenSceneData.load(scenario, scene="scene_1", character="zeek", interaction="converse")
    assert data.triggers["greet"].render_narrator({}) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metahuman_actor.game_driven.scene_data'`.

- [ ] **Step 4: Write minimal implementation**

`metahuman_actor/game_driven/scene_data.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene_data.py -v`
Expected: PASS (8 passed).

- [ ] **Step 6: Commit**

```bash
git add tests/metahuman_actor/game_driven/conftest.py metahuman_actor/game_driven/scene_data.py tests/metahuman_actor/game_driven/test_scene_data.py
git commit -m "add GameDrivenSceneData (prompt content via get_prompt) + shared fixture"
```

---

## Task 5: Prompt templates for respond and trigger

Two top-level line-generation templates. They share scaffolding now but are kept separate so they can diverge. They are placed in the flat `.langfuse_prompts/dialogue/` namespace so `get_prompt("dialogue/get_respond_line")` finds them when running with `--langfuse-local`.

**Files:**
- Create: `.langfuse_prompts/dialogue/get_respond_line.txt`
- Create: `.langfuse_prompts/dialogue/get_trigger_line.txt`

- [ ] **Step 1: Create `get_respond_line.txt`**

`.langfuse_prompts/dialogue/get_respond_line.txt`:

```
{{scene_back_story}}

# Character
{{character_back_story}}

# Scene
{{scene_description}}

{{current_situation_wrapper}}# Speakers
{{actors}}

{{dialogue_summary_wrapper}}# Dialogue
{{dialogue}}

{{steer_back_instructions}}
The player has just spoken to {{actor_name}}. Write {{actor_name}}'s next spoken line, in character. Output only the line.
```

- [ ] **Step 2: Create `get_trigger_line.txt`**

`.langfuse_prompts/dialogue/get_trigger_line.txt`:

```
{{scene_back_story}}

# Character
{{character_back_story}}

# Scene
{{scene_description}}

{{current_situation_wrapper}}# Recent event
{{trigger_prompt}}

# Speakers
{{actors}}

{{dialogue_summary_wrapper}}# Dialogue
{{dialogue}}

{{steer_back_instructions}}
Given the recent event above, write {{actor_name}}'s next spoken line, in character. Output only the line.
```

- [ ] **Step 3: Verify the templates resolve through get_prompt in local mode**

Run:
```bash
uv run python -c "
import os; os.environ['LOCAL_LANGFUSE_PATH']='.langfuse_prompts'
from langfuse_utils import langfuse_session, get_prompt
with langfuse_session(local=True):
    print(get_prompt('dialogue/get_respond_line').compile(
        scene_back_story='', character_back_story='', scene_description='',
        steer_back_instructions='', current_situation_wrapper='',
        dialogue_summary_wrapper='', actors='Zeek, Player', actor_name='Zeek', dialogue='')[:60])
"
```
Expected: prints the rendered template head (placeholders substituted, no `{{...}}` left for the provided keys). Confirms the template is resolvable and compiles via the real seam. Full behavior is exercised in Task 6.

- [ ] **Step 4: Commit**

```bash
git add .langfuse_prompts/dialogue/get_respond_line.txt .langfuse_prompts/dialogue/get_trigger_line.txt
git commit -m "add respond/trigger line-generation prompt templates"
```

---

## Task 6: GameDrivenScene — respond path (no followup yet)

`GameDrivenScene` implements `BaseScene`. This task builds the actor, history, response lock, and the `respond` path: record `Player:`, build the prompt, generate the line, stream TTS. No followup hint yet (Task 8), no triggers yet (Task 7).

The scene needs its own prompt-building because the actor's `get_next_line_prompt_info` uses the *authoritative* `dialogue/get_next_line` template. We override line generation at the scene level: the scene builds a `PromptInfo` with `get_respond_line` and calls `stage_context.llm_acomplete`, then records and delivers the line directly. This avoids reusing `SceneDigitalActor.generate_next_text` (which is hard-wired to the actor's own template).

A test seam: the scene must work with a fake LLM. We construct the scene with a real `MetaHumanDigitalActor` but drive it through a `GameDrivenStage` (Task 9) in integration tests. For this task's unit tests, we install a stub stage via `set_stage` that returns canned LLM output and records delivered payloads.

**Files:**
- Create: `metahuman_actor/game_driven/scene.py`
- Test: `tests/metahuman_actor/game_driven/test_scene.py`

- [ ] **Step 1: Write the failing test**

`tests/metahuman_actor/game_driven/test_scene.py`:

```python
"""Unit tests for GameDrivenScene using a stub stage."""
from __future__ import annotations

import pytest

from digital_actor.data_models import PromptInfo
from digital_actor.dialogue import PLAYER_ROLE_NAME, NARRATOR_ROLE_NAME
from digital_actor.messenger import OutboundPayload
from digital_actor.stage_context import set_stage

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene import GameDrivenScene
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData

from .conftest import write_scenario_tree


class StubStage:
    """Minimal stage_context surface for driving GameDrivenScene in tests."""

    def __init__(self, llm_reply="A canned line."):
        self._llm_reply = llm_reply
        self.elapsed_time = 0.0
        self.tts_client = None  # disables TTS; run_tts emits a single final frame
        self.delivered: list[OutboundPayload] = []
        self.prompts: list[str] = []

    async def llm_acomplete(self, prompt_info: PromptInfo, obs_name="completion") -> str:
        self.prompts.append(prompt_info.prompt)
        return self._llm_reply

    def llm_complete(self, prompt_info: PromptInfo, obs_name="completion") -> str:
        self.prompts.append(prompt_info.prompt)
        return self._llm_reply

    @property
    def scene_data(self):
        return self._scene_data

    def set_scene_data(self, sd):
        self._scene_data = sd

    def deliver_text(self, line, **kwargs):
        self.delivered.append(OutboundPayload(actor_name=line.name, text=line.text, line_id=line.line_id))

    def deliver_speech(self, line, chunk, **kwargs):
        self.delivered.append(
            OutboundPayload(
                actor_name=line.name,
                audio_chunk=chunk,
                line_id=line.line_id,
                is_final_audio=kwargs.get("is_final_audio", False),
            )
        )

    def deliver_event(self, event):
        pass


@pytest.fixture
def scene_and_stage(local_prompts):
    # local_prompts (from conftest.py) activates local langfuse mode pointed at
    # tmp_path and seeds the dialogue/common/query templates. Build the scenario
    # tree there, then load scene_data through get_prompt.
    write_scenario_tree(local_prompts)
    scenario = GameDrivenScenario.load("tavern")
    scene_data = GameDrivenSceneData.load(
        scenario, scene="scene_1", character="zeek", interaction="converse"
    )
    actor = MetaHumanDigitalActor({"id": "zeek", "display_name": "Zeek"})
    stage = StubStage()
    stage.set_scene_data(scene_data)
    set_stage(stage)
    scene = GameDrivenScene(actor=actor, scene_data=scene_data, suggested_delay_seconds=6.0)
    return scene, stage


@pytest.mark.asyncio
async def test_respond_records_player_and_generates_line(scene_and_stage):
    scene, stage = scene_and_stage
    line = await scene.respond("Hello there", world_state={"time_of_day": "night"})
    # Player line recorded, then actor line.
    roles = [m.name for m in scene.actor.history.messages]
    assert PLAYER_ROLE_NAME in roles
    assert scene.actor.name in roles
    # The actor's line was delivered as text.
    text_frames = [p for p in stage.delivered if p.text is not None]
    assert any(p.text == "A canned line." for p in text_frames)
    assert line.text == "A canned line."


@pytest.mark.asyncio
async def test_respond_prompt_includes_world_state_block(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.respond("Hello", world_state={"time_of_day": "night"})
    assert any("time_of_day: night" in p for p in stage.prompts)


@pytest.mark.asyncio
async def test_respond_empty_text_raises(scene_and_stage):
    scene, stage = scene_and_stage
    with pytest.raises(ValueError):
        await scene.respond("   ", world_state={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metahuman_actor.game_driven.scene'`.

- [ ] **Step 3: Write minimal implementation**

Implementation note: the scene builds the `respond` prompt with `langfuse_utils.get_prompt("dialogue/get_respond_line").compile(...)`. The `current_situation_wrapper` is the rendered world_state wrapped in a `# Current situation` header (or empty). The `dialogue_summary_wrapper` mirrors the existing actor code. The scene records the actor line via `history.add_message(self.actor.name, response)` and delivers it via `stage_context.deliver_text`, then `run_tts`.

`metahuman_actor/game_driven/scene.py`:

```python
"""GameDrivenScene — request-driven dialogue, no server-side clock.

Implements the library BaseScene but ignores tick/idle/followup-timer
behaviour. Lines are produced only when the game calls respond()/trigger().
"""
from __future__ import annotations

import asyncio

from app_logging import get_logger
from digital_actor.data_models import PromptInfo
from digital_actor.dialogue import NARRATOR_ROLE_NAME, PLAYER_ROLE_NAME, DialogueLine
from digital_actor.scene import BaseScene
from langfuse_utils import get_prompt
from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData
from metahuman_actor.game_driven.world_state import render_world_state

logger = get_logger(__name__)


class GameDrivenScene(BaseScene):
    def __init__(
        self,
        actor: MetaHumanDigitalActor,
        scene_data: GameDrivenSceneData,
        suggested_delay_seconds: float = 6.0,
    ) -> None:
        self.actor = actor
        self.scene_data = scene_data
        self.suggested_delay_seconds = suggested_delay_seconds
        self._response_lock = asyncio.Lock()

    # --- BaseScene abstract methods (mostly inert in this path) ---

    async def tick(self) -> None:
        return

    async def on_interrupt(self, line_id: str, elapsed_seconds: float) -> None:
        return

    async def on_game_event(self, name: str, event_info: dict[str, str]) -> None:
        # Event handling arrives via trigger(); BaseScene's hook is unused here.
        return

    async def on_user_input(self, message: str, emotions: list[str] | None = None) -> None:
        await self.respond(message, world_state={}, emotions=emotions)

    def reset(self) -> None:
        self.actor.reset()

    # --- request entry points ---

    async def respond(
        self,
        text: str,
        world_state: dict | None,
        emotions: list[str] | None = None,
    ) -> DialogueLine:
        if not text or not text.strip():
            raise ValueError("respond: empty text")
        async with self._response_lock:
            self.actor.history.add_message(PLAYER_ROLE_NAME, text.strip())
            prompt_info = self._build_line_prompt(
                template="dialogue/get_respond_line",
                world_state=world_state,
                trigger_prompt=None,
            )
            line = await self._generate_and_deliver(prompt_info, emotions)
            await self.actor.history.summarize_if_needed()
            return line

    # --- internals ---

    def _build_line_prompt(
        self,
        *,
        template: str,
        world_state: dict | None,
        trigger_prompt: str | None,
    ) -> PromptInfo:
        situation = render_world_state(world_state)
        current_situation_wrapper = (
            f"# Current situation\n{situation}\n\n" if situation else ""
        )
        dialogue_summary_wrapper = ""
        if self.actor.history.summary:
            dialogue_summary_wrapper = get_prompt("common/dialogue_summary_wrapper").compile(
                dialogue_summary=self.actor.history.summary
            )
        prompt_input: dict = {
            "scene_back_story": self.scene_data.scene_back_story,
            "character_back_story": self.scene_data.character_back_story,
            "scene_description": self.scene_data.scene_description,
            "steer_back_instructions": self.scene_data.steer_back_instruction,
            "current_situation_wrapper": current_situation_wrapper,
            "dialogue_summary_wrapper": dialogue_summary_wrapper,
            "actors": ", ".join([self.actor.name, PLAYER_ROLE_NAME]),
            "actor_name": self.actor.name,
            "dialogue": self.actor.history.to_string(include_summary=False),
        }
        if trigger_prompt is not None:
            prompt_input["trigger_prompt"] = trigger_prompt
        prompt = get_prompt(template)
        compiled = prompt.compile(**prompt_input)
        return PromptInfo(prompt=compiled, input_args=prompt_input, langfuse_prompt=prompt)

    async def _generate_and_deliver(
        self, prompt_info: PromptInfo, emotions: list[str] | None
    ) -> DialogueLine:
        from digital_actor.stage_context import stage_context

        response = await stage_context.llm_acomplete(prompt_info, obs_name="generate_next_line")
        line = self.actor.history.add_message(self.actor.name, response)
        emotion = line.tags[0] if line.tags else None
        intensity = line.tags[1] if len(line.tags) > 1 else None
        stage_context.deliver_text(line, interruptible=True, emotion=emotion, intensity=intensity)
        await self.actor.run_tts(line)
        return line
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene.py -v`
Expected: PASS (3 passed).

Note: if `to_string` requires a non-empty history or `summarize_if_needed` calls back into the stub, the stub's `llm_complete` already returns a canned reply; `summarize_if_needed` only triggers past a length threshold and should no-op for a 2-message history.

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/scene.py tests/metahuman_actor/game_driven/test_scene.py
git commit -m "add GameDrivenScene respond path"
```

---

## Task 7: GameDrivenScene — trigger path

Add `trigger(name, info, world_state, ...)`. Look up the trigger in `scene_data.triggers`; unknown → `KeyError` (caller surfaces as error frame). If it has a narrator template, render it with `info` and add a `Narrator:` line. Build the prompt with `get_trigger_line` and the rendered trigger prompt. Also evaluate matching event checkpoints (existing library mechanism).

**Files:**
- Modify: `metahuman_actor/game_driven/scene.py`
- Test: `tests/metahuman_actor/game_driven/test_scene.py` (add tests)

- [ ] **Step 1: Write the failing tests (append to test_scene.py)**

Append to `tests/metahuman_actor/game_driven/test_scene.py`. The `scene_and_stage` fixture already builds a scenario via `write_scenario_tree`, which includes a `greet` trigger (no narrator) and a `player_drew_weapon` trigger (with a `{{weapon}}` narrator) — so the trigger tests reuse `scene_and_stage` directly, no new fixture needed.

```python
@pytest.mark.asyncio
async def test_trigger_generates_line(scene_and_stage):
    scene, stage = scene_and_stage
    line = await scene.trigger("greet", info={}, world_state={})
    assert line.text == "A canned line."
    assert any("The player approaches" in p for p in stage.prompts)


@pytest.mark.asyncio
async def test_trigger_with_narrator_adds_narrator_line(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.trigger("player_drew_weapon", info={"weapon": "sword"}, world_state={})
    narrator_lines = [m for m in scene.actor.history.messages if m.name == NARRATOR_ROLE_NAME]
    assert any("The player draws their sword." == m.text for m in narrator_lines)


@pytest.mark.asyncio
async def test_trigger_without_narrator_adds_no_narrator_line(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.trigger("greet", info={}, world_state={})
    narrator_lines = [m for m in scene.actor.history.messages if m.name == NARRATOR_ROLE_NAME]
    assert narrator_lines == []


@pytest.mark.asyncio
async def test_unknown_trigger_raises_keyerror(scene_and_stage):
    scene, stage = scene_and_stage
    with pytest.raises(KeyError):
        await scene.trigger("does_not_exist", info={}, world_state={})


@pytest.mark.asyncio
async def test_trigger_prompt_includes_substituted_info(scene_and_stage):
    scene, stage = scene_and_stage
    await scene.trigger("player_drew_weapon", info={"weapon": "axe"}, world_state={})
    assert any("The player drew axe. React." in p for p in stage.prompts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene.py -k trigger -v`
Expected: FAIL with `AttributeError: 'GameDrivenScene' object has no attribute 'trigger'`.

- [ ] **Step 3: Add the trigger method (insert into scene.py after `respond`)**

Add this method to `GameDrivenScene` (in `metahuman_actor/game_driven/scene.py`), directly below `respond`:

```python
    async def trigger(
        self,
        name: str,
        info: dict[str, str],
        world_state: dict | None,
        request_followup_hint: bool = False,
    ) -> DialogueLine:
        config = self.scene_data.triggers[name]  # KeyError -> caller emits error frame
        async with self._response_lock:
            narrator = config.render_narrator(info)
            if narrator is not None:
                self.actor.history.add_message(NARRATOR_ROLE_NAME, narrator)
            self._evaluate_event_checkpoints(name)
            prompt_info = self._build_line_prompt(
                template="dialogue/get_trigger_line",
                world_state=world_state,
                trigger_prompt=config.render_prompt(info),
            )
            line = await self._generate_and_deliver(prompt_info, emotions=None)
            await self.actor.history.summarize_if_needed()
            return line

    def _evaluate_event_checkpoints(self, name: str) -> None:
        from digital_actor.checkpoints import EventCheckpoint
        from digital_actor.stage_context import stage_context

        checkpoints = self.scene_data.checkpoints
        if not checkpoints or not checkpoints.nodes:
            return
        for node in checkpoints.active_nodes():
            if isinstance(node, EventCheckpoint) and node.event_id == name:
                if node.narrator_message and "true" in node.narrator_message:
                    self.actor.history.add_message(
                        NARRATOR_ROLE_NAME, node.narrator_message["true"]
                    )
                checkpoints.complete(node.id)
                for callback in node.callbacks or []:
                    from digital_actor.game_events import GameEvent

                    stage_context.deliver_event(GameEvent(name=callback, info={}))
                break
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene.py -v`
Expected: PASS (all `respond` and `trigger` tests pass).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/scene.py tests/metahuman_actor/game_driven/test_scene.py
git commit -m "add GameDrivenScene trigger path with narrator + event checkpoints"
```

---

## Task 8: Followup hint computation

When `request_followup_hint` is true, the scene runs the existing `query_followup` (the `MetaHumanSingleActorScene.get_query_followup_prompt_info` logic) after line generation and returns a hint object. The scene does NOT send the wire frame itself — it returns a `FollowupHint` (or `None`) so the server can emit it. This keeps the scene transport-agnostic.

**v1 runs the followup query sequentially after TTS, inside the response lock.** The spec's design intent is to run it *concurrently* with TTS streaming to hide latency. We defer that optimization: running it after `run_tts` (still inside the lock) keeps the hint strictly tied to a completed line and avoids a background task that could emit a hint after the lock releases and the scene has since switched. The hint is paired by `line_id` regardless, so a later move to a concurrent `asyncio.gather`/`create_task` is a safe, isolated change. Note this in a code comment so the optimization is discoverable.

The followup query reuses the same prompt-building approach as the authoritative scene. To avoid duplicating ~25 lines, we lift the followup-prompt builder into the scene.

**Files:**
- Modify: `metahuman_actor/game_driven/scene.py`
- Test: `tests/metahuman_actor/game_driven/test_scene.py` (add tests)

- [ ] **Step 1: Write the failing tests (append to test_scene.py)**

```python
@pytest.mark.asyncio
async def test_respond_returns_followup_hint_when_requested(scene_and_stage, monkeypatch):
    scene, stage = scene_and_stage

    # Force the followup query to return "yes".
    async def fake_query(prompt_info, obs_name="completion"):
        if obs_name == "query_followup":
            return "YES"
        return "A canned line."

    stage.llm_acomplete = fake_query  # type: ignore[assignment]
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=True
    )
    assert hint is not None
    assert hint.available is True
    assert hint.line_id == line.line_id
    assert hint.suggested_delay_seconds == scene.suggested_delay_seconds


@pytest.mark.asyncio
async def test_respond_no_hint_when_not_requested(scene_and_stage):
    scene, stage = scene_and_stage
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=False
    )
    assert hint is None


@pytest.mark.asyncio
async def test_followup_hint_available_false_when_query_no(scene_and_stage):
    scene, stage = scene_and_stage

    async def fake_query(prompt_info, obs_name="completion"):
        if obs_name == "query_followup":
            return "NO"
        return "A canned line."

    stage.llm_acomplete = fake_query  # type: ignore[assignment]
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=True
    )
    assert hint is not None
    assert hint.available is False


@pytest.mark.asyncio
async def test_followup_query_failure_returns_no_hint(scene_and_stage):
    scene, stage = scene_and_stage

    async def fake_query(prompt_info, obs_name="completion"):
        if obs_name == "query_followup":
            raise RuntimeError("llm down")
        return "A canned line."

    stage.llm_acomplete = fake_query  # type: ignore[assignment]
    line, hint = await scene.respond_with_hint(
        "Hello", world_state={}, request_followup_hint=True
    )
    # Query failure is silent: line still produced, no hint.
    assert line.text == "A canned line."
    assert hint is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene.py -k followup -v`
Expected: FAIL with `AttributeError: 'GameDrivenScene' object has no attribute 'respond_with_hint'`.

- [ ] **Step 3: Implement followup hint (modify scene.py)**

Add a `FollowupHint` dataclass at module level in `scene.py` (below the imports):

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FollowupHint:
    line_id: str
    available: bool
    suggested_delay_seconds: float
```

Add the `respond_with_hint` and `trigger_with_hint` methods and the followup query helper to `GameDrivenScene`. Refactor `respond`/`trigger` to delegate. Replace the existing `respond` and `trigger` methods with versions that return only the line (for the existing tests) by having them call the `*_with_hint` variants and discard the hint:

```python
    async def respond(self, text, world_state, emotions=None):
        line, _ = await self.respond_with_hint(
            text, world_state, emotions=emotions, request_followup_hint=False
        )
        return line

    async def respond_with_hint(
        self, text, world_state, emotions=None, request_followup_hint=False
    ) -> tuple[DialogueLine, "FollowupHint | None"]:
        if not text or not text.strip():
            raise ValueError("respond: empty text")
        async with self._response_lock:
            self.actor.history.add_message(PLAYER_ROLE_NAME, text.strip())
            prompt_info = self._build_line_prompt(
                template="dialogue/get_respond_line",
                world_state=world_state,
                trigger_prompt=None,
            )
            line = await self._generate_and_deliver(prompt_info, emotions)
            hint = await self._maybe_followup_hint(line, request_followup_hint)
            await self.actor.history.summarize_if_needed()
            return line, hint

    async def trigger(self, name, info, world_state, request_followup_hint=False):
        line, _ = await self.trigger_with_hint(
            name, info, world_state, request_followup_hint=False
        )
        return line

    async def trigger_with_hint(
        self, name, info, world_state, request_followup_hint=False
    ) -> tuple[DialogueLine, "FollowupHint | None"]:
        config = self.scene_data.triggers[name]
        async with self._response_lock:
            narrator = config.render_narrator(info)
            if narrator is not None:
                self.actor.history.add_message(NARRATOR_ROLE_NAME, narrator)
            self._evaluate_event_checkpoints(name)
            prompt_info = self._build_line_prompt(
                template="dialogue/get_trigger_line",
                world_state=world_state,
                trigger_prompt=config.render_prompt(info),
            )
            line = await self._generate_and_deliver(prompt_info, emotions=None)
            hint = await self._maybe_followup_hint(line, request_followup_hint)
            await self.actor.history.summarize_if_needed()
            return line, hint

    async def _maybe_followup_hint(
        self, line: DialogueLine, request_followup_hint: bool
    ) -> "FollowupHint | None":
        if not request_followup_hint:
            return None
        try:
            available = await self._query_followup()
        except Exception:
            logger.exception("followup query failed; emitting no hint")
            return None
        return FollowupHint(
            line_id=line.line_id,
            available=available,
            suggested_delay_seconds=self.suggested_delay_seconds,
        )

    async def _query_followup(self) -> bool:
        from digital_actor.stage_context import stage_context

        prompt_info = self._build_followup_prompt()
        response = await stage_context.llm_acomplete(prompt_info, obs_name="query_followup")
        return response.strip().lower() in ("yes", "true")

    def _build_followup_prompt(self) -> PromptInfo:
        history = self.actor.history
        last = history.last_actor_line()
        if last is None:
            raise RuntimeError("query_followup invoked before the actor has spoken")
        last_line, last_idx = last
        dialogue = "\n\n".join(
            f"{m.name}: {m.text}"
            for m in history.messages[history.summary_idx : last_idx + 1]
            if m.name != NARRATOR_ROLE_NAME
        )
        dialogue_summary_wrapper = ""
        if history.summary:
            dialogue_summary_wrapper = get_prompt("common/dialogue_summary_wrapper").compile(
                dialogue_summary=history.summary
            )
        prompt = get_prompt("query/query_followup")
        prompt_input = {
            "scene_description": self.scene_data.scene_description,
            "actors": ", ".join([self.actor.name, PLAYER_ROLE_NAME]),
            "dialogue": dialogue,
            "dialogue_summary_wrapper": dialogue_summary_wrapper,
            "last_line": f"{last_line.name}: {last_line.text}",
        }
        compiled = prompt.compile(**prompt_input)
        return PromptInfo(prompt=compiled, input_args=prompt_input, langfuse_prompt=prompt)
```

Remove the now-duplicated original `respond`/`trigger` bodies so only the delegating versions remain.

- [ ] **Step 4: Run all scene tests to verify they pass**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scene.py -v`
Expected: PASS (all respond, trigger, and followup tests pass).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/scene.py tests/metahuman_actor/game_driven/test_scene.py
git commit -m "add followup hint computation to GameDrivenScene"
```

---

## Task 9: GameDrivenStage — scenario lifecycle + switching

`GameDrivenStage` subclasses the library `BaseStage` (via `SingleSceneStage`-style minimal stage). It owns `load_scenario`, `unload_scenario`, `set_scene`, `set_interaction`, and exposes a `scene_data` property for `stage_context` (the actor reads `stage_context.scene_data`). It builds the TTS client from the persona's `voice`.

The stage holds the `GameDrivenScene`. On load it constructs actor + scene_data + scene atomically (mirroring `MetaHumanStage.load_scenario`). On `set_scene`/`set_interaction` it rebuilds `scene_data` and swaps it on the scene while preserving `actor.history`.

**Files:**
- Create: `metahuman_actor/game_driven/stage.py`
- Test: `tests/metahuman_actor/game_driven/test_stage.py`

- [ ] **Step 1: Write the failing test**

`tests/metahuman_actor/game_driven/test_stage.py`:

```python
"""Tests for GameDrivenStage lifecycle and switching (TTS disabled)."""
from __future__ import annotations

import pytest

from metahuman_actor.game_driven.stage import GameDrivenStage

from .conftest import write_scenario_tree


@pytest.fixture
def stage(local_prompts):
    # Two scenes, two interactions, so set_scene / set_interaction have targets.
    # scene_description renders as "<scene> desc." and steer as "<interaction> steer."
    write_scenario_tree(
        local_prompts,
        scenes=("scene_1", "scene_2"),
        interactions=("converse", "barter"),
    )
    return GameDrivenStage(llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False)


@pytest.mark.asyncio
async def test_starts_empty(stage):
    assert stage.scenario is None
    assert stage.scene_data is None


@pytest.mark.asyncio
async def test_load_scenario_populates(stage):
    await stage.load_scenario("tavern")
    assert stage.scenario is not None
    assert stage.scene_data is not None
    assert stage.current_scene == "scene_1"
    assert stage.current_interaction == "converse"
    assert stage.actor.name == "Zeek"


@pytest.mark.asyncio
async def test_unload_returns_to_empty(stage):
    await stage.load_scenario("tavern")
    await stage.unload_scenario()
    assert stage.scenario is None
    assert stage.scene_data is None
    assert stage.actor is None


@pytest.mark.asyncio
async def test_unload_when_empty_is_noop(stage):
    await stage.unload_scenario()  # must not raise
    assert stage.scenario is None


@pytest.mark.asyncio
async def test_set_interaction_swaps_and_preserves_history(stage):
    await stage.load_scenario("tavern")
    stage.actor.history.add_message("Player", "earlier message")
    await stage.set_interaction("zeek", "barter")
    assert stage.current_interaction == "barter"
    assert "barter steer." == stage.scene_data.steer_back_instruction
    # History preserved across the switch.
    assert any(m.text == "earlier message" for m in stage.actor.history.messages)


@pytest.mark.asyncio
async def test_set_interaction_unknown_raises_and_keeps_state(stage):
    await stage.load_scenario("tavern")
    with pytest.raises(Exception):
        await stage.set_interaction("zeek", "nonexistent")
    assert stage.current_interaction == "converse"


@pytest.mark.asyncio
async def test_set_scene_swaps_and_resets_interaction(stage):
    await stage.load_scenario("tavern")
    await stage.set_interaction("zeek", "barter")
    stage.actor.history.add_message("Player", "carry me")
    await stage.set_scene("scene_2")
    assert stage.current_scene == "scene_2"
    # Interaction reset to scenario default.
    assert stage.current_interaction == "converse"
    assert "scene_2 desc." == stage.scene_data.scene_description
    # History preserved.
    assert any(m.text == "carry me" for m in stage.actor.history.messages)


@pytest.mark.asyncio
async def test_set_scene_unknown_raises_and_keeps_state(stage):
    await stage.load_scenario("tavern")
    with pytest.raises(Exception):
        await stage.set_scene("scene_99")
    assert stage.current_scene == "scene_1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_stage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metahuman_actor.game_driven.stage'`.

- [ ] **Step 3: Write minimal implementation**

`metahuman_actor/game_driven/stage.py`:

```python
"""GameDrivenStage — owns scenario lifecycle for the request-driven server.

Builds the actor + scene atomically on load, swaps scene_data on
set_scene/set_interaction while preserving actor history, and exposes the
scene_data property that stage_context (and thus the actor's prompt builder)
reads.
"""
from __future__ import annotations

import json

from app_logging import get_logger
from digital_actor.game_events import GameEventBase
from digital_actor.messenger import Messenger, MessengerType
from digital_actor.stage import SingleSceneStage
from tts_lib import get_tts_client

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene import GameDrivenScene
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData

logger = get_logger(__name__)


class UnknownSceneError(ValueError):
    pass


class UnknownInteractionError(ValueError):
    pass


class UnknownNpcError(ValueError):
    pass


class GameDrivenStage(SingleSceneStage):
    _scene: GameDrivenScene | None

    def __init__(
        self,
        llm_model: str,
        messenger: Messenger | MessengerType | None = None,
        tts_enabled: bool = True,
    ) -> None:
        super().__init__(
            llm_model,
            tts_provider=None,
            tts_voice_id=None,
            tts_model_id=None,
            messenger=messenger,
        )
        self._scenario: GameDrivenScenario | None = None
        self.actor: MetaHumanDigitalActor | None = None
        self.current_scene: str | None = None
        self.current_interaction: str | None = None
        self._tts_enabled = tts_enabled
        logger.info("GameDrivenStage ready (no scenario loaded)")

    @property
    def scenario(self) -> GameDrivenScenario | None:
        return self._scenario

    @property
    def scene_data(self) -> GameDrivenSceneData | None:
        if self._scene is None:
            return None
        return self._scene.scene_data

    async def on_game_event(self, event: GameEventBase) -> None:
        return

    async def on_user_input(self, message: str) -> None:
        if self._scene is not None:
            await self._scene.on_user_input(message)

    def _build_scene_data(self, scene: str, interaction: str) -> GameDrivenSceneData:
        assert self._scenario is not None and self.actor is not None
        return GameDrivenSceneData.load(
            self._scenario,
            scene=scene,
            character=self._scenario.default_character,
            interaction=interaction,
        )

    async def load_scenario(self, name: str) -> None:
        new_scenario = GameDrivenScenario.load(name)
        persona_path = new_scenario.persona_path(new_scenario.default_character)
        with open(persona_path, encoding="utf-8") as f:
            persona = json.load(f)
        voice = (persona.get("voice") or {}) if self._tts_enabled else {}
        new_actor = MetaHumanDigitalActor(persona)
        new_scene_data = GameDrivenSceneData.load(
            new_scenario,
            scene=new_scenario.default_scene,
            character=new_scenario.default_character,
            interaction=new_scenario.default_interaction,
        )
        new_tts = (
            get_tts_client(
                voice.get("provider"),
                voice_id=voice.get("voice_id"),
                model_id=voice.get("model_id"),
            )
            if voice.get("provider")
            else None
        )
        new_scene = GameDrivenScene(actor=new_actor, scene_data=new_scene_data)

        if self._scenario is not None:
            await self.await_idle()
        self.reset()
        self._scenario = new_scenario
        self.actor = new_actor
        self.current_scene = new_scenario.default_scene
        self.current_interaction = new_scenario.default_interaction
        self._tts_client = new_tts
        self.register_scene(new_scene)
        logger.info("Loaded game-driven scenario=%s", new_scenario.name)

    async def unload_scenario(self) -> None:
        if self._scenario is None:
            return
        await self.await_idle()
        self.reset()
        self._scene = None
        self._scenario = None
        self.actor = None
        self.current_scene = None
        self.current_interaction = None
        self._tts_client = None
        logger.info("Unloaded game-driven scenario")

    async def set_scene(self, scene: str) -> None:
        if self._scenario is None:
            raise UnknownSceneError("no scenario loaded")
        if not self._scenario.has_scene(scene):
            raise UnknownSceneError(scene)
        interaction = self._scenario.default_interaction
        if not self._scenario.has_interaction(
            scene, self._scenario.default_character, interaction
        ):
            raise UnknownInteractionError(f"{scene}/{interaction}")
        new_scene_data = self._build_scene_data(scene, interaction)
        await self.await_idle()
        self.current_scene = scene
        self.current_interaction = interaction
        assert self._scene is not None
        self._scene.scene_data = new_scene_data
        logger.info("Scene -> %s (interaction reset to %s)", scene, interaction)

    async def set_interaction(self, npc: str, interaction: str) -> None:
        if self._scenario is None or self.actor is None:
            raise UnknownNpcError("no scenario loaded")
        if npc != self._scenario.default_character:
            raise UnknownNpcError(npc)
        if not self._scenario.has_interaction(
            self.current_scene, npc, interaction
        ):
            raise UnknownInteractionError(interaction)
        new_scene_data = self._build_scene_data(self.current_scene, interaction)
        await self.await_idle()
        self.current_interaction = interaction
        assert self._scene is not None
        self._scene.scene_data = new_scene_data
        logger.info("Interaction -> %s", interaction)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_stage.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/stage.py tests/metahuman_actor/game_driven/test_stage.py
git commit -m "add GameDrivenStage lifecycle and scene/interaction switching"
```

---

## Task 10: GameDrivenServer — WS protocol

`GameDrivenServer` subclasses `WebSocketServer`. It implements the new inbound protocol in `_handle_inbound` and emits the new outbound frames directly over `ws`. Dialogue text/audio frames continue to flow through the messenger's outbound drain (unchanged). The server holds the stage and validates `npc` against the loaded character.

For `respond`/`trigger`, the server calls `respond_with_hint`/`trigger_with_hint`, then if a `FollowupHint` is returned, sends a `followup_hint` frame.

**Files:**
- Create: `metahuman_actor/game_driven/server.py`
- Test: `tests/metahuman_actor/game_driven/test_server.py`

- [ ] **Step 1: Write the failing test**

The test drives `_handle_inbound`-level logic through a fake websocket that records sent frames and feeds inbound messages. We test the dispatch by calling a single message handler method `_handle_message(msg, ws)` (extracted so it's unit-testable without a live socket).

`tests/metahuman_actor/game_driven/test_server.py`:

```python
"""Tests for GameDrivenServer message dispatch using a fake websocket."""
from __future__ import annotations

import json

import pytest

from metahuman_actor.game_driven.scene import FollowupHint
from metahuman_actor.game_driven.server import GameDrivenServer
from metahuman_actor.game_driven.stage import GameDrivenStage

from .conftest import write_scenario_tree


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, raw: str):
        self.sent.append(json.loads(raw))


@pytest.fixture
def server(local_prompts):
    write_scenario_tree(local_prompts)
    stage = GameDrivenStage(
        llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False
    )
    return GameDrivenServer(stage)


@pytest.mark.asyncio
async def test_list_scenarios_returns_names_and_null_active(server):
    ws = FakeWS()
    await server._handle_message({"type": "list_scenarios"}, ws)
    assert ws.sent[-1]["type"] == "scenarios"
    assert ws.sent[-1]["active"] is None
    assert "tavern" in ws.sent[-1]["names"]


@pytest.mark.asyncio
async def test_respond_before_load_errors(server):
    ws = FakeWS()
    await server._handle_message(
        {"type": "respond", "npc": "zeek", "text": "hi", "world_state": {}}, ws
    )
    assert ws.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_load_scenario_emits_scenario_loaded(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    frame = ws.sent[-1]
    assert frame["type"] == "scenario_loaded"
    assert frame["name"] == "tavern"
    assert frame["scene"] == "scene_1"
    assert frame["interactions"] == {"zeek": "converse"}


@pytest.mark.asyncio
async def test_load_unknown_scenario_errors(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "nope"}, ws)
    assert ws.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_respond_with_followup_emits_hint(server, monkeypatch):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)

    async def fake_respond_with_hint(text, world_state, emotions=None, request_followup_hint=False):
        from digital_actor.dialogue import DialogueLine

        line = DialogueLine(name="Zeek", text="Hi.", line_id="L1")
        hint = FollowupHint(line_id="L1", available=True, suggested_delay_seconds=6.0) if request_followup_hint else None
        return line, hint

    server._stage._scene.respond_with_hint = fake_respond_with_hint  # type: ignore
    await server._handle_message(
        {"type": "respond", "npc": "zeek", "text": "hi", "world_state": {}, "request_followup_hint": True},
        ws,
    )
    hint_frames = [f for f in ws.sent if f["type"] == "followup_hint"]
    assert hint_frames
    assert hint_frames[-1]["line_id"] == "L1"
    assert hint_frames[-1]["available"] is True
    assert hint_frames[-1]["npc"] == "zeek"


@pytest.mark.asyncio
async def test_respond_unknown_npc_errors(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    await server._handle_message(
        {"type": "respond", "npc": "grog", "text": "hi", "world_state": {}}, ws
    )
    assert ws.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_set_scene_emits_scene_changed(server):
    ws = FakeWS()
    await server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    # scene_2 does not exist in this minimal tree -> error
    await server._handle_message({"type": "set_scene", "scene": "scene_2"}, ws)
    assert ws.sent[-1]["type"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metahuman_actor.game_driven.server'`.

- [ ] **Step 3: Write minimal implementation**

`metahuman_actor/game_driven/server.py`:

```python
"""WebSocket server for the game-driven dialogue path.

Implements the request-driven wire protocol (respond/trigger/set_scene/
set_interaction). Dialogue text/audio frames flow through the messenger's
outbound drain (inherited from WebSocketServer); the new control/hint frames
are sent directly over the socket here.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app_logging import get_logger, setup_logging
from digital_actor.messenger import MessengerType, WebSocketServer
from dotenv import load_dotenv
from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

from metahuman_actor.game_driven.scenario import list_game_driven_scenarios
from metahuman_actor.game_driven.stage import GameDrivenStage
from metahuman_actor.settings import settings

logger = get_logger(__name__)
get_logger("digital_actor")


class GameDrivenServer(WebSocketServer):
    def __init__(self, stage: GameDrivenStage, *, port: int = 8788, tick_rate: int = 20) -> None:
        super().__init__(stage, port=port, tick_rate=tick_rate)

    async def _handle_connection(self, ws) -> None:
        self._runtime.resume()
        try:
            await super()._handle_connection(ws)
        finally:
            self._runtime.pause()
            await self._stage.unload_scenario()
            logger.info("client disconnected; scenario unloaded")

    async def _handle_inbound(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"type": "error", "message": "invalid JSON"}))
                continue
            try:
                await self._handle_message(msg, ws)
            except Exception as exc:
                logger.exception("error handling %s", msg.get("type"))
                await ws.send(json.dumps({"type": "error", "message": str(exc)}))

    async def _handle_message(self, msg: dict, ws) -> None:
        msg_type = msg.get("type")
        stage: GameDrivenStage = self._stage

        if msg_type == "list_scenarios":
            active = stage.scenario.name if stage.scenario else None
            await ws.send(json.dumps({
                "type": "scenarios",
                "names": list_game_driven_scenarios(),
                "active": active,
            }))
            return

        if msg_type == "load_scenario":
            name = (msg.get("name") or "").strip()
            if not name:
                await ws.send(json.dumps({"type": "error", "message": "load_scenario: empty name"}))
                return
            await stage.load_scenario(name)
            await ws.send(json.dumps({
                "type": "scenario_loaded",
                "name": name,
                "scene": stage.current_scene,
                "interactions": {stage.actor.actor_id: stage.current_interaction},
            }))
            return

        if msg_type == "unload_scenario":
            await stage.unload_scenario()
            await ws.send(json.dumps({"type": "scenario_unloaded"}))
            return

        # Everything below requires a loaded scenario.
        if stage.scenario is None:
            await ws.send(json.dumps({"type": "error", "message": "no scenario loaded"}))
            return

        if msg_type == "set_scene":
            scene = (msg.get("scene") or "").strip()
            await stage.set_scene(scene)
            await ws.send(json.dumps({
                "type": "scene_changed",
                "scene": stage.current_scene,
                "interactions": {stage.actor.actor_id: stage.current_interaction},
            }))
            return

        if msg_type == "set_interaction":
            npc = (msg.get("npc") or "").strip()
            interaction = (msg.get("interaction") or "").strip()
            await stage.set_interaction(npc, interaction)
            await ws.send(json.dumps({
                "type": "interaction_changed",
                "npc": npc,
                "interaction": stage.current_interaction,
            }))
            return

        if msg_type == "respond":
            npc = (msg.get("npc") or "").strip()
            self._validate_npc(npc)
            text = (msg.get("text") or "").strip()
            if not text:
                await ws.send(json.dumps({"type": "error", "message": "respond: empty text"}))
                return
            world_state = msg.get("world_state") or {}
            request_followup = bool(msg.get("request_followup_hint", False))
            emotions = msg.get("emotions")
            _, hint = await stage._scene.respond_with_hint(
                text, world_state, emotions=emotions, request_followup_hint=request_followup
            )
            await self._maybe_send_hint(ws, npc, hint)
            return

        if msg_type == "trigger":
            npc = (msg.get("npc") or "").strip()
            self._validate_npc(npc)
            name = (msg.get("name") or "").strip()
            info = {str(k): str(v) for k, v in (msg.get("info") or {}).items()}
            world_state = msg.get("world_state") or {}
            request_followup = bool(msg.get("request_followup_hint", False))
            _, hint = await stage._scene.trigger_with_hint(
                name, info, world_state, request_followup_hint=request_followup
            )
            await self._maybe_send_hint(ws, npc, hint)
            return

        await ws.send(json.dumps({"type": "error", "message": f"unknown message type {msg_type!r}"}))

    def _validate_npc(self, npc: str) -> None:
        stage: GameDrivenStage = self._stage
        if stage.actor is None or npc != stage.actor.actor_id:
            raise ValueError(f"unknown npc {npc!r}")

    async def _maybe_send_hint(self, ws, npc: str, hint) -> None:
        if hint is None:
            return
        await ws.send(json.dumps({
            "type": "followup_hint",
            "npc": npc,
            "line_id": hint.line_id,
            "available": hint.available,
            "suggested_delay_seconds": hint.suggested_delay_seconds,
        }))


def main(port: int, llm_model: str, langfuse_local: bool = False) -> None:
    session = langfuse_session(
        prompt_label=settings.digital_actor_server.prompt_label,
        local=langfuse_local,
    )
    with session:
        fetch_all_prompts_from_project()
        GameDrivenServer(
            GameDrivenStage(llm_model, messenger=MessengerType.WEBSOCKET),
            port=port,
        ).run()


if __name__ == "__main__":
    load_dotenv()
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default="cerebras/qwen-3-235b-a22b-instruct-2507")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--langfuse-local", action="store_true")
    args = parser.parse_args()
    main(port=args.port, llm_model=args.llm, langfuse_local=args.langfuse_local)
```

Note on `interactions` map key: the test `test_load_scenario_emits_scenario_loaded` expects `{"zeek": "converse"}`. `actor.actor_id` is `"zeek"` (from persona `id`). That matches. If the persona `id` and the `npc` field the game uses ever differ, revisit — for v1 they're the same.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_server.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/server.py tests/metahuman_actor/game_driven/test_server.py
git commit -m "add GameDrivenServer WS protocol and entry point"
```

---

## Task 11: Migrate one existing scenario to the new layout (smoke fixture)

Create a real game-driven scenario on disk by converting an existing one (e.g. `zeek`) into the new tree, so the server can be launched and smoke-tested manually. This is a content task — no Python.

The new-layout scenarios live under the local prompt root at `scenarios/` — i.e. **`.langfuse_prompts/scenarios/<name>/`** by default (same root the existing scenario prompt files already use). The loader (`resolve_local_langfuse_root() / "scenarios"`) and `get_prompt` both resolve there.

**Files:**
- Create: the tree below under `.langfuse_prompts/scenarios/zeek_gd/`.

- [ ] **Step 1: Create the new-layout scenario tree under `.langfuse_prompts/scenarios/zeek_gd/`**

Create these files (copy lore text from the existing `zeek` scenario's prompt files under `.langfuse_prompts/scenarios/zeek/` where sensible; minimal placeholder text is acceptable for a smoke test):

```
.langfuse_prompts/scenarios/zeek_gd/scenario.json
  {"default_character": "zeek", "default_scene": "scene_1", "default_interaction": "converse"}

.langfuse_prompts/scenarios/zeek_gd/back_story.txt                    (copy from .langfuse_prompts/scenarios/zeek/back_story.txt)
.langfuse_prompts/scenarios/zeek_gd/personas/zeek.json                (copy metahuman_actor/scenarios/zeek/persona.json; keep voice config)
.langfuse_prompts/scenarios/zeek_gd/scene_1/scene_description.txt     (copy from zeek/scene1/scene_description.txt)
.langfuse_prompts/scenarios/zeek_gd/scene_1/characters/zeek/character_back_story.txt  (copy from zeek/scene1/character_back_story.txt)
.langfuse_prompts/scenarios/zeek_gd/scene_1/characters/zeek/converse/steer_back_instructions.txt  (copy from zeek/scene1/steer_back_instructions.txt)
.langfuse_prompts/scenarios/zeek_gd/scene_1/characters/zeek/converse/opening_speech.txt           (copy from zeek/scene1/opening_speech.txt)
.langfuse_prompts/scenarios/zeek_gd/scene_1/characters/zeek/converse/triggers/greet/prompt.txt
  The player has approached you. Greet them in character.
.langfuse_prompts/scenarios/zeek_gd/scene_1/characters/zeek/converse/triggers/goodbye/prompt.txt
  The player is leaving. Give a fitting parting line in character.
```

- [ ] **Step 2: Verify the loader reads it (local mode)**

Run:
```bash
uv run python -c "
from langfuse_utils import langfuse_session
from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData
with langfuse_session(local=True):
    s = GameDrivenScenario.load('zeek_gd')
    d = GameDrivenSceneData.load(s, scene=s.default_scene, character=s.default_character, interaction=s.default_interaction)
    print(s.name, list(d.triggers))
"
```
Expected: prints `zeek_gd ['goodbye', 'greet']` (sorted).

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "add zeek_gd scenario in new game-driven layout for smoke testing"
```

---

## Task 12: Full test sweep + manual smoke

- [ ] **Step 1: Run the whole game_driven test suite**

Run: `uv run pytest tests/metahuman_actor/game_driven/ -v`
Expected: all pass.

- [ ] **Step 2: Run the full existing suite to confirm nothing regressed**

Run: `uv run pytest -q`
Expected: all pass (the authoritative path is untouched).

- [ ] **Step 3: Manual smoke — launch the new server**

Run (in one terminal): `uv run python -m metahuman_actor.game_driven.server --langfuse-local`
Expected: logs "Actor server listening on ws://localhost:8788".

- [ ] **Step 4: Manual smoke — drive it with a tiny client**

Run (in another terminal):
```bash
uv run python -c "
import asyncio, json, websockets
async def go():
    async with websockets.connect('ws://localhost:8788') as ws:
        await ws.send(json.dumps({'type':'load_scenario','name':'zeek_gd'}))
        print(await ws.recv())
        await ws.send(json.dumps({'type':'trigger','npc':'zeek','name':'greet','info':{},'world_state':{'time_of_day':'night'},'request_followup_hint':True}))
        for _ in range(6):
            print(await ws.recv())
asyncio.run(go())
"
```
Expected: a `scenario_loaded` frame, then a `text` frame with a greeting line, `audio_done`, and a `followup_hint` frame.

- [ ] **Step 5: Final commit (if any fixups were needed)**

```bash
git add -A
git commit -m "game-driven server: test sweep and smoke fixups"
```

---

## Notes for the implementer

- **Do not modify anything under `packages/digital_actor/`.** If you find yourself wanting to, stop and reconsider — the new path composes library primitives, it doesn't change them.
- **`DialogueLine` constructor**: check `digital_actor/dialogue.py` for the exact required fields if you construct one directly in a test (the server test does — `DialogueLine(name=..., text=..., line_id=...)`). Adjust kwargs to match the real signature.
- **`history.add_message(role, text)` returns a `DialogueLine`** — use its `.line_id`.
- **`history.last_actor_line()`, `history.summary_idx`, `history.summary`, `history.to_string(...)`** are used by the followup prompt builder; they exist on `DialogueHistory` (the authoritative `MetaHumanSingleActorScene` uses the same). Confirm signatures in `packages/digital_actor/digital_actor/history.py` and match them.
- **`pytest-asyncio` mode**: if `@pytest.mark.asyncio` causes "async def not natively supported", check `pyproject.toml`/`pytest.ini` for `asyncio_mode = auto` and drop the marker, or add it — match the existing async tests under `tests/metahuman_actor/`.
- **`set_stage`/`stage_context`**: the scene unit tests install a `StubStage` via `set_stage`. The real flow uses `GameDrivenStage` which calls `set_stage(self)` in `BaseStage.__init__`. Ensure the scene reads `stage_context` lazily (inside methods), not at construction.
```
