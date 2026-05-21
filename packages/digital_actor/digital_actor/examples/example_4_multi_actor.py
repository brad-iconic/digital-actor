"""
Example 4: MultiActorStage
===========================
Multiple actors on one stage with no scene layer. Each actor responds directly
to player input — no idle, followup, or checkpoints.

Usage:
  @greta <message>   — talk to the tavern keeper
  @brom <message>    — talk to the blacksmith
  quit               — exit
"""

import asyncio

from digital_actor.actor import DigitalActor
from digital_actor.data_models import PromptInfo
from digital_actor.messenger import MessengerType, OutboundPayload
from digital_actor.runtime import Runtime
from digital_actor.stage import MultiActorStage
from dotenv import load_dotenv

load_dotenv()


async def _print_payloads(queue: asyncio.Queue[OutboundPayload | None]) -> None:
    while True:
        payload = await queue.get()
        if payload is None:
            break
        if payload.text:
            print(f"\n{payload.actor_name}: {payload.text}")


class TavernKeeper(DigitalActor):
    def get_next_line_prompt_info(self) -> PromptInfo:
        return PromptInfo(
            prompt=(
                "You are Greta, a gruff but warm tavern keeper at the Rusty Flagon. Keep replies brief.\n\n"
                f"{self.history.to_string()}"
            ),
            input_args={},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise:\n{dialogue}", input_args={})


class Blacksmith(DigitalActor):
    def get_next_line_prompt_info(self) -> PromptInfo:
        return PromptInfo(
            prompt=(
                "You are Brom, a taciturn blacksmith who takes great pride in his craft. Keep replies brief.\n\n"
                f"{self.history.to_string()}"
            ),
            input_args={},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise:\n{dialogue}", input_args={})


async def main() -> None:
    stage = MultiActorStage("cerebras/qwen-3-235b-a22b-instruct-2507", messenger=MessengerType.WEBSOCKET)

    greta = TavernKeeper("greta", "Greta", "Runs the local tavern.", character_info=None)
    brom = Blacksmith("brom", "Brom", "Works the forge.", character_info=None)

    stage.register_actor(greta, actor_id="greta")
    stage.register_actor(brom, actor_id="brom")

    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)

    print("Two NPCs, one stage. Route messages with '@'.")
    print("  @greta <message>   — talk to Greta")
    print("  @brom <message>    — talk to Brom")
    print("  quit               — exit\n")

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
                elif msg.startswith("@greta "):
                    await stage.on_user_input(msg[7:], actor_id="greta")
                elif msg.startswith("@brom "):
                    await stage.on_user_input(msg[6:], actor_id="brom")
                else:
                    print("Use '@greta <message>' or '@brom <message>'")
        finally:
            await runtime.stop()
    await consumer


asyncio.run(main())
