# Game-Driven Dialogue Server

## Background

Today's `MetaHumanServer` is an **authoritative runtime**. A `Runtime` ticks at
20 Hz, calls `stage.step()` → `scene.tick()`, and the scene
(`SingleActorScene`) decides on its own when the NPC speaks: it manages followup
deadlines, idle timeouts, and a server-side estimate of when client audio
playback finishes (`playback_end_buffer_sec`, `_audio_finished_at`,
`_pending_followup_args`). The server is effectively *directing* the scene.

This causes structural problems:

- The server only **estimates** when audio finishes. An "8s followup" on a 10s
  line can overdub.
- The server can't know the player is mid-speech, that a cutscene is playing, or
  that the game is in a state where a followup is unwanted.
- All this game-state knowledge lives in the game engine, which is forced to
  reconstruct it on the server through `audio_finished` callbacks and timing
  fudge factors.

## Goal

Invert authority. The game engine owns the simulation clock and all situational
judgment (when to speak, whether the moment permits speaking). The server becomes
a **request-driven dialogue/context engine**: given the loaded scenario lore, the
NPC's ongoing conversation history, and a per-request snapshot of game state, it
produces a convincing in-character line *only when asked*.

The server has **no clock** in this path — no tick-driven behavior, no followup
timers, no idle timers, no playback-end estimation.

## Scope

- **v1 is single-character.** One character per loaded scenario. The wire protocol
  carries an `npc` field on every message so multi-character is a non-breaking
  future addition, but v1 enforces one loaded actor.
- **Additive only.** All new code lives under `metahuman_actor/`. The existing
  authoritative server, stage, and scene are untouched and remain runnable. The
  shared library `packages/digital_actor/` is **not modified**.
- **The two servers never run in parallel.** They coexist as code. You launch one
  *or* the other via separate entry points.

Out of scope (explicit future work):

- Multi-character scenarios (v2).
- History persistence across scenario unload / process restart / level reload.
- Per-(scene, interaction) checkpoint-state persistence on scene re-entry.
- Full checkpoint redesign for the request-driven paradigm (v1 keeps a
  stripped-down version of the existing mechanism).

## Vocabulary

A three-tier model. "Scene" was previously overloaded; it is now reserved for the
narrative-stage meaning.

- **Scenario** — the whole bundle (e.g. `tavern_brawl`). Holds scenario-level lore
  and a registry of personas.
- **Scene** — a *narrative stage* of the scenario (e.g. "player just arrived",
  "player has achieved X"). Scenario-wide: advancing the scene affects every
  character. The game advances scenes as the story progresses.
- **Character** — an NPC (e.g. `zeek`). Has a persona (voice + identity) and, per
  scene, scene-bound lore and interactions.
- **Interaction** — *how a single character is being engaged right now* (e.g.
  `converse`, `barter`, `intimidate`). Per-character; different characters can be
  in different interactions within the same scene.

At any moment: the scenario is on **scene** *S*, the player is engaging character
*C* via **interaction** *I*. The scene is global; the interaction is per-character.

## Architecture

### Code layering

```
packages/digital_actor/                  <- shared library, UNTOUCHED
  digital_actor/
    actor.py        (SceneDigitalActor, history, line generation, run_tts)
    scene.py        (SingleActorScene — authoritative, not used here)
    stage.py        (BaseStage, scene-management subclasses)
    checkpoints.py  (SceneCheckpoints, Event/Query checkpoints)
    history.py, game_events.py, runtime.py, messenger.py, stage_context.py

metahuman_actor/                         <- application code
  server.py                  <- existing authoritative path, untouched
  stage.py                   <- existing
  scene.py                   <- existing (MetaHumanSingleActorScene)
  scenario.py                <- existing loader; gains a new loader variant
  game_driven_server.py      <- NEW: MetaHumanGameDrivenServer + its main()
  game_driven_stage.py       <- NEW: MetaHumanGameDrivenStage
  game_driven_scene.py       <- NEW: GameDrivenScene
```

The new path is launched with its own entry point
(`python -m metahuman_actor.game_driven_server`). The two servers share the same
WS port and the same Langfuse/prompt-loading conventions, but only one runs at a
time.

### Components

- **`GameDrivenScene`** implements the library's `BaseScene` abstract interface.
  Holds the actor, its continuous `history`, the active `scene_data` (rotating),
  `current_scene` / `current_interaction` names, and a per-NPC response lock. It
  has **no** `tick` logic, **no** followup deadline, **no** `audio_finished`
  handling. It dispatches inbound intents (`respond`, `trigger`) to handler
  methods and emits the `followup_hint` frame when the optional parallel query
  resolves.

  It reuses, unchanged, the library primitives that constitute dialogue "craft":
  `SceneDigitalActor` (line generation, `run_tts`, history, summarization),
  `SceneCheckpoints` (optional), `stage_context.llm_acomplete`, and the messenger
  plumbing. It does **not** inherit from `SingleActorScene` — the timing
  orchestration that class provides is exactly what we are removing.

- **`MetaHumanGameDrivenStage`** owns scenario lifecycle for the new layout: load
  personas, load scene-bound content, build the TTS client, construct the actor
  and `GameDrivenScene`. It supports `set_scene` (scenario-wide narrative advance)
  and `set_interaction` (per-character engagement mode) by rebuilding the active
  `scene_data` while preserving history.

- **`MetaHumanGameDrivenServer`** is a `WebSocketServer` subclass implementing the
  new wire protocol. It does not subscribe the scene to a `Runtime` tick (the
  scene's `tick` is a no-op). It serves the same TTS HTTP endpoint as today.

## On-disk scenario layout

Everything for a scenario lives under one tree (no split between code-side
`scenarios/` and `.langfuse_prompts/scenarios/`). Personas live in a flat
registry; scene-bound content is nested scenario → scene → character →
interaction. The layout is multi-character-ready even though v1 loads one
character.

```
scenarios/tavern_brawl/
  scenario.json                          <- default_character, default_scene, default_interaction
  back_story.txt                         <- scenario-level lore (the whole arc)
  personas/
    zeek.json                            <- voice config, identity, LLM tuning (one per character)
    grog.json
  scene_1_just_arrived/
    scene_description.txt                <- world context for this stage, shared by all characters
    characters/
      zeek/
        character_back_story.txt         <- Zeek's lore as of this scene
        converse/
          steer_back_instructions.txt
          opening_speech.txt             <- optional
          checkpoints.json               <- optional
          triggers/                      <- optional
            greet/
              prompt.txt
              narrator.txt               <- optional
            player_drew_weapon/
              prompt.txt
              narrator.txt
        barter/
          steer_back_instructions.txt
          triggers/
            player_offered_gold/
              prompt.txt
              narrator.txt
      grog/
        character_back_story.txt
        converse/
          steer_back_instructions.txt
  scene_2_after_X/
    scene_description.txt                <- the world has moved on
    characters/
      zeek/
        character_back_story.txt         <- may differ from scene 1 (Zeek now wary)
        converse/
          steer_back_instructions.txt
          triggers/...
```

Notes:

- `personas/<character>.json` is the single home for a character's voice/identity.
  No per-scene persona override in v1 (a character who is *fundamentally* different
  in a later scene — e.g. possessed — is modeled as a separate character).
- `scene_supplement.txt` (today's Jinja-templated per-scenario runtime fragment)
  is **obsolete** in this path. Its job is replaced by the auto-rendered
  `## Current situation` block (see below).
- `triggers/` is optional. A `trigger` whose name has no folder under the active
  scene/interaction is rejected with an error frame.
- The trigger registry is built by listing `triggers/*/` folders that contain a
  `prompt.txt`. A missing `prompt.txt` simply means the folder is not a trigger.

### Migration of existing scenarios

Today's `scenarios/<name>/scene1/` + `.langfuse_prompts/scenarios/<name>/...`
split is consolidated into the tree above. A `scene1` directory becomes a
narrative scene (e.g. `scene_1_...`) and the inner prompt files move under
`characters/<name>/<interaction>/`. The existing authoritative server's loader is
unchanged and continues to read the old layout; the two paths can use
differently-formatted scenarios during migration.

## Prompt assembly

Two top-level line-generation templates, deliberately separate so they can
diverge (they will share scaffolding early on):

- `dialogue/get_respond_line.txt` — used for `respond` (player spoke).
- `dialogue/get_trigger_line.txt` — used for `trigger` (a game event occurred).

Both compose, in order:

```
## Character          {{character_back_story}}        (scene-bound, per character)
## Scene              {{scene_description}}            (scene-bound, shared)
## Current situation  <world_state rendered as key: value lines>
## Recent event       {{trigger_prompt}}              (get_trigger_line only; trigger's prompt.txt rendered with `info`)
[dialogue summary wrapper if a summary exists]
## Dialogue           {{dialogue_history}}
{{steer_back_instructions}}                            (interaction-bound)
```

Scenario-level `back_story.txt` is composed into the character/scene lore as it is
today (e.g. included by `character_back_story.txt`).

### The `## Current situation` block

`world_state` (a dict sent by the game on every `respond`/`trigger`) is rendered
**mechanically** as labeled `key: value` lines. It is **not** writer-templated:
the writer's prompt files are stable lore; the game-side designer iterates on
runtime variables (adding/removing/changing them) without touching prompts. New
variables appear in the block automatically; the LLM reads them as situational
context. If `world_state` is empty, the block is omitted.

### Followup query

Unchanged from today's `query/query_followup.txt` — fed
`scene_description + actors + dialogue + last_line`, returns `YES`/`NO`. World
state and trigger context are **not** fed in (keeps the binary stable; can be
extended later). The single-bit output is what makes the query reliable.

## Wire protocol

### Inbound (game → server)

| `type` | Fields | Notes |
|---|---|---|
| `list_scenarios` | — | |
| `load_scenario` | `name` | Loads scenario, default character/scene/interaction from `scenario.json`. |
| `unload_scenario` | — | Tears down; history is lost. |
| `set_scene` | `scene` | Scenario-wide narrative advance. Resets every character to the scenario `default_interaction`. No `npc`. |
| `set_interaction` | `npc`, `interaction` | Per-character engagement-mode switch within the current scene. |
| `respond` | `npc`, `text`, `world_state`, `request_followup_hint`, `emotions?` | Player said `text`; produce a reply. Empty `text` → error frame. |
| `trigger` | `npc`, `name`, `info`, `world_state`, `request_followup_hint` | A game event occurred; produce a line. |

`request_followup_hint` is a bool. **Server default when omitted is `false`** (no
query, no hint). The game explicitly sets `true` on routine requests; this keeps
every emitted hint traceable to an explicit `true` in the wire log.

### Outbound (server → game)

| `type` | Fields | Notes |
|---|---|---|
| `scenarios` | `names`, `active` (nullable) | |
| `scenario_loaded` | `name`, `scene`, `interactions` | `interactions`: map of character → current interaction. |
| `scene_changed` | `scene`, `interactions` | Reports post-reset interactions. |
| `interaction_changed` | `npc`, `interaction` | |
| `text` / `audio` frames | (existing `OutboundPayload` shape) | Dialogue stream, unchanged from today. |
| `followup_hint` | `npc`, `line_id`, `available`, `suggested_delay_seconds` | Late-arriving; paired to its line by `line_id`. |
| `error` | `message` | Uniform single-frame error. |

There is **no** `audio_finished`, **no** `start_game`, **no** admin `say` in this
protocol.

## Data flow

### `load_scenario(name)`

1. Read `scenario.json` (`default_character`, `default_scene`, `default_interaction`).
2. Read `back_story.txt`.
3. Read `personas/<default_character>.json`; build TTS client (or skip if
   `tts_enabled` is false); construct `SceneDigitalActor`.
4. Read scene-bound content under
   `<default_scene>/characters/<default_character>/<default_interaction>/`
   (`steer_back_instructions.txt`, optional `opening_speech.txt`, optional
   `checkpoints.json`, optional `triggers/`), plus `<default_scene>/scene_description.txt`
   and the character's `character_back_story.txt`.
5. Construct `GameDrivenScene` with the actor and assembled `scene_data`.
6. Emit `scenario_loaded` with name, scene, and interactions map.

Any failure unwinds cleanly and emits `error`; prior state is untouched.

### `respond(npc, text, world_state, request_followup_hint, emotions?)`

1. Validate `npc` matches the loaded character; validate `text` non-empty
   (else `error`).
2. Acquire the response lock.
3. Append `Player: <text>` to history.
4. Build the prompt from `get_respond_line.txt` (lore + `## Current situation`
   from `world_state` + summary wrapper + history + `steer_back_instructions`).
5. Run the LLM → `DialogueLine`; emit the `text` frame.
6. Run TTS streaming and (if `request_followup_hint`) the followup query
   concurrently, **both inside the lock**. Emit `audio` frames; final frame sets
   `is_final_audio`.
7. If the followup query is enabled, emit `followup_hint` (paired by `line_id`)
   when it resolves. `available` from the LLM; `suggested_delay_seconds` from
   scene config.
8. Run `history.summarize_if_needed()`; release the lock. **No playback-end
   sleep** — that authoritative-server pacing is gone.

### `trigger(npc, name, info, world_state, request_followup_hint)`

Same as `respond`, except:

- Look up `name` in the active `scene_data` trigger registry; unknown → `error`.
- If the trigger has `narrator.txt`, render it with `info` and append
  `Narrator: <text>` to history. Otherwise nothing is added to history for the
  triggering event itself.
- Build the prompt from `get_trigger_line.txt`, whose `## Recent event` section is
  the trigger's `prompt.txt` rendered with `info` as context.
- Event checkpoints whose `event_id` matches `name` are evaluated (existing
  library mechanism); their callbacks emit as game events.

### `set_scene(scene)` and `set_interaction(npc, interaction)`

Both: validate the target exists (else `error`, no state change); drain any
in-flight response via `await_idle()`; build the new `scene_data` fully before
swapping (failure leaves prior state intact); swap; clear ephemeral per-turn
state; emit the corresponding outbound frame.

- `set_scene` rebuilds `scene_data` for `(new_scene, default_interaction)` and
  resets the interaction to the scenario default.
- `set_interaction` rebuilds for `(current_scene, new_interaction)`.
- **History is preserved across both.**

### Concurrency

The WS handler processes inbound frames strictly sequentially — each handler runs
to completion (including any `await_idle()`) before the next frame is read. The
per-NPC response lock additionally guards any background work spawned within a
single request. Followup hints may resolve and emit after their request handler
returns; they are safe because they are paired to a `line_id` and the game ignores
hints whose line is no longer relevant.

## State model

Three categories of state on `GameDrivenScene`:

- **Durable** (lives while the scenario is loaded): `actor`, `actor.history` (+
  summary), `current_scene`, `current_interaction`, TTS client. Dropped on
  `unload_scenario`/disconnect.
- **Rotating** (bound to the active scene/interaction): `scene_data` (lore,
  trigger registry, optional checkpoint graph). Swapped on `set_scene` /
  `set_interaction`.
- **Ephemeral** (one response pipeline): response-lock state, per-turn query cache.
  Cleared at turn end.

| State | `respond`/`trigger` | `set_interaction` | `set_scene` | `unload` |
|---|---|---|---|---|
| `history` + summary | append | preserved | preserved | dropped |
| `scene_data` | unchanged | rebuilt | rebuilt | dropped |
| checkpoint completed/active sets | mutated by callbacks | reset | reset | dropped |
| ephemeral query cache | cleared at turn end | cleared | cleared | dropped |
| `current_scene` | unchanged | unchanged | updated | dropped |
| `current_interaction` | unchanged | updated | reset to default | dropped |
| TTS client | unchanged | unchanged | unchanged | dropped |

### History is one continuous log

History persists across `set_scene` and `set_interaction`. In scene 2 the LLM can
still see (raw or summarized) what was said in scene 1 — the NPC remembers. This
is the intended emergence. History is in-memory only and lost on unload; a level
reload in the game maps to a scenario reload on the server, which is the intended
"start fresh" boundary.

### Checkpoints (stripped down for v1)

- Loaded from `<scene>/characters/<char>/<interaction>/checkpoints.json` when present.
- **Query checkpoints** are evaluated after `respond` only — not after `trigger`.
- **Event checkpoints** match on `trigger` (by `event_id == name`).
- Callbacks emit as outbound game events (existing mechanism).
- Checkpoint completed/active/dropped state is bound to `scene_data` and is reset
  when the scene/interaction is swapped. Because history persists, re-entering an
  interaction re-evaluates query checkpoints against the accumulated history (so a
  condition met earlier in the conversation may activate immediately on return).
  This is a known, accepted semantic for v1.

A proper checkpoint redesign for the request-driven paradigm is deferred.

## Error handling

- All errors are a single `{"type": "error", "message": "..."}` frame; the
  connection stays open.
- **Load/switch failures** build new objects fully before mutating state, so a
  failure leaves the prior (empty or loaded) state intact.
- **Unknown `npc`** (not the loaded character): error frame.
- **Unknown trigger / scene / interaction**: error frame, no state change.
- **Empty `respond` text**: error frame (no silent drop — surfaces game bugs).
- **Followup query failure/timeout**: silent — no `followup_hint` is emitted; the
  dialogue line and audio are unaffected.
- **Disconnect mid-request**: the response drains; `unload_scenario` then tears
  down. Late followup tasks emit to a closed socket harmlessly.

## Testing

Unit (on `GameDrivenScene` / `MetaHumanGameDrivenStage`, TTS disabled):

1. `load_scenario` populates actor, history, scene_data, current scene/interaction
   from `scenario.json` defaults.
2. `respond` appends `Player:` to history, produces a line, and emits a text frame.
3. `respond` with `request_followup_hint: true` emits a `followup_hint` paired to
   the line's `line_id`; with it false/omitted, no hint is emitted.
4. `trigger` with a registered name produces a line; with `narrator.txt` it appends
   a `Narrator:` line; unknown trigger → error, no state change.
5. `set_interaction` swaps `scene_data` and preserves history; unknown interaction
   → error, prior state intact.
6. `set_scene` swaps `scene_data`, resets interaction to default, preserves
   history; unknown scene → error, prior state intact.
7. `unload_scenario` returns to empty state and is a no-op when nothing is loaded.
8. Empty `respond` text → error frame.

Server-handler:

9. Scenario-dependent messages before `load_scenario` → `error`.
10. `list_scenarios` returns `active: null` when empty.
11. `scenario_loaded` / `scene_changed` carry the correct `interactions` map.

Integration:

12. Load → respond → set_interaction(barter) → respond (history carried, new
    interaction's prompts used) → set_scene → respond (interaction reset to
    default, history still carried).
13. A second scenario with different persona voice loads after unload and produces
    audio in the new voice.

## Open questions / future work

- Multi-character scenarios (concurrent actors, per-character histories, per-NPC
  routing). The wire protocol is already shaped for it.
- History persistence across unload / restart / level reload.
- Per-(scene, interaction) checkpoint-state persistence on re-entry.
- Full checkpoint redesign for request-driven dialogue.
- Optional `Followup(npc)` re-evaluation intent for the "game waited long; hint is
  stale" case (v1 has the game act on the existing hint without re-evaluation).
- Feeding world_state / trigger context into the followup query.
- Optional shared scene-level lore composed into per-character prompts.
