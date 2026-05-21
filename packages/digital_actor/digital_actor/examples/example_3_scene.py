"""
Example 3: Actor + Stage + Scene
==================================
A `SingleActorScene` wraps the actor and handles:
  - idle lines (actor speaks if the player goes quiet)
  - followup (actor adds to their thought after a short delay)
  - checkpoints (story beats triggered by events or LLM queries)

This demo uses an innkeeper who is hiding something about a mysterious stranger.

Special commands:
  !stranger_leaves   — send a game event that triggers the checkpoint
  quit               — exit
"""

import asyncio

from digital_actor.actor import BasicSceneDigitalActor
from digital_actor.checkpoints import SceneCheckpoints
from digital_actor.data_models import BasicSceneData, PromptInfo
from digital_actor.game_events import GameEvent
from digital_actor.messenger import MessengerType, OutboundPayload
from digital_actor.runtime import Runtime
from digital_actor.scene import SingleActorScene
from digital_actor.stage import SingleSceneStage
from dotenv import load_dotenv

load_dotenv()


async def _print_payloads(queue: asyncio.Queue[OutboundPayload | None]) -> None:
    while True:
        payload = await queue.get()
        if payload is None:
            break
        if payload.text:
            print(f"\n{payload.actor_name}: {payload.text}")


# ── scene data ────────────────────────────────────────────────────────────────

scene_data = BasicSceneData(
    scene_back_story=(
        "The Rusty Flagon inn, late evening. Candles flicker. A mysterious hooded figure sits alone in the corner."
    ),
    scene_description=(
        "You are Aldric, the innkeeper. Be welcoming but guarded. "
        "If the player asks about the stranger in the corner, deflect — "
        "you have been warned to stay quiet about them."
    ),
    checkpoints=SceneCheckpoints.from_dict(
        {
            "nodes": [
                # Fires when the game sends a "stranger_leaves" event
                {
                    "id": "stranger_gone",
                    "type": "Event",
                    "event_id": "stranger_leaves",
                    "narrator_message": {"true": "The hooded figure slips out the back door without a word."},
                },
                # Fires when the LLM judges the player has asked about the stranger
                # (only active after stranger_gone completes)
                {
                    "id": "player_asks_about_stranger",
                    "type": "Query",
                    "target": "Player",
                    "query_str": "The player asks who the mysterious figure was",
                    "dependency": "stranger_gone",
                    "narrator_message": {"true": "Aldric glances nervously at the door, then leans in close."},
                    "callbacks": ["secret_revealed"],
                },
            ]
        }
    ),
)


# ── actor ─────────────────────────────────────────────────────────────────────


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
        idle_hint = "\n(The player has gone quiet. Say something to fill the silence.)" if is_idle else ""
        interrupt_hint = "\n(You were just cut off mid-sentence. Acknowledge it briefly.)" if is_interrupt else ""
        return PromptInfo(
            prompt=f"{backstory}\n\nScene: {script}\n\n{self.history.to_string()}{idle_hint}{interrupt_hint}",
            input_args={"is_idle": is_idle},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise this inn conversation briefly:\n{dialogue}", input_args={})


# ── scene ─────────────────────────────────────────────────────────────────────


class InnKeeperScene(SingleActorScene):
    def get_query_followup_prompt_info(self) -> PromptInfo:
        last_line = next(
            (line.text for line in reversed(self.actor.history.messages) if line.name == self.actor.name),
            "",
        )
        return PromptInfo(
            prompt=(
                f"Dialogue:\n{self.actor.history.to_string()}\n\n"
                f'Last line: "{last_line}"\n'
                "Reply YES if the innkeeper would naturally want to add something more, NO otherwise."
            ),
            input_args={},
        )

    def get_query_prompt_info(self, text: str, question: str) -> PromptInfo:
        return PromptInfo(
            prompt=f"Dialogue:\n{text}\n\nStatement: {question}\nReply YES or NO.",
            input_args={},
        )


# ── main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    actor = InnKeeper("aldric", "Aldric", "The innkeeper of the Rusty Flagon.", None, scene_data)
    scene = InnKeeperScene(actor, scene_data, idle_timeout=20.0)

    stage = SingleSceneStage("cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)
    stage.register_scene(scene)

    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)

    print("Chat with Aldric.")
    print("  !stranger_leaves  — send a game event (triggers the checkpoint)")
    print("  quit              — exit\n")

    async with stage.messenger.delivering("player") as queue:
        consumer = asyncio.create_task(_print_payloads(queue))
        try:
            while True:
                msg = await asyncio.to_thread(input, "> ")
                msg = msg.strip()
                if not msg:
                    continue
                if msg == "quit":
                    break
                elif msg == "!stranger_leaves":
                    stage.queue_game_event(GameEvent(name="stranger_leaves", info={}))
                    print("[game event queued: stranger_leaves — will fire on the next tick]")
                else:
                    await stage.on_user_input(msg)
        finally:
            await runtime.stop()
    await consumer


asyncio.run(main())
