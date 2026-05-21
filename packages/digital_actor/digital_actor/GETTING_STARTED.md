# Getting Started: `digital_actor`

The package is built around four concepts that sit on top of each other. You can stop at any layer depending on what your NPC needs.

| Layer | Class | Responsibility |
|---|---|---|
| **Actor** | `DigitalActor` / `BasicSceneDigitalActor` | Character brain — prompt construction, dialogue history, TTS |
| **Scene** | `SingleActorScene` | Moment-to-moment interaction — idle, followup, interrupts, checkpoints |
| **Stage** | `SingleActorStage` / `MultiActorStage` / `SingleSceneStage` / `MultiSceneStage` | Infrastructure — LLM client, TTS client, Messenger, output routing |
| **Runtime** | `Runtime` | Tick loop — calls `stage.step(t)` at a fixed rate |

Actors and scenes never hold direct references to the stage. Instead they call through a global proxy — `stage_context` — which is automatically wired when any `BaseStage` subclass is constructed. This keeps actors and scenes free of infrastructure coupling.

Each section below has a matching runnable script in `python/examples/`.

---

## 1. Actor + Stage

> **Runnable example:** `python/examples/example_1_actor_stage.py`

The minimal setup: one character, no ticking, no scene. You send a message and get a response back directly.

**What you implement:** Subclass `DigitalActor` and fill in two prompt methods.

```python
from digital_actor.actor import DigitalActor
from digital_actor.data_models import PromptInfo


class TavernKeeper(DigitalActor):

    def get_next_line_prompt_info(self) -> PromptInfo:
        return PromptInfo(
            prompt=f"You are Greta, a gruff but warm tavern keeper.\n\n{self.history.to_string()}",
            input_args={},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise:\n{dialogue}", input_args={})
```

Use `SingleActorStage` to wire everything up. It creates the LLM client internally and defaults to no Messenger — `on_user_input` returns the response text directly:

```python
import asyncio
from digital_actor.stage import SingleActorStage


async def main():
    actor = TavernKeeper("keeper", "Greta", "Runs the local tavern.", character_info=None)
    stage = SingleActorStage(actor, llm_model="cerebras/qwen-3-235b-a22b-instruct-2507")
    # stage_context is wired automatically on construction

    while True:
        reply = await stage.on_user_input(input("> "))
        print(f"Greta: {reply}")

asyncio.run(main())
```

When you're ready to serve over a network, pass a messenger type and use `stage.on_user_input()` from your connection handler instead:

```python
stage = SingleActorStage(actor, llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)
```

---

## 2. Actor + Stage + Runtime

> **Runnable example:** `python/examples/example_2_runtime.py`

Add a `Runtime` and the stage begins **ticking** — enabling time-driven behaviour like idle lines and followup. `Runtime` is generic: it knows nothing about stages. You hand it any async callable that accepts an elapsed-time float.

```python
import asyncio
from digital_actor.runtime import Runtime
from digital_actor.stage import SingleActorStage
from digital_actor.messenger import MessengerType


async def serve():
    actor = TavernKeeper("keeper", "Greta", "Runs the local tavern.", character_info=None)
    stage = SingleActorStage(actor, llm_model="cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)

    runtime = Runtime()
    runtime.subscribe(stage.step)   # stage.step(elapsed_time: float) is the tick entry point
    runtime.start(tick_rate=20)     # 20 ticks per second

    # ... run your server, accept connections, call stage.on_user_input

    await runtime.stop()            # cancels the tick task cleanly
```

On each tick, `stage.step(t)` sets `stage.elapsed_time = t`, drains the inbound game-event queue, then calls `stage.tick()`.

**Pausing** stops the clock and skips all tick callbacks:

```python
runtime.pause()   # stops time and ticking
runtime.resume()  # resumes from where it left off
```

To drive the stage from a **game engine** instead, skip the Runtime entirely and call `stage.step(engine.elapsed_time)` from your engine's tick callback. The stage is agnostic about who drives it.

---

## 3. Actor + Stage + Scene

> **Runnable example:** `python/examples/example_3_scene.py`

A `SingleActorScene` wraps an actor and takes over the full interaction loop. Instead of calling `actor.on_user_input()` directly, you call `scene.on_user_input()` and `scene.tick()`, and the scene decides when and how the actor speaks.

**What the scene handles automatically:**
- **Idle**: if the actor spoke last and the player has been silent longer than `idle_timeout`, the actor speaks unprompted
- **Followup**: after each actor line, the scene LLM-queries whether a followup makes sense; if yes, the actor adds to their thought after a short delay
- **Interrupts**: if the player cuts the actor off mid-line, the actor's history is trimmed to the truncation point
- **Checkpoints**: story beats that fire when game events arrive or when the LLM judges a dialogue condition is met

### Setting up the actor

For scene-driven actors use `BasicSceneDigitalActor`, which extends the prompt signature with context flags:

```python
from digital_actor.actor import BasicSceneDigitalActor
from digital_actor.data_models import BasicSceneData, PromptInfo


class InnKeeper(BasicSceneDigitalActor):

    def get_next_line_prompt_info(
        self,
        is_idle: bool = False,
        is_interrupt: bool = False,
        is_followup: bool = False,
        interrupt_count: int = 0,
    ) -> PromptInfo:
        backstory = self.scene_data.scene_back_story or ""
        script = self.scene_data.scene_description or ""
        idle_hint = "\n(The player has gone quiet. Speak up.)" if is_idle else ""
        interrupt_hint = "\n(The player cut you off. Acknowledge it briefly.)" if is_interrupt else ""
        prompt = f"{backstory}\n\nScene: {script}\n\n{self.history.to_string()}{idle_hint}{interrupt_hint}"
        return PromptInfo(prompt=prompt, input_args={"is_idle": is_idle})

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise:\n{dialogue}", input_args={})
```

### Setting up the scene

Subclass `SingleActorScene` and implement the two query-prompt methods. These are called when the scene needs to ask the LLM a yes/no question about the dialogue:

```python
from digital_actor.scene import SingleActorScene
from digital_actor.data_models import PromptInfo


class InnKeeperScene(SingleActorScene):

    def get_query_followup_prompt_info(self) -> PromptInfo:
        """Should the actor add a followup line to what they just said?"""
        last_line = next(
            (l.text for l in reversed(self.actor.history.messages) if l.name == self.actor.name),
            "",
        )
        prompt = (
            f"Dialogue:\n{self.actor.history.to_string()}\n\n"
            f"Last line: \"{last_line}\"\n"
            "Reply YES if the actor would naturally want to add something more, NO otherwise."
        )
        return PromptInfo(prompt=prompt, input_args={})

    def get_query_prompt_info(self, text: str, question: str) -> PromptInfo:
        """Given this dialogue excerpt, is the following statement true?"""
        return PromptInfo(
            prompt=f"Dialogue:\n{text}\n\nStatement: {question}\nReply YES or NO.",
            input_args={},
        )
```

### Scene data: backstory and checkpoints

`BasicSceneData` carries everything the scene and actor need to stay in character:

```python
from digital_actor.data_models import BasicSceneData
from digital_actor.checkpoints import SceneCheckpoints

scene_data = BasicSceneData(
    scene_back_story=(
        "The Rusty Flagon inn, late evening. Candles flicker. "
        "A mysterious hooded figure sits in the corner."
    ),
    scene_description=(
        "You are Aldric, the innkeeper. Be welcoming but keep an eye on the stranger. "
        "If the player asks about the stranger, deflect — you have been warned to stay quiet."
    ),
    checkpoints=SceneCheckpoints.from_dict({
        "nodes": [
            # Fires when a game event named "stranger_leaves" arrives from the game engine
            {
                "id": "stranger_gone",
                "type": "Event",
                "event_id": "stranger_leaves",
                "narrator_message": {"true": "The hooded figure slips out the back door."},
            },
            # Fires when the LLM judges the player has asked about the stranger.
            # Only activates after "stranger_gone" has completed (dependency).
            {
                "id": "player_asks_about_stranger",
                "type": "Query",
                "target": "Player",
                "query_str": "The player asks who the mysterious figure was",
                "dependency": "stranger_gone",
                "narrator_message": {"true": "Aldric glances nervously at the door."},
                "callbacks": ["reveal_stranger_secret"],
            },
        ]
    }),
)
```

Two checkpoint types:

- **`EventCheckpoint`** — waits for a named game event (`stage.queue_game_event(GameEvent(name="stranger_leaves", info={}))`). When it fires, a narrator message is injected into the actor's history and any callbacks are emitted as `GameEvent`s back to the client.
- **`QueryCheckpoint`** — after each actor line, the scene runs the `query_str` as a yes/no LLM query against the dialogue history. Fires when the LLM answers YES. Callbacks and narrator messages work the same way.

Checkpoints chain via `dependency`: a node only becomes active once its dependency is satisfied, letting you sequence story beats without writing state-machine code.

### Wiring it together

```python
from digital_actor.stage import SingleSceneStage
from digital_actor.runtime import Runtime
from digital_actor.messenger import MessengerType
from digital_actor.game_events import GameEvent

async def serve():
    actor = InnKeeper("aldric", "Aldric", "The innkeeper of the Rusty Flagon.", None, scene_data)
    scene = InnKeeperScene(actor, scene_data, idle_timeout=30.0)

    stage = SingleSceneStage("cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)
    stage.register_scene(scene)

    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)

    # Player message arrives from your connection handler:
    await stage.on_user_input("Is there a room for the night?")

    # Game event from the engine triggers the "stranger_gone" checkpoint:
    stage.queue_game_event(GameEvent(name="stranger_leaves", info={}))
    # → processed on next tick → narrator message injected
    # → "player_asks_about_stranger" becomes active
```

---

## 4. Multiple actors and scene transitions

> **Runnable examples:** `python/examples/example_4_multi_actor.py` · `python/examples/example_5_multi_scene.py`

### Multiple actors without scenes

`MultiActorStage` runs several `DigitalActor` instances on the same stage with no scene layer. Each actor responds directly to player input — no idle, followup, or checkpoint handling. Use this when you want simple conversational NPCs without time-driven behaviour.

```python
from digital_actor.stage import MultiActorStage
from digital_actor.runtime import Runtime
from digital_actor.messenger import MessengerType

async def serve():
    stage = MultiActorStage("cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)

    greta = TavernKeeper("greta", "Greta", "Runs the local tavern.", character_info=None)
    brom = Blacksmith("brom", "Brom", "Works the forge.", character_info=None)

    stage.register_actor(greta, actor_id="greta")
    stage.register_actor(brom, actor_id="brom")

    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)

    # Each message targets a specific actor
    await stage.on_user_input("Got any ale?", actor_id="greta")
    await stage.on_user_input("Can you fix my sword?", actor_id="brom")
```

### Multiple actors with scenes

`MultiSceneStage` runs several actor-scene pairs on the same stage, each with their own identity, history, scene features, and checkpoint graph. Each actor is registered with a `scene_id` and players target scenes by that ID.

```python
from digital_actor.stage import MultiSceneStage
from digital_actor.runtime import Runtime
from digital_actor.messenger import MessengerType
from digital_actor.game_events import GameEvent

async def serve():
    stage = MultiSceneStage("cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)

    aldric = InnKeeper("aldric", "Aldric", "Innkeeper.", None, aldric_scene_data)
    bjorn = Blacksmith("bjorn", "Bjorn", "Blacksmith.", None, bjorn_scene_data)

    stage.register_scene(InnKeeperScene(aldric, aldric_scene_data), scene_id="aldric")
    stage.register_scene(BlacksmithScene(bjorn, bjorn_scene_data), scene_id="bjorn")

    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)

    # Each message targets a specific scene
    await stage.on_user_input("Any work for a traveller?", scene_id="bjorn")
    await stage.on_user_input("One room please.", scene_id="aldric")

    # Events can be broadcast to all scenes or targeted to one
    stage.queue_game_event(GameEvent(name="night_falls", info={}))
```

Each actor's dialogue is routed to the player session bound to that actor, so two players can be talking to different NPCs simultaneously.

### Scene transitions: one actor, multiple acts

An actor's behaviour is driven by `scene_data` — the backstory, script, and checkpoint graph. Replacing `scene_data` mid-run transitions the actor into a new "act" with different context and objectives.

The cleanest trigger is a checkpoint callback. When a checkpoint fires it emits a `GameEvent` named after the callback. Override `on_game_event` in your stage to intercept it and swap the data:

```python
from digital_actor.stage import SingleSceneStage
from digital_actor.game_events import GameEvent, GameEventBase


ACT_2_DATA = BasicSceneData(
    scene_back_story="The stranger is gone. The inn feels quieter — but Aldric knows too much.",
    scene_description=(
        "You are Aldric. The player has earned your trust. "
        "You can now speak freely about what you saw. Be cautious but honest."
    ),
    checkpoints=SceneCheckpoints.from_dict({"nodes": []}),  # fresh checkpoint graph
)


class InnKeeperStage(SingleSceneStage):

    def __init__(self, actor: InnKeeper, scene: InnKeeperScene, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._actor = actor
        self._scene = scene

    async def on_game_event(self, event: GameEventBase) -> None:
        if isinstance(event, GameEvent) and event.name == "reveal_stranger_secret":
            self._actor.scene_data = ACT_2_DATA
            self._scene.scene_data = ACT_2_DATA
            self._scene._query_cache.clear()
            return
        await super().on_game_event(event)
```

What changes in act 2:
- `scene_description` feeds a different script to the actor's next-line prompt
- `scene_back_story` updates the narrative context
- A fresh `SceneCheckpoints` graph replaces the old one, enabling new beats

The actor's **history** carries over between acts — the player's conversation is preserved. If the new act should feel like a clean start, call `actor.history.reset()` before swapping.

---

## 5. Messenger

The Messenger is how actor dialogue reaches the client. Every `deliver_text` and `deliver_speech` call on the stage flows through it.

`GrpcMessenger` and `WebSocketMessenger` share the same session-routing interface so stage code is transport-agnostic. You can switch between them at startup without changing anything else.

### Types

| Type | Use case |
|---|---|
| `NullMessenger` | Default when `messenger=None` — `on_user_input` returns response text directly as `str` |
| `GrpcMessenger` | gRPC streaming (e.g. bidirectional Chat RPC) |
| `WebSocketMessenger` | asyncio WebSocket servers |

Pass a concrete messenger or a `MessengerType` string to any stage constructor:

```python
from digital_actor.messenger import GrpcMessenger, MessengerType

stage = SingleSceneStage("cerebras/qwen-3-235b-a22b-instruct-2507", messenger=GrpcMessenger())

# or by enum string — stage creates the instance for you:
stage = SingleSceneStage("cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.GRPC)
```

### Outbound payload format

Every frame sent to the client is an `OutboundPayload`:

| Field | Type | Description |
|---|---|---|
| `actor_name` | `str` | Which actor is speaking |
| `text` | `str \| None` | Dialogue text (set when TTS is off or alongside audio) |
| `audio_chunk` | `bytes \| None` | Raw PCM audio chunk (set when streaming TTS) |
| `line_id` | `str` | Stable ID for this line — used to match interrupts back to the right line |
| `interruptible` | `bool` | Whether the client may interrupt this line (default `True`) |
| `user_input_ack` | `bool` | `True` on the first frame of a response, signals the client that input was received |
| `is_final_audio` | `bool` | `True` on the last audio frame for a line |
| `tts_sample_rate` | `int` | Sample rate of the audio stream; `0` when no audio |

Each actor line produces one text payload followed by one or more audio chunks (if TTS is enabled), ending with a final audio frame where `is_final_audio=True`.

### Wiring a connection

`delivering(request_id)` is an async context manager that wires the outbound queue for one session and sets `current_request_id` for the duration. Any `emit_payload` call made inside the block is automatically routed to this session.

```python
async with messenger.delivering(session_id) as queue:
    # emit_payload() now routes here — no need to pass the ID around
    await stage.on_user_input(text)

    # drain the queue to your transport as needed:
    payload = await queue.get()  # None sentinel signals the session is done
```

When only one session is active and `current_request_id` is not set (e.g. payloads emitted by the Runtime between requests), `emit_payload` falls back to that single active delivery automatically.

### Single session

The common case — one player, one connection:

```python
async def handle_connection(ws, stage):
    async with stage.messenger.delivering(str(uuid4())) as queue:
        inbound = asyncio.create_task(handle_inbound(ws, stage))
        outbound = asyncio.create_task(drain_outbound(ws, queue))
        await asyncio.wait([inbound, outbound], return_when=asyncio.FIRST_COMPLETED)
        inbound.cancel(); outbound.cancel()
```

### Multi-session (concurrent clients)

Each client gets its own session ID. Sessions are isolated — `delivering` can be active for multiple IDs simultaneously:

```python
# Per-client handler (same code runs for every connection):
async with messenger.delivering(client_id) as queue:
    ...
```

### Multi-actor routing

When using `MultiActorStage` or `MultiSceneStage`, bind each actor to the session of the player talking to them:

```python
# Player "alice" is talking to Aldric; player "bob" is talking to Bjorn
stage.messenger.bind_actor_to_session("Aldric", session_id="alice")
stage.messenger.bind_actor_to_session("Bjorn", session_id="bob")

# Stage calls emit_payload_for_actor(payload) — routes by actor name, not context var
await stage.on_user_input("One room please.", scene_id="aldric")
```

`bind_actor_to_session` uses the actor's **display name** (the `name` field, not `actor_id`). Call `messenger.clear_actor_session_bindings()` at the end of a session to reset all mappings.

### WebSocket example

The messenger handles session routing. Your server code owns the connection lifecycle, wire format, and drain loops.

```python
import asyncio
import base64
import json
from uuid import uuid4

import websockets
from digital_actor.messenger import OutboundPayload, WebSocketMessenger


def payload_to_frame(payload: OutboundPayload) -> dict | None:
    if payload.text is not None:
        return {
            "type": "text",
            "line_id": payload.line_id,
            "actor_name": payload.actor_name,
            "text": payload.text,
            "interruptible": payload.interruptible,
        }
    if payload.audio_chunk:
        return {
            "type": "audio_chunk",
            "line_id": payload.line_id,
            "data": base64.b64encode(payload.audio_chunk).decode(),
            "sample_rate": payload.tts_sample_rate,
            "is_final": payload.is_final_audio,
        }
    if payload.is_final_audio:
        return {"type": "audio_done", "line_id": payload.line_id}
    return None


async def drain_outbound(ws, queue):
    try:
        while True:
            payload = await queue.get()
            if payload is None:
                break
            frame = payload_to_frame(payload)
            if frame is not None:
                await ws.send(json.dumps(frame))
    except asyncio.CancelledError:
        pass


async def drain_game_events(ws, messenger):
    try:
        async for event in messenger.game_events():
            await ws.send(json.dumps({"type": "game_event", "name": event.name, "info": event.info}))
    except asyncio.CancelledError:
        pass


async def handle_connection(ws, messenger, stage):
    request_id = str(uuid4())
    async with messenger.delivering(request_id) as queue:
        event_task = asyncio.create_task(drain_game_events(ws, messenger))
        inbound_task = asyncio.create_task(handle_inbound(ws, stage))
        outbound_task = asyncio.create_task(drain_outbound(ws, queue))
        try:
            await asyncio.wait([inbound_task, outbound_task], return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in [inbound_task, outbound_task, event_task]:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


async def main():
    messenger = WebSocketMessenger()
    stage = MyStage(messenger=messenger)

    async with websockets.serve(lambda ws: handle_connection(ws, messenger, stage), "localhost", 8788):
        await asyncio.Future()
```

### gRPC example

Same session interface, different transport. The gRPC framework manages connection lifecycle externally.

```python
from digital_actor.messenger import GrpcMessenger


class MyServicer(my_pb2_grpc.MyServiceServicer):
    def __init__(self, stage):
        self.messenger = GrpcMessenger()
        self.stage = stage

    async def Chat(self, request_iterator, context):
        async with self.messenger.delivering(context.peer()) as queue:
            outbound_task = asyncio.create_task(drain_to_stream(queue))
            async for request in request_iterator:
                await self.stage.on_user_input(request.text)
            outbound_task.cancel()
```
