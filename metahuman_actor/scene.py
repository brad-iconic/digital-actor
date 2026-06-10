from __future__ import annotations

import re

from app_logging import get_logger
from digital_actor.data_models import PromptInfo
from digital_actor.dialogue import NARRATOR_ROLE_NAME, PLAYER_ROLE_NAME, DialogueLine
from digital_actor.scene import SingleActorScene
from digital_actor.stage_context import stage_context
from langfuse_utils import get_prompt, langfuse_observation

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.data_models import MetaHumanSceneData

logger = get_logger(__name__)

# Writer's convention in opening_speech prompts: line starts with "[Name]: ".
# Vocal cues like "[whisper]" never have a trailing colon, so this only
# strips speaker tags.
_SPEAKER_TAG_PREFIX = re.compile(r"^\s*\[[^\]]+\]\s*:\s*")


class MetaHumanSingleActorScene(SingleActorScene):
    # Narrow the inherited attribute types so MetaHumanSceneData / MetaHumanDigitalActor
    # extras (opening_speech, deliver_opening_speech, …) resolve.
    scene_data: MetaHumanSceneData
    actor: MetaHumanDigitalActor

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._turn: int = 0
        self._opening_delivered: bool = False

    async def deliver_opening_speech(self) -> None:
        """Play the static opening_speech text via TTS, once per scene reset."""
        if self._opening_delivered:
            return
        text = self.scene_data.opening_speech or ""
        text = _SPEAKER_TAG_PREFIX.sub("", text).strip()
        if not text:
            logger.warning(
                "opening_speech prompt is empty; cannot deliver static opening"
            )
            return
        # Hold the same response lock that generate_actor_response uses so a
        # user_input arriving mid-opening queues behind the opening line
        # instead of interleaving its TTS chunks on the outbound queue.
        async with self._response_lock:
            self._opening_delivered = True
            speech_started_at = stage_context.elapsed_time
            line = await self.actor.deliver_opening_speech(text)
            # The game-driven client does not send audio_finished, so
            # on_audio_finished never fires to set speak_end_elapsed for the
            # opening line. Anchor the idle/followup clock on the server-side
            # playback estimate (same approach as generate_actor_response);
            # without this, tick() never starts counting idle after the opening
            # line and the actor falls silent. A later audio_finished (if any
            # client sends one) still overrides this via on_audio_finished.
            self.actor.speak_end_elapsed = (
                speech_started_at
                + line.audio_duration_sec
                + self.playback_end_buffer_sec
            )

    async def generate_actor_response(
        self,
        message: str | None,
        emotions: list[str] | None = None,
        is_idle: bool = False,
        is_followup: bool = False,
    ) -> list[DialogueLine]:
        if is_idle:
            obs_name = "idle"
        elif is_followup:
            obs_name = "followup"
        else:
            self._turn += 1
            obs_name = f"turn_{self._turn}"
        with langfuse_observation(name=obs_name, as_type="span", input=message) as span:
            lines = await super().generate_actor_response(
                message, emotions, is_idle, is_followup
            )
            if span is not None:
                span.update(output="\n".join(line.text for line in lines))
        return lines

    def reset(self) -> None:
        super().reset()
        self.actor.reset()
        self._turn = 0
        self._opening_delivered = False

    def get_query_followup_prompt_info(self) -> PromptInfo:
        history = self.actor.history
        last = history.last_actor_line()
        if last is None:
            raise RuntimeError("query_followup invoked before the actor has spoken")
        last_line, last_idx = last
        dialogue = "\n\n".join(
            f"{line.name}: {line.text}"
            for line in history.messages[history.summary_idx : last_idx + 1]
            if line.name != NARRATOR_ROLE_NAME
        )
        dialogue_summary_wrapper = ""
        if history.summary:
            dialogue_summary_wrapper = get_prompt(
                "common/dialogue_summary_wrapper"
            ).compile(dialogue_summary=history.summary)
        prompt = get_prompt("query/query_followup")
        prompt_input = {
            "scene_description": self.scene_data.scene_description,
            "actors": ", ".join([self.actor.name, PLAYER_ROLE_NAME]),
            "dialogue": dialogue,
            "dialogue_summary_wrapper": dialogue_summary_wrapper,
            "last_line": f"{last_line.name}: {last_line.text}",
        }
        compiled = prompt.compile(**prompt_input)
        return PromptInfo(
            prompt=compiled,
            input_args=prompt_input,
            langfuse_prompt=prompt,
        )

    def get_query_prompt_info(self, text: str, question: str) -> PromptInfo:
        prompt = get_prompt("query/query_statement")
        prompt_input = {
            "scene_back_story": self.scene_data.scene_back_story,
            "dialogue": text,
            "statement": question,
        }
        compiled = prompt.compile(**prompt_input)
        return PromptInfo(
            prompt=compiled,
            input_args=prompt_input,
            langfuse_prompt=prompt,
        )

    def is_finished(self) -> bool:
        return self.scene_data.checkpoints.is_finished()
