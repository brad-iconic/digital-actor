import re

from app_logging import get_logger
from digital_actor.actor import SceneDigitalActor
from digital_actor.data_models import PromptInfo
from digital_actor.dialogue import PLAYER_ROLE_NAME, DialogueLine
from langfuse_utils import get_prompt

from metahuman_actor.stage_context import stage_context

logger = get_logger(__name__)

_TTS_CUE_RE = re.compile(r"\[[^\]]*\]")


class MetaHumanDigitalActor(SceneDigitalActor):
    def __init__(self, persona: dict) -> None:
        super().__init__(
            actor_id=persona["id"],
            name=persona["display_name"],
            description="A convicted killer with three alternating personalities",
            character_info=None,
        )

    async def run_tts(self, dialogue_line: DialogueLine) -> None:
        stripped = _TTS_CUE_RE.sub("", dialogue_line.text).strip()
        if not stripped:
            return
        await super().run_tts(dialogue_line.model_copy(update={"text": stripped}))

    async def deliver_opening_speech(self, text: str) -> DialogueLine:
        """Deliver a pre-authored opening line via TTS without an LLM call.

        :attr:`speak_end_elapsed` is set by the scene's ``on_audio_finished``
        when the client confirms playback has ended.
        """
        line = self.history.add_message(self.name, text)
        # TODO(N1): emotion + intensity will arrive once tts_lib's
        # reference-profile selector is exposed. For now the opening line ships
        # without expression tags.
        emotion = line.tags[0] if line.tags else None
        intensity = line.tags[1] if len(line.tags) > 1 else None
        stage_context.deliver_text(
            line, interruptible=True, emotion=emotion, intensity=intensity
        )
        await self.run_tts(line)
        return line

    def get_next_line_prompt_info(
        self,
        is_idle: bool = False,
        is_interrupt: bool = False,
        is_followup: bool = False,
        interrupt_count: int = 0,
    ) -> PromptInfo:
        prompt = get_prompt("dialogue/get_next_line")
        previous_scene_wrapper = ""
        if stage_context.scene_data.prev_scene_description:
            previous_scene_wrapper = get_prompt("common/prev_scene_wrapper").compile(
                previous_scene_description=stage_context.scene_data.prev_scene_description
            )
        dialogue_summary_wrapper = ""
        if self.history.summary:
            dialogue_summary_wrapper = get_prompt(
                "common/dialogue_summary_wrapper"
            ).compile(dialogue_summary=self.history.summary)
        interrupt_instruction = ""
        if is_interrupt:
            variant = "multi" if interrupt_count > 2 else "single"
            interrupt_instruction = get_prompt(
                f"dialogue/interrupt_{variant}_instruction"
            ).compile(actor_name=self.name)
        idle_instruction = ""
        if is_idle:
            idle_instruction = get_prompt("dialogue/idle_instruction").compile()

        prompt_input = {
            "scene_back_story": stage_context.scene_data.scene_back_story,
            "character_back_story": stage_context.scene_data.character_back_story,
            "previous_scenes_wrapper": previous_scene_wrapper,
            "scene_description": stage_context.scene_data.scene_description,
            "steer_back_instructions": stage_context.scene_data.steer_back_instruction,
            "scene_supplement": stage_context.scene_data.scene_supplement,
            "actors": ", ".join([self.name, PLAYER_ROLE_NAME]),
            "dialogue": self.history.to_string(include_summary=False),
            "dialogue_summary_wrapper": dialogue_summary_wrapper,
            "interrupt_instruction": interrupt_instruction,
            "idle_instruction": idle_instruction,
        }
        compiled_prompt = prompt.compile(**prompt_input)
        return PromptInfo(
            prompt=compiled_prompt,
            input_args=prompt_input,
            langfuse_prompt=prompt,
        )

    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        prompt_input = {
            "scene_back_story": stage_context.scene_data.scene_back_story,
            "character_back_story": stage_context.scene_data.character_back_story,
            "previous_scenes_description": stage_context.scene_data.prev_scene_description,
            "scene_description": stage_context.scene_data.scene_description,
            "actors": ", ".join([self.name, PLAYER_ROLE_NAME]),
            "dialogue": dialogue,
        }
        state_keys = ["actors", "dialogue"]
        if self.history.summary:
            prompt = get_prompt("summary/update_summary")
            prompt_input["existing_summary"] = self.history.summary
            state_keys.append("existing_summary")
        else:
            prompt = get_prompt("summary/generate_summary")
        compiled = prompt.compile(**prompt_input)
        return PromptInfo(
            prompt=compiled,
            input_args=prompt_input,
            langfuse_prompt=prompt,
        )
