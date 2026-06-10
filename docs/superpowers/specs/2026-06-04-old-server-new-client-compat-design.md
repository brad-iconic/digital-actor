# Old Authoritative Server — New-Client Compatibility Adapter

## Background

The Unreal C++ client was migrated to speak **only** the new game-driven
protocol (`respond` / `trigger` / `set_scene` / `set_interaction` / lifecycle),
and the old authoritative protocol (`user_input` / `start_game` / `say` /
`audio_finished` / …) was removed client-side
(see `docs/superpowers/handovers/2026-06-04-unreal-cpp-client-protocol-confirmation.md`).

We still want to run the **old authoritative server** (`metahuman_actor/server.py`)
from the **new client** for authoritative-mode playtesting — without keeping a
legacy client around. Today the new client's `respond` frames are silently
dropped by the old server (it expects `user_input`), and the dropped `start_game`
means the opening speech never plays. So the old server is currently unusable
from the new client.

## Goal

Add a thin compatibility adapter at the old server's wire layer so the new
client can drive it in authoritative mode. Authoritative behavior (server-side
idle/followup timers, the tick loop, the existing prompts) is preserved exactly —
only the *inbound message translation* changes.

## Scope

- **Only `metahuman_actor/server.py`'s `_handle_inbound` dispatch changes.**
- `MetaHumanStage`, `MetaHumanSingleActorScene`, the authoritative actor, and all
  old prompts (`dialogue/get_next_line`, etc.) are **untouched**.
- The new client in authoritative mode sends: `load_scenario`, `list_scenarios`,
  `respond`, and the lifecycle frames `unload_scenario` / `set_scene` /
  `set_interaction`. It does **not** send `trigger` in this mode.
- Legacy clients (if any) keep working: `start_game`, `say`, `user_input`, and the
  existing `_dispatch` types remain supported.

Out of scope (deliberately):
- Surfacing `world_state` into authoritative prompts (the old mode has no
  situational-context slot; emergence is a game-driven-only feature).
- Plumbing `emotions` (the `MetaHumanStage.on_user_input(message)` signature takes
  no emotions; expanding it is out of scope).
- Emitting `followup_hint` (authoritative mode drives followups on its own clock;
  the client tolerates the frame's absence).
- Handling `trigger` (the client doesn't send it in authoritative mode).

## Design

Three new/changed arms in `_handle_inbound`, plus deliberate non-handling of two
frame types.

### 1. `respond` → authoritative player input

New dispatch arm:

```python
elif msg_type == "respond":
    text = (msg.get("text") or "").strip()
    if not text:
        await ws.send(json.dumps({"type": "error", "message": "respond: empty text"}))
        continue
    logger.info("<<< respond: %s", text[:80])
    await self._stage.on_user_input(text)
```

- Reads `text` only. Ignores `npc`, `world_state`, `request_followup_hint`,
  `emotions` — the authoritative path has no slots for them.
- `on_user_input` records the player line, generates the actor response, and the
  server's tick loop continues to drive idle/followups as before.
- Empty/whitespace text → `error` frame (mirrors the new server's behavior and the
  existing `say` empty-text handling).
- This arm sits alongside the existing `start_game` / `say` arms (before the
  `_dispatch` fallthrough), since it is a scenario-dependent message.

### 2. `load_scenario` → auto-deliver opening speech

The new client never sends `start_game`, so the old server delivers the scene's
authored opening line at load time instead. After the existing `scenario_loaded`
frame is sent:

```python
await ws.send(json.dumps({"type": "scenario_loaded", "name": name}))
await self._stage.deliver_opening_speech()
continue
```

- `scenario_loaded` is sent **first** so the client has its load confirmation
  before the opening `text`/`audio` stream arrives.
- `deliver_opening_speech()` is idempotent (guarded by the scene's
  `_opening_delivered` flag) and no-ops when there is no opening text, so this is
  safe and matches what `start_game` used to do.
- `start_game` remains a supported message; calling it after load is harmless
  (the guard prevents a double opening).

### 3. `unload_scenario` → teardown + ack

New dispatch arm (before the `_dispatch` fallthrough):

```python
elif msg_type == "unload_scenario":
    await self._stage.unload_scenario()
    await ws.send(json.dumps({"type": "scenario_unloaded"}))
```

- `unload_scenario` is allowed when nothing is loaded (the stage method no-ops),
  so it does **not** sit behind the "no scenario loaded" guard. Place this arm
  among the always-allowed types (next to `list_scenarios` / `load_scenario`),
  not after the guard.
- Replies with `{"type": "scenario_unloaded"}`, the frame the new client expects.

### 4. `set_scene` / `set_interaction` → no handling (ignored)

The old server has no scene/interaction concept and the client tolerates silence
on these (it only updates state if a reply arrives). They require **no code**:
they fall through to the existing `_dispatch`, which logs "Unknown message type"
and does nothing. This is acceptable and intentional — no ack, no error.

### 5. Unchanged

`start_game`, `say`, `list_scenarios`, and all existing `_dispatch` types
(`user_input`, `game_event`, `interrupt`, `audio_finished`, `reset`, `ping`)
remain exactly as they are.

## Outbound compatibility (no change needed)

The old server's outbound frames are already byte-compatible with the new client's
parser:

- `text` / `audio_chunk` / `audio_done` — identical field names; the client parses
  them unchanged.
- `game_event` (checkpoint callbacks), `error`, `scenarios`, `scenario_loaded` —
  shapes the client already handles. (`scenario_loaded` from the old server carries
  only `name`; the client's parser treats `scene`/`interactions` as optional, so a
  `name`-only frame is accepted — it just leaves the client's scene/interaction
  cache empty, which is correct for authoritative mode.)

The old server **never sends** `followup_hint`. In authoritative mode the server
drives followups itself, so the client's followup timer simply never starts. This
is the intended authoritative behavior.

## Wire behavior summary (new client → old server)

| Inbound | Old-server behavior |
|---|---|
| `list_scenarios` | unchanged → `scenarios` frame |
| `load_scenario {name}` | load (ignores absent `persona`) → `scenario_loaded {name}` → auto `deliver_opening_speech()` |
| `unload_scenario` | teardown → `scenario_unloaded` |
| `respond {text, …}` | `on_user_input(text)`; other fields ignored; empty text → error |
| `set_scene` / `set_interaction` | ignored (logged unknown; no reply) |
| `trigger` | not sent in this mode; would log unknown |

## Error handling & edge cases

- **`respond` before `load_scenario`:** the existing "no scenario loaded" guard
  (which precedes the scenario-dependent arms) returns an `error` frame. The
  `respond` arm sits after that guard, so this is covered with no extra code.
- **Empty `respond.text`:** explicit `error` frame.
- **`load_scenario` failure:** the existing try/except around load already sends an
  `error` frame and `continue`s; `deliver_opening_speech()` is only reached on
  success.
- **Double opening:** `start_game` then a load, or two loads — the
  `_opening_delivered` guard (reset on scene reset/load) prevents a duplicate
  opening for the same scene.
- **Disconnect:** unchanged — the old server's `_handle_connection` finally-block
  already drains say-tasks, unloads, and pauses the runtime.

## Testing

Handler-level tests (TTS disabled), mirroring the existing
`tests/metahuman_actor/test_ws_scenario.py` style with a fake/recording websocket:

1. `respond {text}` drives `on_user_input` and produces an actor line.
2. `respond` with empty/whitespace text → `error` frame; no line generated.
3. `respond` before any `load_scenario` → `error` frame ("no scenario loaded").
4. `load_scenario` sends `scenario_loaded` **then** delivers the opening speech
   (assert the opening line is delivered, and ordering: load frame before opening).
5. `load_scenario` with no opening text → no crash, no opening line (guard no-ops).
6. `unload_scenario` → `scenario_unloaded` frame; stage returns to empty.
7. `set_scene` / `set_interaction` → no crash, no reply frame (ignored).
8. Regression: existing `start_game`, `say`, `user_input` paths still behave as
   before (a representative test each, if not already covered).

## Files changed

- `metahuman_actor/server.py` — `_handle_inbound` dispatch (the three arms above).
- `tests/metahuman_actor/test_ws_scenario.py` (or a sibling test module) — the
  handler-level tests above.

No other files change.
