"""
Example 1: Actor + Stage
========================
The minimal setup — one actor, one stage, no scene, no ticking.
`on_user_input` returns the reply directly as a string.
"""

import asyncio

from digital_actor.actor import DigitalActor
from digital_actor.data_models import PromptInfo
from digital_actor.stage import SingleActorStage
from dotenv import load_dotenv

load_dotenv()


class TavernKeeper(DigitalActor):
    def get_next_line_prompt_info(self) -> PromptInfo:
        return PromptInfo(
            prompt=(
                "You are Greta, a gruff but warm tavern keeper. "
                "You run the Rusty Flagon inn. Keep replies brief.\n\n"
                f"{self.history.to_string()}"
            ),
            input_args={},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise this tavern conversation briefly:\n{dialogue}", input_args={})


async def main() -> None:
    actor = TavernKeeper("keeper", "Greta", "Runs the local tavern.", character_info=None)
    stage = SingleActorStage(actor, llm_model="cerebras/qwen-3-235b-a22b-instruct-2507")

    print("Chat with Greta. Type 'quit' to exit.\n")
    while True:
        msg = input("> ").strip()
        if not msg:
            continue
        if msg.lower() == "quit":
            break
        reply = await stage.on_user_input(msg)
        print(f"Greta: {reply}\n")


asyncio.run(main())
