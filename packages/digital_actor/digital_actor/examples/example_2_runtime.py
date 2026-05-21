"""
Example 2: Actor + Stage + Runtime
===================================
Adds a Runtime so the stage ticks at a fixed rate. The Runtime is generic —
it just calls subscribed async callbacks with the elapsed time on every tick.

A secondary callback prints the tick count every 5 seconds so you can see
the clock running. Try pausing and resuming to see it stop and restart.

Commands: pause | resume | quit | (anything else chats with Greta)
"""

import asyncio

from digital_actor.actor import DigitalActor
from digital_actor.data_models import PromptInfo
from digital_actor.runtime import Runtime
from digital_actor.stage import SingleActorStage
from dotenv import load_dotenv

load_dotenv()

TICK_RATE = 20  # ticks per second
REPORT_EVERY = TICK_RATE * 5  # print tick count every 5 seconds


class TavernKeeper(DigitalActor):
    def get_next_line_prompt_info(self) -> PromptInfo:
        return PromptInfo(
            prompt=(
                f"You are Greta, a gruff but warm tavern keeper. Keep replies brief.\n\n{self.history.to_string()}"
            ),
            input_args={},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise:\n{dialogue}", input_args={})


tick_count = 0


async def report_ticks(elapsed: float) -> None:
    global tick_count
    tick_count += 1
    if tick_count % REPORT_EVERY == 0:
        print(f"\n[runtime: tick {tick_count}, elapsed {elapsed:.1f}s]")


async def main() -> None:
    actor = TavernKeeper("keeper", "Greta", "Runs the local tavern.", character_info=None)
    stage = SingleActorStage(actor, llm_model="cerebras/qwen-3-235b-a22b-instruct-2507")

    runtime = Runtime()
    runtime.subscribe(report_ticks)  # our counter runs on every tick
    runtime.subscribe(stage.step)  # stage.step(elapsed_time) is the standard tick entry point
    runtime.start(tick_rate=TICK_RATE)

    print(f"Runtime started at {TICK_RATE} ticks/sec. Commands: pause | resume | quit\n")

    try:
        while True:
            msg = await asyncio.to_thread(input, "> ")
            msg = msg.strip()
            if not msg:
                continue
            if msg == "quit":
                break
            elif msg == "pause":
                runtime.pause()
                print("[simulation paused — ticks stop, elapsed time freezes]")
            elif msg == "resume":
                runtime.resume()
                print("[simulation resumed]")
            else:
                reply = await stage.on_user_input(msg)
                print(f"Greta: {reply}\n")
    finally:
        await runtime.stop()
        print(f"[runtime stopped after {tick_count} ticks]")


asyncio.run(main())
