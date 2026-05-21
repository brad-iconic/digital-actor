# digital-actor

Framework for AI-driven NPC dialogue systems. Handles LLM-based character responses, TTS audio generation, idle/followup behavior, story checkpoints, and multi-actor/multi-scene management.

## Installation

```bash
pip install digital-actor --index-url <INTERNAL_PYPI_URL>
```

```bash
uv add digital-actor --index <INTERNAL_PYPI_URL>
```

This installs all workspace dependencies (`llm_lib`, `tts_lib`, `timer_stack`, `app-logging`, `langfuse-utils`). Install extras for your chosen LLM and TTS providers separately (see those packages' READMEs).

## Architecture

Four composable layers — use only what you need:

| Layer | Class | Adds |
|-------|-------|------|
| Actor + Stage | `DigitalActor` + `SingleActorStage` | Direct LLM responses to user input |
| + Runtime | `Runtime` | Fixed-rate tick loop for idle/followup behavior |
| + Scene | `SingleActorScene` | Idle timeouts, followups, interrupts, story checkpoints |
| Multi-actor/scene | `MultiActorStage` / `MultiSceneStage` | Multiple characters or scene transitions |

## Quick start

```python
import asyncio
from digital_actor.actor import DigitalActor
from digital_actor.data_models import PromptInfo
from digital_actor.stage import SingleActorStage
from dotenv import load_dotenv

load_dotenv()

class MyCharacter(DigitalActor):
    def get_next_line_prompt_info(self) -> PromptInfo:
        return PromptInfo(
            prompt=f"You are Aria, a helpful guide. Keep replies brief.\n\n{self.history.to_string()}",
            input_args={},
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        return PromptInfo(prompt=f"Summarise this conversation:\n{dialogue}", input_args={})

async def main():
    actor = MyCharacter("aria", "Aria", "A helpful guide.", character_info=None)
    stage = SingleActorStage(actor, llm_model="cerebras/qwen-3-235b-a22b-instruct-2507")

    reply = await stage.on_user_input("Hello!")
    print(f"Aria: {reply}")

asyncio.run(main())
```

See `digital_actor/examples/` for progressively more complete examples (Runtime, Scene, multi-actor, multi-scene).

## Environment variables

Inherited from `llm_lib` and `tts_lib` — set API keys for whichever LLM and TTS providers you use. Langfuse tracing is configured via `langfuse-utils`.
