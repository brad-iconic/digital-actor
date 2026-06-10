# Multi-Character Support for the Game-Driven Server

## Background

The game-driven server (`metahuman_actor/game_driven/`) currently loads exactly
one character per scenario. The stage holds a single `actor` + single `_scene`,
and the server validates the inbound `npc` against that one character
(`_validate_npc`). Testing the `pirate_tavern` scenario in Unreal — which has
multiple NPCs (Dorn, a barkeep, …) — a `trigger` for `Dorn` fails with
`ValueError: unknown npc 'Dorn'`, because the server only knows the single loaded
character.

## Goal

Support **multiple characters live in a single loaded scenario**. The player
interacts with one character at a time (1:1), addressing each by `npc` on every
message. The scene holds shared world backstory true for all characters; each
character has its own backstory, conversation history, voice, and current
interaction. Advancing the scene moves all characters forward together.

## Runtime model (agreed)

- All characters declared by the scenario load together at `load_scenario`.
- The game addresses one character per message via `npc` (1:1). It may address
  any loaded character at any time.
- The **scene** holds the shared world `scene_description` (true for all
  characters at this story stage).
- Each **character** has its own `character_back_story` (per scene), its own
  conversation history, its own voice (persona), and its own current interaction.
- `set_scene` advances **all** characters to the next scene (shared world change,
  e.g. day → night), resetting every character to the default interaction;
  histories persist.
- `set_interaction(npc, …)` changes **one** character's interaction mode.

## The core technical problem and its resolution

Actors build their LLM prompt by reading `stage_context.scene_data` (e.g.
`MetaHumanDigitalActor.get_next_line_prompt_info` and `get_summary_prompt_info`
read `stage_context.scene_data.character_back_story`, `.scene_description`, etc.).
`stage_context` is a **single module-global proxy** to the one registered stage,
exposing one `scene_data`. With N characters there is no single `scene_data`.

**Resolution (active-pointer):** the stage holds all characters and an
`_active_character` pointer. `stage_context.scene_data` (and `.tts_client`) return
the **active** character's values. Every request that drives a character sets
`_active_character` to that character immediately before generating. This is safe
because generation is already serialized — the WebSocket inbound loop processes
messages strictly sequentially, and each character's scene has its own response
lock — so only one character ever generates at a time. The active pointer is set
synchronously right before the `await` that generates, within the same handler
call.

Rejected alternatives:
- *Actor reads scene_data from its own scene instead of the global*: cleaner in
  theory but requires changing `MetaHumanDigitalActor`'s prompt builders (which
  read `stage_context.scene_data`), a deeper and more invasive change.
- *One stage per character*: impossible — `stage_context` is a module-global
  singleton (`set_stage` replaces a single `_current`); N stages cannot be
  registered at once.

## Scope

- Changes are confined to `metahuman_actor/game_driven/` (scenario loader, stage,
  server) + the `scenario.json` schema + test fixtures.
- `GameDrivenScene`, `GameDrivenSceneData`, `MetaHumanDigitalActor`, and the
  shared library (`packages/digital_actor/`) are **unchanged in shape**.
- **Single-character back-compat is required**: existing one-character scenarios
  (e.g. `zeek_gd`, no `characters` list) and all existing `game_driven` tests must
  continue to pass unchanged.

## scenario.json schema

New shape:

```json
{
  "characters": ["dorn", "barkeep", "smuggler", "captain"],
  "default_character": "dorn",
  "default_scene": "scene_1",
  "default_interaction": "converse"
}
```

- `characters` — authoritative list of character ids to load. Each id must have a
  `personas/<id>.json` and a `<default_scene>/characters/<id>/<default_interaction>/`
  folder.
- `default_character` — the **primary** character. Optional; defaults to
  `characters[0]`. Used as the fallback when a message omits `npc`, and reported
  where a single "primary" is meaningful.
- `default_scene` / `default_interaction` — unchanged; every character starts in
  the default scene and the default interaction.

**Back-compat normalization:** if `characters` is absent, the loader synthesizes
`characters = [default_character]`. So a single-`default_character` `scenario.json`
(today's `zeek_gd`) loads as a one-character scenario with no change to the file.

## Components

### `GameDrivenScenario` (scenario.py)

- Add a `characters: list[str]` property: returns the `characters` array, or
  `[default_character]` when absent (normalization).
- `default_character` remains; when `characters` is present and
  `default_character` absent, default it to `characters[0]`.
- Existing path helpers (`persona_path(character)`, `interaction_dir(scene,
  character, interaction)`, `has_interaction(...)`) already take a `character`
  argument — no change needed; they're called per-character now.

### `LoadedCharacter` (new, stage.py)

A small internal holder, one per loaded character:

```
LoadedCharacter:
    actor: MetaHumanDigitalActor      # owns this character's history
    scene: GameDrivenScene            # owns this character's scene_data + response lock
    tts_client: TTSClient | None      # this character's voice
    current_interaction: str
```

### `GameDrivenStage` (stage.py) — the main change

Fields:
- `_characters: dict[str, LoadedCharacter]` — keyed by lowercase character id.
- `_active_character: str | None` — id whose scene_data/tts_client are exposed.
- `_primary: str | None` — primary character id (from scenario).
- `current_scene: str | None` — scenario-wide.
- `_scenario`, `_tts_enabled` — as today.

Removed: the single `self.actor`, single `self._scene` usage (the base
`SingleSceneStage._scene` machinery is superseded — see "Base class" below).

Properties (read by `stage_context` during generation):
- `scene_data` → `self._characters[self._active_character].scene.scene_data`
  (or `None` if nothing loaded / no active character).
- `tts_client` → `self._characters[self._active_character].tts_client`
  (or `None`).

Name resolution:
```
_resolve_npc(npc: str | None) -> str:
    if not npc: return self._primary
    for cid in self._characters:
        if cid.casefold() == npc.casefold(): return cid
    raise UnknownNpcError(npc)
```

Routing methods (called by the server; encapsulate the active-pointer discipline):
- `async respond(npc, text, world_state, emotions, request_followup_hint) -> (resolved_npc, FollowupHint | None)`
- `async trigger(npc, name, info, world_state, request_followup_hint) -> (resolved_npc, FollowupHint | None)`

Each: `cid = self._resolve_npc(npc)`; `self._active_character = cid`; `hint = await
self._characters[cid].scene.respond_with_hint(...)` / `trigger_with_hint(...)`;
return `(cid, hint)`. The returned `cid` is the resolved id the server echoes in
the `followup_hint` frame.

Lifecycle:
- `load_scenario(name)` — build a `LoadedCharacter` for every `scenario.characters`
  entry (atomic: build all before swapping any state). On success: drain prior
  characters, reset, install `_characters`, set `_primary` and
  `_active_character = _primary`, set `current_scene = default_scene`.
- `unload_scenario()` — drain all characters' in-flight responses, reset each,
  clear `_characters`, `_active_character`, `_primary`, `current_scene`, scenario.
- `set_scene(scene)` — validate `scene` exists; for **every** character validate
  `(scene, char, default_interaction)` exists and build its new scene_data
  (build-all-before-swap); drain all; swap each holder's `scene.scene_data`; reset
  each `current_interaction = default_interaction`; set `current_scene`.
- `set_interaction(npc, interaction)` — `cid = _resolve_npc(npc)`; validate
  `(current_scene, cid, interaction)` exists; build new scene_data; drain that
  character; swap its `scene.scene_data`; set its `current_interaction`.
- `await_idle()` — drains **all** characters' response locks (each
  `GameDrivenScene.await_idle`).
- `reset()` — resets every character's scene/actor.

Helper:
- `interactions_map() -> dict[str, str]` → `{cid: holder.current_interaction}` for
  all loaded characters. Used to build `scenario_loaded` / `scene_changed` frames.

#### Base class note

`GameDrivenStage` currently extends `SingleSceneStage` and uses its `_scene`,
`register_scene`, `await_idle`, `reset`. With multiple scenes (one per character),
the single `_scene` slot no longer fits. The stage will manage its own
`_characters` dict and override `await_idle`/`reset`/`scene_data` accordingly. It
may continue to extend `SingleSceneStage` for the LLM/messenger plumbing in
`BaseStage`, but must not rely on the single-`_scene` behavior. The implementation
should confirm whether extending `BaseStage` directly (rather than
`SingleSceneStage`) is cleaner; either is acceptable as long as the library is not
modified and `set_stage(self)` still registers the stage for `stage_context`.

### `GameDrivenServer` (server.py)

- `_handle_message`'s `respond`/`trigger` arms delegate routing to the stage:
  `resolved_npc, hint = await stage.respond(npc, text, world_state, emotions,
  request_followup)`; then `await self._maybe_send_hint(ws, resolved_npc, hint)`.
- **Remove** the hardcoded `_validate_npc`/single-actor check. Unknown npc now
  raises `UnknownNpcError` from `stage._resolve_npc` (caught by the existing
  try/except → error frame).
- `set_interaction` arm: `await stage.set_interaction(npc, interaction)`; reply
  `interaction_changed {npc: <resolved>, interaction: stage's current for that char}`.
- `set_scene` arm: `await stage.set_scene(scene)`; reply `scene_changed {scene,
  interactions: stage.interactions_map()}`.
- `load_scenario` arm: reply `scenario_loaded {name, scene: current_scene,
  interactions: stage.interactions_map()}`.
- `scenario_loaded` / `scene_changed` now carry the **full** `{npc: interaction}`
  map for all characters (non-breaking: the client replaces its whole interaction
  map from these frames).

### conftest (tests)

`write_scenario_tree` gains a `characters=(...)` parameter (default a single
character, preserving existing tests). When multiple are given, it scaffolds a
persona + per-character scene/interaction folders for each and writes a
`characters` list into `scenario.json`.

## Wire protocol impact

No new message types. The only observable changes:
- `respond`/`trigger` for any loaded `npc` now work (previously only the single
  default character).
- `scenario_loaded` / `scene_changed` `interactions` maps contain one entry per
  loaded character (was always one entry).
- `npc` echoed in `followup_hint` is the resolved (canonical lowercase) id.

The client already replaces its whole interaction map from these frames and routes
by `npc`, so multi-entry maps require no client change.

## Concurrency & safety

- The WS inbound loop processes messages strictly sequentially; each
  `GameDrivenScene` has its own response lock. Only one character generates at a
  time, so the single `_active_character` pointer is always correct during
  generation. It is set synchronously immediately before the generating `await`.
- There are no server-side timers in the game-driven path, so no background task
  can flip the active pointer mid-generation.
- `set_scene` / `set_interaction` drain (`await_idle`) before swapping scene_data,
  per affected character(s), so a swap never races a running response.

## Error handling & edge cases

- Unknown `npc` (no casefold match) → `UnknownNpcError` → error frame.
- Omitted `npc` → primary character.
- Casefold matching everywhere `npc` is resolved (Unreal `FName` sends e.g.
  `"Dorn"` for `dorn`).
- Single-character scenario (no `characters` list) → normalized to one character;
  identical behavior to today.
- `set_scene` where any character lacks the default interaction in the new scene →
  raise before any swap (all-or-nothing); prior state intact.
- Load-time: any listed character missing persona / default scene-interaction
  folder → `load_scenario` raises; prior state intact; server emits error frame.
- Unknown `trigger` name for the active character → `KeyError` → error frame (as
  today).
- Disconnect → drain all characters, unload.

## Testing

Extend `tests/metahuman_actor/game_driven/` (TTS disabled):

1. **Loader**: `scenario.json` with `characters` list → `scenario.characters`
   returns all; no-list single-`default_character` → normalized to one; absent
   `default_character` with a list → defaults to `characters[0]`.
2. **Stage load (multi)**: loads N characters, each with own actor/history/
   scene_data/tts/current_interaction; `_active_character == _primary`;
   `interactions_map()` has all N at the default interaction.
3. **Routing**: `respond("dorn", …)` drives Dorn and appends only to Dorn's
   history; `respond("Dorn", …)` casefold-resolves to `dorn`; `respond("nobody")`
   → UnknownNpcError; omitted `npc` → primary.
4. **scene_data follows active pointer**: after driving `dorn` then `barkeep`,
   each generation's prompt carried that character's `character_back_story` (assert
   via stub stage capturing the compiled prompt).
5. **History isolation**: dorn → barkeep → dorn; Dorn's 2nd turn sees Dorn's 1st
   turn, not the barkeep's.
6. **`set_interaction("dorn","barter")`**: only Dorn changes; barkeep stays
   `converse`; Dorn's history preserved.
7. **`set_scene`**: all characters move; all interactions reset to default; all
   histories preserved; `scene_changed.interactions` shows all at default.
8. **Server (the reported bug)**: load a multi-character scenario, `trigger` for
   `Dorn` → no `unknown npc`; produces a line; `scenario_loaded.interactions` has
   all characters.
9. **Single-character regression**: existing `zeek_gd`-style one-character flow
   still works end-to-end.
10. **Full sweep**: `game_driven` suite + full repo suite green.

## Files changed

- `metahuman_actor/game_driven/scenario.py` — `characters` property + normalization.
- `metahuman_actor/game_driven/stage.py` — `LoadedCharacter`, per-character holders,
  active pointer, routing methods, multi-character lifecycle (the main change).
- `metahuman_actor/game_driven/server.py` — delegate routing to stage; remove
  `_validate_npc`; full `interactions` maps; echo resolved `npc`.
- `tests/metahuman_actor/game_driven/conftest.py` — multi-character
  `write_scenario_tree`.
- `tests/metahuman_actor/game_driven/test_scenario.py`, `test_stage.py`,
  `test_server.py` — new multi-character tests + preserved single-character tests.

No changes to `GameDrivenScene`, `GameDrivenSceneData`, the actor, prompts, or the
library.

## Out of scope (future)

- Multi-party conversations (more than one character responding to a single turn,
  or characters addressing each other). v1 remains strictly 1:1 — one character per
  request.
- Per-character cross-session memory / persistence (history is still in-memory for
  the life of the loaded scenario).
- Per-scene persona overrides (a character's voice/identity differing by scene).
