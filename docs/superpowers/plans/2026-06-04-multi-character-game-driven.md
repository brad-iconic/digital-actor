# Multi-Character Game-Driven Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the game-driven server load multiple characters per scenario and route each `respond`/`trigger`/`set_interaction` to the addressed character by `npc`, fixing the `unknown npc 'Dorn'` error when multiple NPCs share a scenario.

**Architecture:** `GameDrivenStage` stops holding one actor/scene and instead holds a dict of per-character holders (`LoadedCharacter`: actor + scene + tts_client + current_interaction) plus an `_active_character` pointer. `stage_context.scene_data` and `.tts_client` return the active character's values; each request sets the active pointer to the addressed character before generating. Safe because the WS loop is sequential and each scene serializes its own generation. `scenario.json` gains a `characters` list (single-character scenarios still work via normalization).

**Tech Stack:** Python 3.12+, asyncio, `websockets`, pytest + pytest-asyncio. Package manager: `uv`. Run tests with `uv run pytest <path> -v` from repo root `D:\Iconic\Research\digital-actor`.

---

## Spec

Read `docs/superpowers/specs/2026-06-04-multi-character-game-driven-design.md` for full rationale.

## Background the engineer needs

The game-driven path lives under `metahuman_actor/game_driven/`. Read these before starting:

- `metahuman_actor/game_driven/scenario.py` — `GameDrivenScenario` (frozen dataclass) with `name`, `default_character`, `default_scene`, `default_interaction`; classmethod `load(name)` reading `scenario.json`; path helpers `persona_path(character)`, `scene_dir(scene)`, `character_dir(scene, character)`, `interaction_dir(scene, character, interaction)`, `has_scene(scene)`, `has_interaction(scene, character, interaction)`; `prompts_root` (== `f"scenarios/{name}"`), `data_root`. Scenarios are rooted via `resolve_local_langfuse_root() / "scenarios"`.
- `metahuman_actor/game_driven/scene_data.py` — `GameDrivenSceneData.load(scenario, *, scene, character, interaction)`. Unchanged by this work.
- `metahuman_actor/game_driven/scene.py` — `GameDrivenScene(actor, scene_data, suggested_delay_seconds=6.0)`. Has `.scene_data` (settable), `async respond_with_hint(text, world_state, emotions=None, request_followup_hint=False) -> (DialogueLine, FollowupHint|None)`, `async trigger_with_hint(name, info, world_state, request_followup_hint=False) -> (DialogueLine, FollowupHint|None)`, `async await_idle()`, `reset()`. Unchanged by this work. `FollowupHint` is defined here.
- `metahuman_actor/game_driven/stage.py` — `GameDrivenStage(SingleSceneStage)` — the file this work mostly rewrites. Currently single-actor: `self.actor`, single `_scene` (via `register_scene`), `current_scene`, `current_interaction`, `scene_data`/`scenario` properties, `load_scenario`/`unload_scenario`/`set_scene`/`set_interaction`, `_build_scene_data`. Error classes `UnknownSceneError`, `UnknownInteractionError`, `UnknownNpcError`.
- `metahuman_actor/game_driven/server.py` — `GameDrivenServer._handle_message`. Currently reaches into `self._stage._scene.respond_with_hint(...)` and validates npc via `self._validate_npc(npc)` (which raises if `npc != stage.actor.actor_id`). This work moves routing into the stage and removes `_validate_npc`.
- `metahuman_actor/actor.py` — `MetaHumanDigitalActor(persona: dict)`; persona has `id`, `display_name`, optional `voice`. `.actor_id` is the persona `id`. `.name` is `display_name`. `.history` is the conversation.

Key facts:
- `MetaHumanDigitalActor.get_next_line_prompt_info` / `get_summary_prompt_info` read `stage_context.scene_data.*` and the actor's `run_tts` reads `stage_context.tts_client`. `stage_context` is a module-global proxy to the one registered stage (`set_stage` in `BaseStage.__init__`). So whatever the stage's `scene_data`/`tts_client` properties return is what the *currently generating* actor sees. This is why the stage must point those at the active character.
- `SingleSceneStage.await_idle()` calls `self._scene.await_idle()` guarded by `self._scene is not None`. With multiple scenes we override `await_idle`/`reset`/`scene_data` and do NOT use the single `_scene` slot.
- `tts_lib.get_tts_client(provider, voice_id=, model_id=)` builds a TTS client (or we pass `None`).
- Unreal sends `npc` as an `FName` which may be capitalized (`"Dorn"` for `dorn`) — match casefold.

### Test infrastructure (reuse)

`tests/metahuman_actor/game_driven/conftest.py` provides:
- `local_prompts` fixture — sets `LOCAL_LANGFUSE_PATH=tmp_path`, seeds shared `dialogue/common/query/summary` templates, opens `langfuse_session(local=True)`, yields `tmp_path`.
- `write_scenario_tree(langfuse_root, *, name="tavern", scenes=("scene_1",), interactions=("converse",), with_triggers=True)` — writes a single-character (`zeek`) scenario tree. **Task 1 extends this to support multiple characters.**

Test files use:
- `@pytest.fixture(autouse=True) _dummy_llm_key` (sets `CEREBRAS_API_KEY`) — present in `test_stage.py` and `test_server.py`.
- `from .conftest import write_scenario_tree`.
- `pytest.mark.asyncio` per async test (asyncio_mode is configured; check existing tests — they use `@pytest.mark.asyncio`).
- `GameDrivenStage(llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False)`.

**Avoid real LLM calls in tests**: where a test needs generation, stub the scene's `respond_with_hint`/`trigger_with_hint` with an AsyncMock, OR stub `stage_context` LLM via a StubStage (see test_scene.py's `StubStage` pattern). For stage-level routing tests, the cleanest seam is to assert on *which character's history* received the player line and *which scene_data was active*, using a stub that captures the compiled prompt — but simplest is to monkeypatch each character's `scene.respond_with_hint` to a recording AsyncMock and assert the right one was called. Use your judgment; do NOT let a test hit the network.

---

## File structure

- Modify: `metahuman_actor/game_driven/scenario.py` — add `characters` property + normalization.
- Modify (major): `metahuman_actor/game_driven/stage.py` — `LoadedCharacter`, per-character dict, active pointer, routing methods, multi-character lifecycle.
- Modify: `metahuman_actor/game_driven/server.py` — delegate routing to stage; remove `_validate_npc`; full interactions maps; echo resolved npc.
- Modify: `tests/metahuman_actor/game_driven/conftest.py` — multi-character `write_scenario_tree`.
- Modify: `tests/metahuman_actor/game_driven/test_scenario.py`, `test_stage.py`, `test_server.py` — add multi-character tests.

`GameDrivenScene`, `GameDrivenSceneData`, `MetaHumanDigitalActor`, and `packages/digital_actor/` are NOT modified.

---

## Task 1: Multi-character test fixture (`write_scenario_tree`)

Extend the fixture so tests can scaffold multi-character scenarios. Keep the single-character default so existing tests are unaffected.

**Files:**
- Modify: `tests/metahuman_actor/game_driven/conftest.py`

- [ ] **Step 1: Replace `write_scenario_tree` with a multi-character-capable version**

Replace the existing `write_scenario_tree` function in `conftest.py` with this. It adds a `characters` parameter (a list of `(id, display_name)` tuples) defaulting to the existing single `zeek`/`Zeek`, writes one persona per character, a `characters` list in `scenario.json`, and per-character scene/interaction folders. Existing call sites (`write_scenario_tree(local_prompts)`, `write_scenario_tree(local_prompts, scenes=..., interactions=...)`) keep working because the default is the single zeek character.

```python
def write_scenario_tree(
    langfuse_root,
    *,
    name="tavern",
    scenes=("scene_1",),
    interactions=("converse",),
    with_triggers=True,
    characters=(("zeek", "Zeek"),),
):
    """Create a game-driven scenario tree under <langfuse_root>/scenarios/<name>.

    ``characters`` is a list of (id, display_name) tuples. Defaults to a single
    zeek character so existing single-character tests are unaffected. Writes one
    persona per character, a ``characters`` list in scenario.json, and per-scene
    per-character per-interaction folders.

    The loader resolves scenarios under the local prompt root at scenarios/, and
    get_prompt resolves names like "scenarios/<name>/scene_1/..." to these files.

    Returns the scenario directory path.
    """
    scen = langfuse_root / "scenarios" / name
    (scen / "personas").mkdir(parents=True)
    for cid, display in characters:
        (scen / "personas" / f"{cid}.json").write_text(
            json.dumps({"id": cid, "display_name": display}), encoding="utf-8"
        )
    (scen / "scenario.json").write_text(
        json.dumps(
            {
                "characters": [cid for cid, _ in characters],
                "default_character": characters[0][0],
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
        for cid, display in characters:
            char = scen / scene / "characters" / cid
            char.mkdir(parents=True, exist_ok=True)
            (char / "character_back_story.txt").write_text(
                f"{display} is wary.", encoding="utf-8"
            )
            for interaction in interactions:
                inter = char / interaction
                inter.mkdir(parents=True, exist_ok=True)
                (inter / "steer_back_instructions.txt").write_text(
                    f"{interaction} steer.", encoding="utf-8"
                )
                (inter / "opening_speech.txt").write_text(
                    f"[{display}]: Well met.", encoding="utf-8"
                )
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
```

- [ ] **Step 2: Verify existing tests still pass (the fixture change must be back-compatible)**

Run: `uv run pytest tests/metahuman_actor/game_driven/ -q`
Expected: all currently-passing tests still pass (50 passed). The default single-zeek character keeps existing tests working. (Note: `scenario.json` now also has a `characters` list even for single-character trees — that's fine; Task 2 makes the loader read it, and until then the loader ignores the extra key.)

- [ ] **Step 3: Commit**

```bash
git add tests/metahuman_actor/game_driven/conftest.py
git commit -m "test fixture: write_scenario_tree supports multiple characters"
```

---

## Task 2: `GameDrivenScenario.characters` property + normalization

Teach the loader to read the `characters` list, with single-character back-compat.

**Files:**
- Modify: `metahuman_actor/game_driven/scenario.py`
- Test: `tests/metahuman_actor/game_driven/test_scenario.py`

- [ ] **Step 1: Write the failing tests (append to test_scenario.py)**

The existing test file has a `scenarios_root` fixture (sets `LOCAL_LANGFUSE_PATH`, makes `tmp_path/scenarios`) and a `_make_tree(scenarios_root, name="tavern")` helper writing a single-character tree with `default_character` only (no `characters` list). Read the file to confirm those helpers; reuse them. Add a small helper to write a multi-character `scenario.json`.

```python
def test_characters_defaults_to_single_when_no_list(scenarios_root):
    # _make_tree writes scenario.json with default_character only, no characters list.
    _make_tree(scenarios_root)
    s = GameDrivenScenario.load("tavern")
    assert s.characters == ["zeek"]


def test_characters_reads_explicit_list(scenarios_root, monkeypatch):
    import json
    _make_tree(scenarios_root)
    # Overwrite scenario.json with an explicit multi-character list.
    (scenarios_root / "tavern" / "scenario.json").write_text(
        json.dumps({
            "characters": ["dorn", "barkeep"],
            "default_character": "dorn",
            "default_scene": "scene_1",
            "default_interaction": "converse",
        }),
        encoding="utf-8",
    )
    s = GameDrivenScenario.load("tavern")
    assert s.characters == ["dorn", "barkeep"]
    assert s.default_character == "dorn"


def test_default_character_defaults_to_first_when_absent(scenarios_root):
    import json
    _make_tree(scenarios_root)
    (scenarios_root / "tavern" / "scenario.json").write_text(
        json.dumps({
            "characters": ["dorn", "barkeep"],
            "default_scene": "scene_1",
            "default_interaction": "converse",
        }),
        encoding="utf-8",
    )
    s = GameDrivenScenario.load("tavern")
    assert s.characters == ["dorn", "barkeep"]
    assert s.default_character == "dorn"  # defaults to characters[0]
```

NOTE: confirm `_make_tree`'s exact name/signature in the file. If it writes a `characters` list already (it shouldn't, it predates this work), adjust `test_characters_defaults_to_single_when_no_list` to write a no-list scenario.json explicitly. The goal of that test: a scenario.json with only `default_character` (no `characters`) normalizes to `[default_character]`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scenario.py -k "characters or default_character_defaults" -v`
Expected: FAIL — `GameDrivenScenario` has no `characters` attribute.

- [ ] **Step 3: Implement in scenario.py**

`GameDrivenScenario` is a frozen dataclass. Add a `characters: list[str]` field and normalize in `load`. Change the dataclass and `load`:

Add `characters: list[str]` to the dataclass fields (after `default_interaction`):

```python
@dataclass(frozen=True)
class GameDrivenScenario:
    name: str
    default_character: str
    default_scene: str
    default_interaction: str
    characters: list[str]
```

(`list` default in a frozen dataclass is fine as a normal required field since `load` always provides it. Do NOT give it a mutable default; `load` constructs it.)

Update `load` to normalize:

```python
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
            # No list: single-character scenario keyed on default_character.
            characters = [default_character]
        return cls(
            name=name,
            default_character=default_character,
            default_scene=config["default_scene"],
            default_interaction=config["default_interaction"],
            characters=list(characters),
        )
```

(Preserve the existing docstring if one is present; the above includes it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_scenario.py -v`
Expected: PASS — the 3 new tests plus all existing scenario tests. (Existing tests that construct `GameDrivenScenario(...)` directly, if any, must be updated to pass `characters=[...]`; grep the test file for direct construction. If found, fix those constructions to include `characters=["zeek"]` or similar — note it in your report.)

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/scenario.py tests/metahuman_actor/game_driven/test_scenario.py
git commit -m "scenario: add characters list with single-character normalization"
```

---

## Task 3: `LoadedCharacter` + multi-character load/unload in the stage

Rewrite `GameDrivenStage` to hold a dict of per-character holders and an active pointer. This task does load/unload + the `scene_data`/`tts_client`/`scenario`/`interactions_map` properties + `await_idle`/`reset`. Routing (respond/trigger) and set_scene/set_interaction come in Tasks 4 and 5.

**Files:**
- Modify: `metahuman_actor/game_driven/stage.py`
- Test: `tests/metahuman_actor/game_driven/test_stage.py`

- [ ] **Step 1: Write the failing tests (add to test_stage.py)**

Add a multi-character fixture and load tests. Reuse the existing `_dummy_llm_key` autouse fixture and `local_prompts`.

```python
@pytest.fixture
def multi_stage(local_prompts):
    # Two characters, two scenes, two interactions.
    write_scenario_tree(
        local_prompts,
        scenes=("scene_1", "scene_2"),
        interactions=("converse", "barter"),
        characters=(("dorn", "Dorn"), ("barkeep", "Barkeep")),
    )
    return GameDrivenStage(llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False)


@pytest.mark.asyncio
async def test_load_multi_populates_all_characters(multi_stage):
    await multi_stage.load_scenario("tavern")
    assert multi_stage.scenario is not None
    assert set(multi_stage.character_ids()) == {"dorn", "barkeep"}
    # Active pointer defaults to the primary (default_character = first = dorn).
    assert multi_stage.active_character == "dorn"
    # Each character has its own scene_data with its own character_back_story.
    assert "Dorn is wary." == multi_stage.scene_data_for("dorn").character_back_story
    assert "Barkeep is wary." == multi_stage.scene_data_for("barkeep").character_back_story


@pytest.mark.asyncio
async def test_interactions_map_has_all_characters(multi_stage):
    await multi_stage.load_scenario("tavern")
    assert multi_stage.interactions_map() == {"dorn": "converse", "barkeep": "converse"}


@pytest.mark.asyncio
async def test_unload_clears_all_characters(multi_stage):
    await multi_stage.load_scenario("tavern")
    await multi_stage.unload_scenario()
    assert multi_stage.scenario is None
    assert multi_stage.character_ids() == []
    assert multi_stage.active_character is None
    assert multi_stage.scene_data is None


@pytest.mark.asyncio
async def test_active_scene_data_follows_active_pointer(multi_stage):
    await multi_stage.load_scenario("tavern")
    multi_stage._active_character = "barkeep"
    assert multi_stage.scene_data.character_back_story == "Barkeep is wary."
    multi_stage._active_character = "dorn"
    assert multi_stage.scene_data.character_back_story == "Dorn is wary."
```

These reference helper methods this task adds: `character_ids()`, `active_character` (property reading `_active_character`), `scene_data_for(cid)`, `interactions_map()`. Add them.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_stage.py -k "multi or interactions_map or active_scene" -v`
Expected: FAIL — methods/behavior not present.

- [ ] **Step 3: Rewrite the stage's holder + load/unload + properties**

Rewrite `metahuman_actor/game_driven/stage.py`. Keep the three error classes. Replace the single-actor fields and load/unload with the multi-character version below. (Tasks 4 and 5 will add `respond`/`trigger` and rewrite `set_scene`/`set_interaction`; for now keep the OLD `set_scene`/`set_interaction`/`on_user_input` bodies compiling — you'll replace them next. The simplest path: implement everything in this task's code block EXCEPT routing, and leave `set_scene`/`set_interaction` as written here already multi-character so you don't churn twice. This plan's Task 5 assumes set_scene/set_interaction are implemented HERE; Task 4 adds respond/trigger. So implement set_scene/set_interaction now too.)

Full new `stage.py`:

```python
"""GameDrivenStage — owns scenario lifecycle for the request-driven server.

Holds one LoadedCharacter per scenario character (each with its own actor,
history, scene, tts client, and current interaction) plus an active-character
pointer. stage_context.scene_data / .tts_client return the ACTIVE character's
values; each request sets the active pointer to the addressed character before
generating. Safe because the WS loop is sequential and each scene serializes its
own generation — only one character generates at a time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app_logging import get_logger
from digital_actor.game_events import GameEventBase
from digital_actor.messenger import Messenger, MessengerType
from digital_actor.stage import SingleSceneStage
from tts_lib import get_tts_client

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene import FollowupHint, GameDrivenScene
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData

logger = get_logger(__name__)


class UnknownSceneError(ValueError):
    pass


class UnknownInteractionError(ValueError):
    pass


class UnknownNpcError(ValueError):
    pass


@dataclass
class LoadedCharacter:
    """Per-character runtime state held by the stage."""

    actor: MetaHumanDigitalActor
    scene: GameDrivenScene
    tts_client: object | None
    current_interaction: str


class GameDrivenStage(SingleSceneStage):
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
        self._characters: dict[str, LoadedCharacter] = {}
        self._active_character: str | None = None
        self._primary: str | None = None
        self.current_scene: str | None = None
        self._tts_enabled = tts_enabled
        logger.info("GameDrivenStage ready (no scenario loaded)")

    # --- introspection ---

    @property
    def scenario(self) -> GameDrivenScenario | None:
        return self._scenario

    @property
    def active_character(self) -> str | None:
        return self._active_character

    def character_ids(self) -> list[str]:
        return list(self._characters)

    def interactions_map(self) -> dict[str, str]:
        return {cid: lc.current_interaction for cid, lc in self._characters.items()}

    def scene_data_for(self, cid: str) -> GameDrivenSceneData | None:
        lc = self._characters.get(cid)
        return lc.scene.scene_data if lc is not None else None

    @property
    def scene_data(self) -> GameDrivenSceneData | None:
        if self._active_character is None:
            return None
        lc = self._characters.get(self._active_character)
        return lc.scene.scene_data if lc is not None else None

    @property
    def tts_client(self) -> object | None:
        if self._active_character is None:
            return None
        lc = self._characters.get(self._active_character)
        return lc.tts_client if lc is not None else None

    # --- BaseStage hooks ---

    async def on_game_event(self, event: GameEventBase) -> None:
        return

    async def on_user_input(self, message: str) -> None:
        # Back-compat single-input path: drive the active (or primary) character.
        cid = self._active_character or self._primary
        if cid is not None:
            await self._characters[cid].scene.on_user_input(message)

    async def await_idle(self) -> None:
        for lc in self._characters.values():
            await lc.scene.await_idle()

    def reset(self) -> None:
        for lc in self._characters.values():
            lc.scene.reset()

    # --- name resolution ---

    def _resolve_npc(self, npc: str | None) -> str:
        if not npc:
            if self._primary is None:
                raise UnknownNpcError("no scenario loaded")
            return self._primary
        for cid in self._characters:
            if cid.casefold() == npc.casefold():
                return cid
        raise UnknownNpcError(npc)

    # --- lifecycle ---

    def _build_character(
        self, scenario: GameDrivenScenario, cid: str, scene: str, interaction: str
    ) -> LoadedCharacter:
        persona_path = scenario.persona_path(cid)
        with open(persona_path, encoding="utf-8") as f:
            persona = json.load(f)
        voice = (persona.get("voice") or {}) if self._tts_enabled else {}
        actor = MetaHumanDigitalActor(persona)
        scene_data = GameDrivenSceneData.load(
            scenario, scene=scene, character=cid, interaction=interaction
        )
        tts = (
            get_tts_client(
                voice.get("provider"),
                voice_id=voice.get("voice_id"),
                model_id=voice.get("model_id"),
            )
            if voice.get("provider")
            else None
        )
        return LoadedCharacter(
            actor=actor,
            scene=GameDrivenScene(actor=actor, scene_data=scene_data),
            tts_client=tts,
            current_interaction=interaction,
        )

    async def load_scenario(self, name: str) -> None:
        new_scenario = GameDrivenScenario.load(name)
        scene = new_scenario.default_scene
        interaction = new_scenario.default_interaction
        # Build every character fully before mutating any state (atomic load).
        new_characters: dict[str, LoadedCharacter] = {}
        for cid in new_scenario.characters:
            new_characters[cid] = self._build_character(
                new_scenario, cid, scene, interaction
            )

        if self._scenario is not None:
            await self.await_idle()
        self.reset()
        self._scenario = new_scenario
        self._characters = new_characters
        self._primary = new_scenario.default_character
        self._active_character = new_scenario.default_character
        self.current_scene = scene
        logger.info(
            "Loaded game-driven scenario=%s characters=%s",
            new_scenario.name,
            list(new_characters),
        )

    async def unload_scenario(self) -> None:
        if self._scenario is None:
            return
        await self.await_idle()
        self.reset()
        self._characters = {}
        self._active_character = None
        self._primary = None
        self._scenario = None
        self.current_scene = None
        logger.info("Unloaded game-driven scenario")

    # --- scene / interaction switching ---

    async def set_scene(self, scene: str) -> None:
        if self._scenario is None:
            raise UnknownSceneError("no scenario loaded")
        if not self._scenario.has_scene(scene):
            raise UnknownSceneError(scene)
        interaction = self._scenario.default_interaction
        # Build new scene_data for EVERY character before swapping (atomic).
        new_data: dict[str, GameDrivenSceneData] = {}
        for cid in self._characters:
            if not self._scenario.has_interaction(scene, cid, interaction):
                raise UnknownInteractionError(f"{scene}/{cid}/{interaction}")
            new_data[cid] = GameDrivenSceneData.load(
                self._scenario, scene=scene, character=cid, interaction=interaction
            )
        await self.await_idle()
        for cid, lc in self._characters.items():
            lc.scene.scene_data = new_data[cid]
            lc.current_interaction = interaction
        self.current_scene = scene
        logger.info("Scene -> %s (all interactions reset to %s)", scene, interaction)

    async def set_interaction(self, npc: str, interaction: str) -> None:
        if self._scenario is None:
            raise UnknownNpcError("no scenario loaded")
        cid = self._resolve_npc(npc)
        if not self._scenario.has_interaction(self.current_scene, cid, interaction):
            raise UnknownInteractionError(interaction)
        new_scene_data = GameDrivenSceneData.load(
            self._scenario, scene=self.current_scene, character=cid, interaction=interaction
        )
        await self._characters[cid].scene.await_idle()
        self._characters[cid].scene.scene_data = new_scene_data
        self._characters[cid].current_interaction = interaction
        logger.info("Interaction[%s] -> %s", cid, interaction)

    # --- routing (Task 4 adds respond/trigger) ---
```

Leave the `--- routing ---` comment as the insertion point for Task 4.

Note: `GameDrivenStage` no longer calls `register_scene` (it doesn't use the base `_scene` slot). It overrides `await_idle`, `reset`, `scene_data`. The base `SingleSceneStage._scene` stays `None`; that's fine because we override everything that would touch it. `set_stage(self)` still runs in `BaseStage.__init__`, so `stage_context` resolves to this stage.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_stage.py -v`
Expected: the new multi-character load/unload/interactions/active-pointer tests PASS. **Existing single-character `test_stage.py` tests** may reference `stage.actor`, `stage.current_interaction`, or `stage.scene_data` — these changed. Update those existing tests:
- `stage.actor` → there's no single `.actor` now. Replace assertions like `stage.actor.name == "Zeek"` with `stage.scene_data.character_back_story`-style checks, or `stage._characters[stage._primary].actor.name`. Prefer asserting via `character_ids()` / `interactions_map()` / `scene_data`.
- `stage.current_interaction` → use `stage.interactions_map()[<cid>]` or add back a convenience (don't; prefer the map).
- Keep the single-character tests meaningful: a one-character `write_scenario_tree(local_prompts, scenes=..., interactions=...)` now yields `characters == ["zeek"]`, `active_character == "zeek"`.
Report exactly which existing tests you updated and how.

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/stage.py tests/metahuman_actor/game_driven/test_stage.py
git commit -m "stage: multi-character holders, active pointer, load/scene/interaction"
```

---

## Task 4: Routing methods on the stage (`respond` / `trigger`)

Add the `respond`/`trigger` routing methods that set the active pointer and drive the addressed character's scene, returning the resolved id + hint.

**Files:**
- Modify: `metahuman_actor/game_driven/stage.py`
- Test: `tests/metahuman_actor/game_driven/test_stage.py`

- [ ] **Step 1: Write the failing tests (add to test_stage.py)**

These stub each character's `scene.respond_with_hint`/`trigger_with_hint` with recording AsyncMocks so no LLM runs, and assert the right character was driven and the active pointer was set.

```python
@pytest.mark.asyncio
async def test_respond_routes_to_named_character(multi_stage):
    from unittest.mock import AsyncMock
    from digital_actor.dialogue import DialogueLine
    await multi_stage.load_scenario("tavern")

    dorn_line = DialogueLine(name="Dorn", text="Arr.", line_id="D1")
    multi_stage._characters["dorn"].scene.respond_with_hint = AsyncMock(
        return_value=(dorn_line, None)
    )
    multi_stage._characters["barkeep"].scene.respond_with_hint = AsyncMock(
        return_value=(DialogueLine(name="Barkeep", text="Aye.", line_id="B1"), None)
    )

    resolved, hint = await multi_stage.respond("dorn", "hi", world_state={})
    assert resolved == "dorn"
    multi_stage._characters["dorn"].scene.respond_with_hint.assert_awaited_once()
    multi_stage._characters["barkeep"].scene.respond_with_hint.assert_not_awaited()
    assert multi_stage.active_character == "dorn"


@pytest.mark.asyncio
async def test_respond_casefold_resolves(multi_stage):
    from unittest.mock import AsyncMock
    from digital_actor.dialogue import DialogueLine
    await multi_stage.load_scenario("tavern")
    multi_stage._characters["dorn"].scene.respond_with_hint = AsyncMock(
        return_value=(DialogueLine(name="Dorn", text="Arr.", line_id="D1"), None)
    )
    # Unreal sends "Dorn" (capitalized FName) for character id "dorn".
    resolved, _ = await multi_stage.respond("Dorn", "hi", world_state={})
    assert resolved == "dorn"
    multi_stage._characters["dorn"].scene.respond_with_hint.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_unknown_npc_raises(multi_stage):
    from metahuman_actor.game_driven.stage import UnknownNpcError
    await multi_stage.load_scenario("tavern")
    with pytest.raises(UnknownNpcError):
        await multi_stage.respond("nobody", "hi", world_state={})


@pytest.mark.asyncio
async def test_respond_omitted_npc_uses_primary(multi_stage):
    from unittest.mock import AsyncMock
    from digital_actor.dialogue import DialogueLine
    await multi_stage.load_scenario("tavern")
    multi_stage._characters["dorn"].scene.respond_with_hint = AsyncMock(
        return_value=(DialogueLine(name="Dorn", text="Arr.", line_id="D1"), None)
    )
    resolved, _ = await multi_stage.respond(None, "hi", world_state={})
    assert resolved == "dorn"  # primary = default_character = first = dorn


@pytest.mark.asyncio
async def test_trigger_routes_to_named_character(multi_stage):
    from unittest.mock import AsyncMock
    from digital_actor.dialogue import DialogueLine
    await multi_stage.load_scenario("tavern")
    multi_stage._characters["barkeep"].scene.trigger_with_hint = AsyncMock(
        return_value=(DialogueLine(name="Barkeep", text="Aye.", line_id="B1"), None)
    )
    resolved, hint = await multi_stage.trigger("barkeep", "greet", info={}, world_state={})
    assert resolved == "barkeep"
    multi_stage._characters["barkeep"].scene.trigger_with_hint.assert_awaited_once()
    assert multi_stage.active_character == "barkeep"


@pytest.mark.asyncio
async def test_respond_history_isolated_per_character(multi_stage):
    # No stubbing of history: drive via the real scene but stub only the LLM by
    # making each scene's respond_with_hint record into that actor's history.
    from unittest.mock import AsyncMock
    from digital_actor.dialogue import DialogueLine

    await multi_stage.load_scenario("tavern")

    async def make_recorder(cid):
        async def _rwh(text, world_state, emotions=None, request_followup_hint=False):
            multi_stage._characters[cid].actor.history.add_message("Player", text)
            return DialogueLine(name=cid, text="ok", line_id=cid), None
        return _rwh

    multi_stage._characters["dorn"].scene.respond_with_hint = await make_recorder("dorn")
    multi_stage._characters["barkeep"].scene.respond_with_hint = await make_recorder("barkeep")

    await multi_stage.respond("dorn", "to dorn", world_state={})
    await multi_stage.respond("barkeep", "to barkeep", world_state={})

    dorn_texts = [m.text for m in multi_stage._characters["dorn"].actor.history.messages]
    barkeep_texts = [m.text for m in multi_stage._characters["barkeep"].actor.history.messages]
    assert "to dorn" in dorn_texts and "to barkeep" not in dorn_texts
    assert "to barkeep" in barkeep_texts and "to dorn" not in barkeep_texts
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_stage.py -k "routes or casefold or omitted or history_isolated or unknown_npc" -v`
Expected: FAIL — `respond`/`trigger` methods not present on the stage.

- [ ] **Step 3: Implement the routing methods (append to stage.py, after the `--- routing ---` comment)**

```python
    async def respond(
        self,
        npc: str | None,
        text: str,
        world_state: dict | None,
        emotions: list[str] | None = None,
        request_followup_hint: bool = False,
    ) -> tuple[str, "FollowupHint | None"]:
        cid = self._resolve_npc(npc)
        self._active_character = cid
        _, hint = await self._characters[cid].scene.respond_with_hint(
            text,
            world_state,
            emotions=emotions,
            request_followup_hint=request_followup_hint,
        )
        return cid, hint

    async def trigger(
        self,
        npc: str | None,
        name: str,
        info: dict[str, str],
        world_state: dict | None,
        request_followup_hint: bool = False,
    ) -> tuple[str, "FollowupHint | None"]:
        cid = self._resolve_npc(npc)
        self._active_character = cid
        _, hint = await self._characters[cid].scene.trigger_with_hint(
            name,
            info,
            world_state,
            request_followup_hint=request_followup_hint,
        )
        return cid, hint
```

(`FollowupHint` is already imported at the top of stage.py per Task 3's import block.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_stage.py -v`
Expected: all stage tests pass (load + routing).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/stage.py tests/metahuman_actor/game_driven/test_stage.py
git commit -m "stage: add respond/trigger routing with active-pointer + casefold resolve"
```

---

## Task 5: Server delegates routing to the stage

Rewrite the server's `respond`/`trigger`/`set_interaction` arms to call the stage's routing methods, drop `_validate_npc`, and emit full interactions maps + resolved npc.

**Files:**
- Modify: `metahuman_actor/game_driven/server.py`
- Test: `tests/metahuman_actor/game_driven/test_server.py`

- [ ] **Step 1: Write the failing tests (add to test_server.py)**

Read the existing `test_server.py` for its `FakeWS`, `_dummy_llm_key`, `server` fixture, and `write_scenario_tree` usage. Add a multi-character server fixture and tests. The key test reproduces the reported bug.

```python
@pytest.fixture
def multi_server(local_prompts):
    write_scenario_tree(
        local_prompts,
        characters=(("dorn", "Dorn"), ("barkeep", "Barkeep")),
    )
    from metahuman_actor.game_driven.stage import GameDrivenStage
    stage = GameDrivenStage(
        llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", tts_enabled=False
    )
    return GameDrivenServer(stage)


@pytest.mark.asyncio
async def test_scenario_loaded_lists_all_characters(multi_server):
    ws = FakeWS()
    await multi_server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    frame = ws.sent[-1]
    assert frame["type"] == "scenario_loaded"
    assert frame["interactions"] == {"dorn": "converse", "barkeep": "converse"}


@pytest.mark.asyncio
async def test_trigger_for_second_character_works(multi_server, monkeypatch):
    # The reported bug: trigger for a non-primary character must NOT error.
    from unittest.mock import AsyncMock
    from digital_actor.dialogue import DialogueLine
    from metahuman_actor.game_driven.scene import FollowupHint

    ws = FakeWS()
    await multi_server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)

    multi_server._stage._characters["dorn"].scene.trigger_with_hint = AsyncMock(
        return_value=(DialogueLine(name="Dorn", text="Arr.", line_id="D1"),
                      FollowupHint(line_id="D1", available=True, suggested_delay_seconds=6.0))
    )
    # Unreal sends capitalized "Dorn".
    await multi_server._handle_message(
        {"type": "trigger", "npc": "Dorn", "name": "greet", "info": {},
         "world_state": {}, "request_followup_hint": True},
        ws,
    )
    # No error frame; a followup_hint with the RESOLVED npc ("dorn") was sent.
    assert not any(f.get("type") == "error" for f in ws.sent)
    hints = [f for f in ws.sent if f["type"] == "followup_hint"]
    assert hints and hints[-1]["npc"] == "dorn" and hints[-1]["line_id"] == "D1"


@pytest.mark.asyncio
async def test_respond_for_second_character_no_error(multi_server):
    from unittest.mock import AsyncMock
    from digital_actor.dialogue import DialogueLine
    ws = FakeWS()
    await multi_server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    multi_server._stage._characters["barkeep"].scene.respond_with_hint = AsyncMock(
        return_value=(DialogueLine(name="Barkeep", text="Aye.", line_id="B1"), None)
    )
    await multi_server._handle_message(
        {"type": "respond", "npc": "barkeep", "text": "hello", "world_state": {}}, ws
    )
    assert not any(f.get("type") == "error" for f in ws.sent)


@pytest.mark.asyncio
async def test_respond_unknown_npc_errors(multi_server):
    ws = FakeWS()
    await multi_server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    await multi_server._handle_message(
        {"type": "respond", "npc": "ghost", "text": "hi", "world_state": {}}, ws
    )
    assert ws.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_set_interaction_changes_only_one(multi_server):
    ws = FakeWS()
    await multi_server._handle_message({"type": "load_scenario", "name": "tavern"}, ws)
    # Need a 'barter' interaction to exist; the default multi fixture has only
    # 'converse'. Reload with barter present:
```

For `test_set_interaction_changes_only_one` the default `multi_server` fixture only has `converse`. Either (a) add a second fixture with `interactions=("converse","barter")` and `characters=((dorn,...),(barkeep,...))`, or (b) drop this server-level interaction test and rely on the stage-level `set_interaction` coverage from Task 3. RECOMMENDED: drop the half-written `test_set_interaction_changes_only_one` from the server tests (it's covered at the stage level); delete those last lines so the file is valid. Keep the four complete tests above.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_server.py -k "multi or second_character or lists_all or unknown_npc" -v`
Expected: FAIL — server still uses `_validate_npc` (rejects non-primary npc) and reaches into `_scene`.

- [ ] **Step 3: Rewrite the server arms**

In `metahuman_actor/game_driven/server.py`:

(a) **`load_scenario` arm** — change the `scenario_loaded` reply's `interactions` to the full map:

```python
                await stage.load_scenario(name)
                await ws.send(
                    json.dumps(
                        {
                            "type": "scenario_loaded",
                            "name": name,
                            "scene": stage.current_scene,
                            "interactions": stage.interactions_map(),
                        }
                    )
                )
                return
```

(b) **`set_scene` arm** — full interactions map:

```python
            if msg_type == "set_scene":
                scene = (msg.get("scene") or "").strip()
                await stage.set_scene(scene)
                await ws.send(
                    json.dumps(
                        {
                            "type": "scene_changed",
                            "scene": stage.current_scene,
                            "interactions": stage.interactions_map(),
                        }
                    )
                )
                return
```

(c) **`set_interaction` arm** — resolve via stage, echo resolved id + that character's interaction:

```python
            if msg_type == "set_interaction":
                npc = (msg.get("npc") or "").strip()
                interaction = (msg.get("interaction") or "").strip()
                await stage.set_interaction(npc, interaction)
                resolved = stage._resolve_npc(npc)
                await ws.send(
                    json.dumps(
                        {
                            "type": "interaction_changed",
                            "npc": resolved,
                            "interaction": stage.interactions_map()[resolved],
                        }
                    )
                )
                return
```

(d) **`respond` arm** — delegate to `stage.respond`, echo resolved npc:

```python
            if msg_type == "respond":
                npc = msg.get("npc")
                text = (msg.get("text") or "").strip()
                if not text:
                    await ws.send(
                        json.dumps({"type": "error", "message": "respond: empty text"})
                    )
                    return
                world_state = msg.get("world_state") or {}
                request_followup = bool(msg.get("request_followup_hint", False))
                emotions = msg.get("emotions")
                resolved, hint = await stage.respond(
                    npc, text, world_state, emotions=emotions,
                    request_followup_hint=request_followup,
                )
                await self._maybe_send_hint(ws, resolved, hint)
                return
```

(e) **`trigger` arm** — delegate to `stage.trigger`, echo resolved npc:

```python
            if msg_type == "trigger":
                npc = msg.get("npc")
                name = (msg.get("name") or "").strip()
                info = {str(k): str(v) for k, v in (msg.get("info") or {}).items()}
                world_state = msg.get("world_state") or {}
                request_followup = bool(msg.get("request_followup_hint", False))
                resolved, hint = await stage.trigger(
                    npc, name, info, world_state,
                    request_followup_hint=request_followup,
                )
                await self._maybe_send_hint(ws, resolved, hint)
                return
```

(f) **Remove `_validate_npc`** entirely (the method and both call sites — they're replaced by `stage.respond`/`stage.trigger` which resolve internally). Keep `_maybe_send_hint` as-is.

Note the `npc` empty-string handling: previously the code did `(msg.get("npc") or "").strip()`. Now pass `msg.get("npc")` straight through (may be `None`); `stage._resolve_npc` treats falsy as "use primary". Do NOT pre-`.strip()` it to `""` in a way that loses `None` — passing `None` or the raw string is correct since `_resolve_npc` handles both.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/metahuman_actor/game_driven/test_server.py -v`
Expected: new multi-character server tests pass. **Existing single-character server tests**: the ones that asserted `respond`/`trigger` against the single `zeek` character should still pass (zeek is now the sole + primary character; `npc:"zeek"` resolves, omitted npc → primary). If any existing test stubbed `stage._scene.respond_with_hint`, update it to stub `stage._characters[<cid>].scene.respond_with_hint` instead. Report which existing tests you updated.

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/game_driven/server.py tests/metahuman_actor/game_driven/test_server.py
git commit -m "server: delegate npc routing to the multi-character stage"
```

---

## Task 6: Full sweep + a real multi-character smoke scenario

- [ ] **Step 1: Run the whole game_driven suite**

Run: `uv run pytest tests/metahuman_actor/game_driven/ -v`
Expected: all pass (multi-character + preserved single-character).

- [ ] **Step 2: Run the full repo suite**

Run: `uv run pytest -q`
Expected: all pass. (The old authoritative server and library are untouched.)

- [ ] **Step 3: Convert `zeek_gd` is NOT needed; verify single-character still loads via the real loader**

Run:
```bash
uv run python -c "
from langfuse_utils import langfuse_session
from metahuman_actor.game_driven.scenario import GameDrivenScenario
with langfuse_session(local=True):
    s = GameDrivenScenario.load('zeek_gd')
    print('zeek_gd characters:', s.characters, 'primary:', s.default_character)
"
```
Expected: `zeek_gd characters: ['zeek'] primary: zeek` (single-character normalization works on the real on-disk scenario).

- [ ] **Step 4: Commit any fixups**

```bash
git add -A
git commit -m "multi-character: test sweep fixups"
```

---

## Notes for the implementer

- **Do not modify** `GameDrivenScene`, `GameDrivenSceneData`, `MetaHumanDigitalActor`, or `packages/`.
- The big risk is **existing single-character tests in `test_stage.py`/`test_server.py`** that referenced `stage.actor`, `stage.current_interaction`, `stage._scene`, or stubbed `stage._scene.respond_with_hint`. These break because those fields changed. Update them to the multi-character API (`character_ids()`, `interactions_map()`, `scene_data`, `_characters[cid]...`). Read both test files fully before Task 3/5 and fix breakages as part of those tasks. Report every existing test you change.
- **Active-pointer discipline**: `respond`/`trigger` set `self._active_character = cid` BEFORE awaiting generation. Never generate without setting it first — the generating actor reads `stage_context.scene_data`/`tts_client` which depend on it.
- **Atomic load/scene-switch**: build all new objects before swapping any state, so a failure (missing persona, missing interaction folder) leaves prior state intact and surfaces as an error frame.
- `stage._resolve_npc` is called from the server for `set_interaction`'s echo; it's a `_`-prefixed method but used cross-module here — acceptable, or promote to `resolve_npc` (no underscore) if you prefer a cleaner public surface. Keep consistent with whatever you choose.
- Keep `casefold()` matching for all npc resolution (Unreal FName capitalization).
```
