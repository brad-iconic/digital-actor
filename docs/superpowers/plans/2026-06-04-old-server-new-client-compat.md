# Old-Server New-Client Compatibility Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the new game-driven Unreal client drive the old authoritative server (`metahuman_actor/server.py`) in authoritative mode, by translating `respond` → `on_user_input`, auto-delivering the opening speech on `load_scenario` (replacing the dropped `start_game`), and handling `unload_scenario`.

**Architecture:** All changes are in `metahuman_actor/server.py`'s `_handle_inbound` dispatch (the wire layer). `MetaHumanStage`, the authoritative scene, and the old prompts are untouched. `set_scene`/`set_interaction` need no code (they fall through to the existing harmless "unknown type" log). Outbound frames are already compatible; the old server simply never sends `followup_hint` (the client tolerates this).

**Tech Stack:** Python 3.12+, asyncio, `websockets`, pytest + pytest-asyncio. Package manager: `uv`. Run tests with `uv run pytest <path> -v` from the repo root `D:\Iconic\Research\digital-actor`.

---

## Spec

Read `docs/superpowers/specs/2026-06-04-old-server-new-client-compat-design.md` for full rationale.

## Background the engineer needs

`metahuman_actor/server.py` defines `MetaHumanServer(WebSocketServer)`. Its `_handle_inbound(ws)` is an `async for raw in ws:` loop that JSON-parses each frame and dispatches by `msg.get("type")`. The current structure (read the file):

- Always-allowed types handled first, each ending in `continue`: `list_scenarios`, `load_scenario`.
- Then a guard: `if self._stage.scenario is None:` → sends `{"type":"error","message":"no scenario loaded"}` and `continue`.
- Then scenario-dependent types: `start_game` (→ `await self._stage.deliver_opening_speech()`), `say` (→ create_task of `_say_with_error_reporting`), `else: await self._dispatch(msg, ws)`.
- The whole per-message body is wrapped in `try/except Exception` that sends an `error` frame.

Key facts:
- `self._stage` is a `MetaHumanStage`. Relevant async methods: `load_scenario(name, persona_variant=None)`, `unload_scenario()` (no-op if nothing loaded), `deliver_opening_speech()` (idempotent — guarded by the scene's `_opening_delivered`; no-ops if no opening text), `on_user_input(message: str)` (records player line, generates response; signature takes NO emotions).
- `self._stage.scenario` is `None` when nothing is loaded.
- `deliver_opening_speech()` plays the scene's authored `opening_speech.txt` via TTS, once per scene.
- The existing `load_scenario` arm reads `name` and an optional `persona`; the new client never sends `persona`, so `persona_variant` resolves to `None` — that already works, no change needed there beyond adding the opening-speech call.

### Test infrastructure (already exists — reuse it)

`tests/metahuman_actor/test_ws_scenario.py` has:
- A `_FakeWS` class: constructed with a list of incoming dict messages; it is async-iterable (feeds them to `_handle_inbound`) and records everything sent in `.sent` (list of parsed dicts).
- An autouse `_dummy_llm_key` fixture (sets `CEREBRAS_API_KEY`).
- A `_setup(monkeypatch, tmp_path)` helper that mirrors the `zeek` scenario on disk under logical names `default`/`alt` and an autouse cleanup fixture.
- `pytestmark = pytest.mark.asyncio` at module level (so async tests need no per-test marker).
- `LLM = "cerebras/qwen-3-235b-a22b-instruct-2507"`.

Read this file in full before writing tests. Match its construction pattern for `MetaHumanServer` + `_FakeWS`. Build the server with TTS disabled (the stage is constructed via `MetaHumanStage(LLM, messenger=..., tts_enabled=False)` — check `_setup`/existing tests for the exact construction and reuse it verbatim).

IMPORTANT: these tests make REAL LLM calls when `on_user_input` runs (the dummy key is fake). The existing `test_ws_scenario.py` tests avoid that by only exercising `load_scenario`/`list_scenarios` (no generation). For the `respond` tests in this plan, you must AVOID a real LLM call — do this by monkeypatching `self._stage.on_user_input` (or `server._stage.on_user_input`) with an `AsyncMock`/stub that records the call, so the test asserts the translation (respond → on_user_input(text)) WITHOUT generating. Do NOT assert on generated dialogue. See Task 1 for the exact approach.

---

## File structure

- Modify: `metahuman_actor/server.py` — `_handle_inbound` dispatch only.
- Modify/extend: `tests/metahuman_actor/test_ws_scenario.py` — add handler-level tests for the new arms (or a sibling module `test_ws_compat.py` if you prefer isolation; this plan appends to `test_ws_scenario.py` to reuse `_FakeWS`/`_setup`).

No other files change.

---

## Task 1: `respond` → `on_user_input` translation

**Files:**
- Modify: `metahuman_actor/server.py` (`_handle_inbound`)
- Test: `tests/metahuman_actor/test_ws_scenario.py`

- [ ] **Step 1: Write the failing tests (append to test_ws_scenario.py)**

These use a stub `on_user_input` to avoid real LLM calls and assert the translation. Adapt the server/`_FakeWS` construction to match the existing helpers in the file (use `_setup` to get a loaded-scenario state, or load via a `load_scenario` frame first).

```python
async def test_respond_translates_to_on_user_input(monkeypatch, tmp_path):
    import json
    from unittest.mock import AsyncMock
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage
    from digital_actor.messenger import MessengerType

    _setup(monkeypatch, tmp_path)  # mirrors zeek -> default/alt on disk
    stage = MetaHumanStage(LLM, messenger=MessengerType.WEBSOCKET, tts_enabled=False)
    server = MetaHumanServer(stage)
    await stage.load_scenario("default")  # scenario now loaded

    # Stub out generation so no real LLM call happens.
    stage.on_user_input = AsyncMock()

    ws = _FakeWS([{"type": "respond", "npc": "zeek", "text": "Hello there",
                   "world_state": {"x": "1"}, "request_followup_hint": True}])
    await server._handle_inbound(ws)

    stage.on_user_input.assert_awaited_once_with("Hello there")
    # No error frame emitted.
    assert not any(f.get("type") == "error" for f in ws.sent)


async def test_respond_empty_text_errors(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage
    from digital_actor.messenger import MessengerType

    _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, messenger=MessengerType.WEBSOCKET, tts_enabled=False)
    server = MetaHumanServer(stage)
    await stage.load_scenario("default")
    stage.on_user_input = AsyncMock()

    ws = _FakeWS([{"type": "respond", "npc": "zeek", "text": "   ", "world_state": {}}])
    await server._handle_inbound(ws)

    stage.on_user_input.assert_not_awaited()
    assert any(f.get("type") == "error" and "empty text" in f.get("message", "")
               for f in ws.sent)


async def test_respond_before_load_errors(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage
    from digital_actor.messenger import MessengerType

    _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, messenger=MessengerType.WEBSOCKET, tts_enabled=False)
    server = MetaHumanServer(stage)
    stage.on_user_input = AsyncMock()  # no scenario loaded

    ws = _FakeWS([{"type": "respond", "npc": "zeek", "text": "hi", "world_state": {}}])
    await server._handle_inbound(ws)

    stage.on_user_input.assert_not_awaited()
    assert any(f.get("type") == "error" and "no scenario loaded" in f.get("message", "")
               for f in ws.sent)
```

NOTE: verify the `MetaHumanStage` construction args (`tts_enabled`, messenger) and the logical scenario name (`"default"`) against `_setup` in the existing file. If `_setup` returns the server/stage already built, use what it returns instead of re-constructing. Adjust these three tests to match the file's actual helper signatures — keep the ASSERTIONS (translation happens / empty→error / pre-load→error) intact.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -k respond -v`
Expected: FAIL — the `respond` type currently falls through to `_dispatch` which logs "Unknown message type" and does nothing, so `on_user_input` is never called and no error frame is sent.

- [ ] **Step 3: Add the `respond` dispatch arm**

In `metahuman_actor/server.py`, inside `_handle_inbound`, in the scenario-dependent section (AFTER the `if self._stage.scenario is None:` guard, alongside `start_game`/`say`), add a `respond` arm. The cleanest place is to add it as another `elif` in the `start_game`/`say`/`else` chain:

```python
                if msg_type == "start_game":
                    logger.info("<<< start_game")
                    await self._stage.deliver_opening_speech()
                elif msg_type == "respond":
                    text = (msg.get("text") or "").strip()
                    if not text:
                        await ws.send(
                            json.dumps(
                                {"type": "error", "message": "respond: empty text"}
                            )
                        )
                        continue
                    logger.info("<<< respond: %s", text[:80])
                    await self._stage.on_user_input(text)
                elif msg_type == "say":
                    text = (msg.get("text") or "").strip()
                    if not text:
                        await ws.send(
                            json.dumps({"type": "error", "message": "say: empty text"})
                        )
                        continue
                    logger.info("<<< say: %s", text[:80])
                    task = asyncio.create_task(self._say_with_error_reporting(ws, text))
                    self._pending_say_tasks.add(task)
                    task.add_done_callback(self._pending_say_tasks.discard)
                else:
                    await self._dispatch(msg, ws)
```

(Only the `elif msg_type == "respond":` block is new; the rest shows surrounding context so you insert it in the right place. `respond` ignores `npc`/`world_state`/`request_followup_hint`/`emotions` — they are not read.)

NOTE on `continue` vs the surrounding structure: the existing `say` arm uses `continue` for its empty-text early-out, which means these arms sit inside the `async for` loop (not a helper). Match that — the `continue` in the `respond` empty-text branch returns to the top of the `async for raw in ws:` loop, same as `say`. Verify by reading the surrounding code that `continue` is valid at that indentation (it is — the dispatch is directly inside the for-loop's try block).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -k respond -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/server.py tests/metahuman_actor/test_ws_scenario.py
git commit -m "old server: translate respond -> on_user_input"
```

---

## Task 2: `load_scenario` auto-delivers opening speech

**Files:**
- Modify: `metahuman_actor/server.py` (`_handle_inbound`, `load_scenario` arm)
- Test: `tests/metahuman_actor/test_ws_scenario.py`

- [ ] **Step 1: Write the failing test (append to test_ws_scenario.py)**

Assert that after a `load_scenario` frame, `deliver_opening_speech` is invoked, AND that the `scenario_loaded` frame is sent before the opening is delivered. Stub `deliver_opening_speech` to avoid TTS/LLM and to record ordering.

```python
async def test_load_scenario_auto_delivers_opening(monkeypatch, tmp_path):
    import json
    from unittest.mock import AsyncMock
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage
    from digital_actor.messenger import MessengerType

    _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, messenger=MessengerType.WEBSOCKET, tts_enabled=False)
    server = MetaHumanServer(stage)

    order = []
    real_send = []
    # Record when scenario_loaded is sent.
    orig_load = stage.load_scenario
    async def tracking_load(name, persona_variant=None):
        await orig_load(name, persona_variant=persona_variant)
        order.append("loaded")
    stage.load_scenario = tracking_load

    async def fake_open():
        order.append("opening")
    stage.deliver_opening_speech = AsyncMock(side_effect=fake_open)

    ws = _FakeWS([{"type": "load_scenario", "name": "default"}])
    await server._handle_inbound(ws)

    # scenario_loaded frame was sent.
    assert any(f.get("type") == "scenario_loaded" for f in ws.sent)
    # opening speech was delivered.
    stage.deliver_opening_speech.assert_awaited_once()
    # ordering: load completed, scenario_loaded frame sent, THEN opening delivered.
    sent_types = [f.get("type") for f in ws.sent]
    assert sent_types.index("scenario_loaded") >= 0
    assert order == ["loaded", "opening"]
```

NOTE: adapt construction to `_setup`'s actual return/signature, and confirm `"default"` is a valid mirrored scenario name in this file's fixtures. Keep the assertions: scenario_loaded sent + deliver_opening_speech awaited once + ordering loaded-before-opening.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -k auto_delivers_opening -v`
Expected: FAIL — the current `load_scenario` arm sends `scenario_loaded` but never calls `deliver_opening_speech`, so the mock is not awaited.

- [ ] **Step 3: Add the opening-speech call to the `load_scenario` arm**

In `metahuman_actor/server.py`, the existing `load_scenario` arm ends with:

```python
                    await ws.send(json.dumps({"type": "scenario_loaded", "name": name}))
                    continue
```

Change it to deliver the opening speech after sending the load confirmation:

```python
                    await ws.send(json.dumps({"type": "scenario_loaded", "name": name}))
                    # The new game-driven client does not send start_game; deliver
                    # the scene's authored opening line on load instead. Idempotent
                    # (guarded by the scene's _opening_delivered) and a no-op when
                    # there is no opening text.
                    await self._stage.deliver_opening_speech()
                    continue
```

(Insert the `await self._stage.deliver_opening_speech()` line just before the existing `continue`. Do not change the load logic above it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -k auto_delivers_opening -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/server.py tests/metahuman_actor/test_ws_scenario.py
git commit -m "old server: auto-deliver opening speech on load_scenario"
```

---

## Task 3: `unload_scenario` arm

**Files:**
- Modify: `metahuman_actor/server.py` (`_handle_inbound`)
- Test: `tests/metahuman_actor/test_ws_scenario.py`

- [ ] **Step 1: Write the failing test (append to test_ws_scenario.py)**

```python
async def test_unload_scenario_acks_and_empties(monkeypatch, tmp_path):
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage
    from digital_actor.messenger import MessengerType

    _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, messenger=MessengerType.WEBSOCKET, tts_enabled=False)
    server = MetaHumanServer(stage)
    await stage.load_scenario("default")
    assert stage.scenario is not None

    ws = _FakeWS([{"type": "unload_scenario"}])
    await server._handle_inbound(ws)

    assert any(f.get("type") == "scenario_unloaded" for f in ws.sent)
    assert stage.scenario is None


async def test_unload_scenario_when_empty_acks(monkeypatch, tmp_path):
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage
    from digital_actor.messenger import MessengerType

    _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, messenger=MessengerType.WEBSOCKET, tts_enabled=False)
    server = MetaHumanServer(stage)  # nothing loaded

    ws = _FakeWS([{"type": "unload_scenario"}])
    await server._handle_inbound(ws)

    # No "no scenario loaded" error; unload is always allowed.
    assert any(f.get("type") == "scenario_unloaded" for f in ws.sent)
    assert not any(f.get("type") == "error" for f in ws.sent)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -k unload -v`
Expected: FAIL — `unload_scenario` currently falls through to the `scenario is None` guard (when empty → error frame) or to `_dispatch` (when loaded → silently ignored, no `scenario_unloaded` frame).

- [ ] **Step 3: Add the `unload_scenario` arm in the always-allowed section**

In `metahuman_actor/server.py`, place this arm BEFORE the `if self._stage.scenario is None:` guard (so it works whether or not a scenario is loaded), right after the `load_scenario` arm's `continue`:

```python
                if msg_type == "unload_scenario":
                    logger.info("<<< unload_scenario")
                    await self._stage.unload_scenario()
                    await ws.send(json.dumps({"type": "scenario_unloaded"}))
                    continue
```

(This sits among the always-allowed types — `list_scenarios`, `load_scenario`, `unload_scenario` — before the no-scenario guard. `unload_scenario()` is a no-op when nothing is loaded, so the empty case acks cleanly.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -k unload -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add metahuman_actor/server.py tests/metahuman_actor/test_ws_scenario.py
git commit -m "old server: handle unload_scenario with ack"
```

---

## Task 4: `set_scene` / `set_interaction` are ignored (regression guard)

This task adds NO production code (the spec says these are ignored — they fall through to `_dispatch`'s harmless "Unknown message type" log). It adds a test pinning that they neither crash nor emit a reply, so a future change doesn't accidentally start handling them.

**Files:**
- Test: `tests/metahuman_actor/test_ws_scenario.py`

- [ ] **Step 1: Write the test (append to test_ws_scenario.py)**

```python
async def test_set_scene_and_set_interaction_are_ignored(monkeypatch, tmp_path):
    from metahuman_actor.server import MetaHumanServer
    from metahuman_actor.stage import MetaHumanStage
    from digital_actor.messenger import MessengerType

    _setup(monkeypatch, tmp_path)
    stage = MetaHumanStage(LLM, messenger=MessengerType.WEBSOCKET, tts_enabled=False)
    server = MetaHumanServer(stage)
    await stage.load_scenario("default")

    ws = _FakeWS([
        {"type": "set_scene", "scene": "scene_2"},
        {"type": "set_interaction", "npc": "zeek", "interaction": "barter"},
    ])
    await server._handle_inbound(ws)  # must not raise

    # No scene_changed / interaction_changed reply (old server has no such concept).
    assert not any(f.get("type") in ("scene_changed", "interaction_changed")
                   for f in ws.sent)
```

NOTE: These two frames reach `_dispatch` (the `else` branch), which logs "Unknown message type" and returns without sending anything. The test asserts no scene/interaction reply is sent and no exception is raised. (They will NOT produce an `error` frame either, because `_dispatch` swallows unknown types silently — so do not assert an error frame here.)

- [ ] **Step 2: Run test to verify it passes immediately (no prod change)**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -k set_scene_and_set_interaction -v`
Expected: PASS (1 passed) — the behavior already holds; this test pins it.

(If it FAILS — e.g. `_dispatch` raises on these — then `_dispatch`'s unknown-type path needs inspection; report it. Per the code read, it only logs, so it should pass.)

- [ ] **Step 3: Commit**

```bash
git add tests/metahuman_actor/test_ws_scenario.py
git commit -m "old server: pin set_scene/set_interaction as ignored"
```

---

## Task 5: Full sweep + regression check

- [ ] **Step 1: Run the whole WS-scenario test module**

Run: `uv run pytest tests/metahuman_actor/test_ws_scenario.py -v`
Expected: all pass (existing tests + the new respond/load/unload/ignored tests).

- [ ] **Step 2: Run the full repo suite (no regressions)**

Run: `uv run pytest -q`
Expected: all pass. The game_driven suite and the existing authoritative tests are unaffected by these wire-layer additions.

- [ ] **Step 3: Commit any fixups (if needed)**

```bash
git add -A
git commit -m "old server compat: test sweep fixups"
```

---

## Notes for the implementer

- **Do not touch** `MetaHumanStage`, `MetaHumanSingleActorScene`, the actor, or any prompt files. The change is purely in `_handle_inbound`'s dispatch.
- **Match the existing file's test helpers.** Read `tests/metahuman_actor/test_ws_scenario.py` fully first. Use its `_FakeWS`, `_setup`, `_dummy_llm_key`, `LLM`, and `pytestmark`. The exact `MetaHumanStage(...)` construction and the mirrored scenario name (`"default"`/`"alt"`) come from that file — reuse them rather than the illustrative versions above if they differ.
- **Avoid real LLM calls in tests.** The `respond` tests stub `stage.on_user_input`; the `load_scenario` test stubs `stage.deliver_opening_speech`. Never let a test actually generate dialogue (the dummy key would fail or hit the network).
- **`respond` deliberately ignores** `npc`, `world_state`, `request_followup_hint`, `emotions`. That's the spec. Don't add handling for them.
- The dispatch is wrapped in a `try/except Exception` that emits an `error` frame — your new arms are inside it, so any unexpected exception still surfaces as an error frame (matches existing behavior).
