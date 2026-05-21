"""
Example 5: MultiSceneStage + Scene Transitions
================================================
Multiple actor-scene pairs on one stage. Each scene has its own idle timer,
followup queries, and checkpoint graph.

This demo shows a scene transition: Aldric starts guarded but transitions into
a more open character (act 2) once the 'reveal_secret' checkpoint fires. The
transition is driven by overriding `on_game_event` on the stage.

Usage:
  @aldric <message>       — talk to the innkeeper
  @mira <message>         — talk to the merchant
  !fire_at_docks          — send a game event (triggers Mira's checkpoint)
  quit                    — exit
"""

import asyncio

from digital_actor.actor import BasicSceneDigitalActor
from digital_actor.checkpoints import SceneCheckpoints
from digital_actor.data_models import BasicSceneData, PromptInfo
from digital_actor.game_events import GameEvent, GameEventBase
from digital_actor.messenger import MessengerType, OutboundPayload
from digital_actor.runtime import Runtime
from digital_actor.scene import SingleActorScene
from digital_actor.stage import MultiSceneStage
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

aldric_scene_data_act1 = BasicSceneData(
    scene_back_story="The Rusty Flagon inn. Late evening. Candles flicker.",
    scene_description=(
        "You are Aldric, the innkeeper. Be welcoming but guarded. "
        "You know the hooded stranger who was here earlier, but say nothing about them."
    ),
    checkpoints=SceneCheckpoints.from_dict(
        {
            "nodes": [
                {
                    "id": "player_presses_aldric",
                    "type": "Query",
                    "target": "Player",
                    "query_str": "The player directly accuses Aldric of hiding something or demands the truth",
                    "narrator_message": {"true": "Aldric's composure cracks. He glances around and lowers his voice."},
                    "callbacks": ["aldric_act2"],
                }
            ]
        }
    ),
)

aldric_scene_data_act2 = BasicSceneData(
    scene_back_story="The Rusty Flagon inn. The player has earned Aldric's trust.",
    scene_description=(
        "You are Aldric. The player pushed hard enough — you can speak freely now. "
        "Tell them the hooded stranger was a royal courier carrying a sealed letter. "
        "You were paid to keep quiet. Be relieved someone finally knows."
    ),
    checkpoints=SceneCheckpoints.from_dict({"nodes": []}),
)

mira_scene_data = BasicSceneData(
    scene_back_story="A corner table. Mira, a travelling merchant, nurses a cup of wine.",
    scene_description=(
        "You are Mira, a sharp-eyed merchant. You trade in rare goods and information. "
        "You heard rumours about a fire at the docks — if asked, you know more than you let on."
    ),
    checkpoints=SceneCheckpoints.from_dict(
        {
            "nodes": [
                {
                    "id": "fire_at_docks",
                    "type": "Event",
                    "event_id": "fire_at_docks",
                    "narrator_message": {
                        "true": "A distant bell tolls from the harbour district. Mira sits up straight."
                    },
                }
            ]
        }
    ),
)


# ── actor ─────────────────────────────────────────────────────────────────────


class InnActor(BasicSceneDigitalActor):
    def get_next_line_prompt_info(
        self,
        is_idle: bool = False,
        is_interrupt: bool = False,
        is_followup: bool = False,
        interrupt_count: int = 0,
    ) -> PromptInfo:
        backstory = self.scene_data.scene_back_story or ""
        script = self.scene_data.scene_description or ""
        idle_hint = "\n(The player has gone quiet. Add something.)" if is_idle else ""
        return PromptInfo(
            prompt=f"{backstory}\n\nScene: {script}\n\n{self.history.to_string()}{idle_hint}",
            input_args={"is_idle": is_idle},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise:\n{dialogue}", input_args={})


# ── scene ─────────────────────────────────────────────────────────────────────


class InnScene(SingleActorScene):
    def get_query_followup_prompt_info(self) -> PromptInfo:
        last_line = next(
            (line.text for line in reversed(self.actor.history.messages) if line.name == self.actor.name),
            "",
        )
        return PromptInfo(
            prompt=(
                f"Dialogue:\n{self.actor.history.to_string()}\n\n"
                f'Last line: "{last_line}"\n'
                "Reply YES if the character would naturally add something more, NO otherwise."
            ),
            input_args={},
        )

    def get_query_prompt_info(self, text: str, question: str) -> PromptInfo:
        return PromptInfo(
            prompt=f"Dialogue:\n{text}\n\nStatement: {question}\nReply YES or NO.",
            input_args={},
        )


# ── stage with scene-transition hook ─────────────────────────────────────────


class InnStage(MultiSceneStage):
    def __init__(self, aldric: InnActor, aldric_scene: InnScene, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aldric = aldric
        self._aldric_scene = aldric_scene

    async def on_game_event(self, event: GameEventBase) -> None:
        if isinstance(event, GameEvent) and event.name == "aldric_act2":
            # Transition Aldric into act 2 — swap scene_data on both actor and scene
            self._aldric.scene_data = aldric_scene_data_act2
            self._aldric_scene.scene_data = aldric_scene_data_act2
            self._aldric_scene._query_cache.clear()
            print("\n[scene transition: Aldric is now in act 2]\n")
            return
        await super().on_game_event(event)


# ── main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    aldric = InnActor("aldric", "Aldric", "The innkeeper.", None, aldric_scene_data_act1)
    mira = InnActor("mira", "Mira", "A travelling merchant.", None, mira_scene_data)

    aldric_scene = InnScene(aldric, aldric_scene_data_act1, idle_timeout=25.0)
    mira_scene = InnScene(mira, mira_scene_data, idle_timeout=25.0)

    stage = InnStage(aldric, aldric_scene, "cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)
    stage.register_scene(aldric_scene, scene_id="aldric")
    stage.register_scene(mira_scene, scene_id="mira")

    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)

    print("Two scenes, one stage. Aldric has a secret; pressure him to unlock act 2.")
    print("  @aldric <message>     — talk to the innkeeper")
    print("  @mira <message>       — talk to the merchant")
    print("  !fire_at_docks        — send a game event (triggers Mira's checkpoint)")
    print("  quit                  — exit\n")

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
                elif msg == "!fire_at_docks":
                    stage.queue_game_event(GameEvent(name="fire_at_docks", info={}))
                    print("[game event queued: fire_at_docks]")
                elif msg.startswith("@aldric "):
                    await stage.on_user_input(msg[8:], scene_id="aldric")
                elif msg.startswith("@mira "):
                    await stage.on_user_input(msg[6:], scene_id="mira")
                else:
                    print("Use '@aldric <message>' or '@mira <message>'")
        finally:
            await runtime.stop()
    await consumer


asyncio.run(main())
