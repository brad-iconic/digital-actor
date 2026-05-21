"""Actor classes — the character brain layer of the digital_actor framework."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from digital_actor.data_models import PromptInfo
from digital_actor.dialogue import PLAYER_ROLE_NAME, DialogueLine
from digital_actor.history import DialogueHistory
from digital_actor.stage_context import stage_context
from llm_lib import LLMClient
from timer_stack import hierarchical_timer
from tts_lib import TTSClient

logger = logging.getLogger(__name__)


class BaseDigitalActor(ABC):
    """Abstract base for all actor types.

    An actor holds a character identity, owns a :class:`~digital_actor.history.DialogueHistory`,
    and knows how to construct prompts for the LLM and deliver synthesised
    audio via the TTS client. Concrete actors subclass either
    :class:`DigitalActor` (direct player-input mode) or
    :class:`SceneDigitalActor` (scene-managed mode).

    All LLM calls and audio delivery are routed through
    :data:`~digital_actor.stage_context.stage_context` so the actor is
    decoupled from the stage implementation.

    Attributes:
        actor_id: Unique identifier for this actor instance.
        name: Display name used as the speaker label in dialogue lines.
        description: Short character description available to the stage.
        history: The actor's conversation history.
    """

    def __init__(
        self,
        actor_id: str,
        name: str,
        description: str,
        character_info: Any,
    ) -> None:
        """
        Args:
            actor_id: Unique string identifier for this actor.
            name: Character name used as the speaker label in dialogue.
            description: Short free-text description of the character.
            character_info: Arbitrary character data (game-specific config,
                stats, etc.). Available via :attr:`character_info`.
        """
        self.actor_id = actor_id
        self.name = name
        self.description = description
        self._character_info = character_info
        self.history = DialogueHistory(self)

    @property
    def character_info(self) -> Any:
        """Arbitrary character configuration passed at construction time."""
        return self._character_info

    def get_llm_client(self) -> LLMClient:
        return stage_context.llm_client

    def get_tts_client(self) -> TTSClient:
        return stage_context.tts_client

    async def run_tts(self, dialogue_line: DialogueLine) -> None:
        """Synthesise audio for ``dialogue_line`` and deliver it via the stage.

        Streams PCM chunks from the TTS client through
        :meth:`~digital_actor.stage_context.StageContext.deliver_speech`.
        The first chunk carries ``user_input_ack=True`` and the sample rate so
        the game client can initialise its audio pipeline. A final empty chunk
        with ``is_final_audio=True`` signals end-of-speech.

        When no TTS client is configured on the stage, a single empty chunk is
        delivered immediately so the game client receives the ``user_input_ack``
        signal.

        Updates :attr:`~digital_actor.dialogue.DialogueLine.audio_duration_sec`
        on ``dialogue_line`` as audio is streamed.

        Args:
            dialogue_line: The line whose :attr:`~digital_actor.dialogue.DialogueLine.text`
                is synthesised.
        """
        first_audio = True
        tts = self.get_tts_client()
        with hierarchical_timer("deliver_tts"):
            if tts is not None:
                async for chunk in tts.generate_audio(dialogue_line.text):
                    stage_context.deliver_speech(
                        dialogue_line,
                        chunk,
                        interruptible=True,
                        user_input_ack=first_audio,
                        tts_sample_rate=tts.sample_rate if first_audio else 0,
                    )
                    first_audio = False
                    if chunk:
                        chunk_dur = len(chunk) / max(tts.sample_rate, 1) / 2
                        dialogue_line.audio_duration_sec += chunk_dur
                stage_context.deliver_speech(
                    dialogue_line,
                    b"",
                    interruptible=True,
                    is_final_audio=True,
                    tts_sample_rate=tts.sample_rate,
                )
            else:
                stage_context.deliver_speech(
                    dialogue_line,
                    b"",
                    interruptible=True,
                    user_input_ack=True,
                    is_final_audio=True,
                    tts_sample_rate=0,
                )

    @abstractmethod
    async def tick(self) -> None:
        """Called on each runtime tick. Override for time-driven behaviour."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the actor's mutable state for a new scene or session."""

    @abstractmethod
    def get_summary_prompt_info(self, dialogue: str) -> PromptInfo:
        """Return the :class:`~digital_actor.data_models.PromptInfo` for condensing dialogue history.

        Called by :meth:`~digital_actor.history.DialogueHistory.summarize` when
        the history exceeds its summarisation threshold.

        Args:
            dialogue: The conversation excerpt to summarise, as a formatted
                multi-line string.

        Returns:
            A :class:`~digital_actor.data_models.PromptInfo` whose
            :attr:`~digital_actor.data_models.PromptInfo.prompt` asks the LLM
            to summarise ``dialogue``.
        """


class DigitalActor(BaseDigitalActor):
    """Actor that responds directly to player input without scene management.

    Use with :class:`~digital_actor.stage.SingleActorStage` or
    :class:`~digital_actor.stage.MultiActorStage` for the minimal setup where
    each player message immediately triggers one LLM response.

    Subclasses must implement :meth:`get_next_line_prompt_info` and
    :meth:`get_summary_prompt_info`.
    """

    async def on_user_input(self, message: str, emotions: list[str] | None = None) -> None:
        """Process a player message: record it, generate a response, and run TTS.

        Args:
            message: Raw player input text.
            emotions: Optional list of detected player emotion tags.
        """
        self.history.add_message(PLAYER_ROLE_NAME, message)
        dialogue_line = await self.generate_next_text(emotions)
        await self.run_tts(dialogue_line)
        await self.history.summarize_if_needed()

    async def tick(self) -> None:
        pass

    async def generate_next_text(self, emotions: list[str] | None = None) -> DialogueLine:
        """Generate the actor's next line via the LLM and append it to history.

        Calls :meth:`get_next_line_prompt_info`, sends the prompt to the LLM,
        appends the response to history, and delivers the text via
        :meth:`~digital_actor.stage_context.StageContext.deliver_text`.

        Args:
            emotions: Optional emotion tags from the player turn.

        Returns:
            The newly generated and recorded :class:`~digital_actor.dialogue.DialogueLine`.
        """
        with hierarchical_timer("generate_next_line"):
            prompt_info = self.get_next_line_prompt_info()
            response = await stage_context.llm_acomplete(prompt_info, obs_name="generate_next_line")
        dialogue_line = self.history.add_message(self.name, response)
        # TODO(N1): tts_lib (external dep) doesn't yet expose the emotion +
        # intensity selected for the reference clip; once it does, plumb those
        # values here instead of relying on parsed tags.
        emotion = dialogue_line.tags[0] if dialogue_line.tags else None
        intensity = dialogue_line.tags[1] if len(dialogue_line.tags) > 1 else None
        stage_context.deliver_text(
            dialogue_line, interruptible=True, emotion=emotion, intensity=intensity
        )
        return dialogue_line

    def reset(self) -> None:
        self.history.reset()

    @abstractmethod
    def get_next_line_prompt_info(self) -> PromptInfo:
        """Return the :class:`~digital_actor.data_models.PromptInfo` for the next dialogue line.

        Called by :meth:`generate_next_text` before every LLM call. Typically
        includes the rendered system prompt, character description, and the
        full :meth:`~digital_actor.history.DialogueHistory.to_string` output.

        Returns:
            A :class:`~digital_actor.data_models.PromptInfo` ready to send to
            the LLM.
        """


class SceneDigitalActor(BaseDigitalActor):
    """Actor managed by a :class:`~digital_actor.scene.SingleActorScene`.

    Extends :class:`BaseDigitalActor` with scene-aware prompt flags
    (``is_idle``, ``is_interrupt``, ``is_followup``) and tracks when the actor
    last finished speaking so the scene can schedule idle and followup
    responses.

    Subclasses must implement :meth:`get_next_line_prompt_info` and
    :meth:`get_summary_prompt_info`.

    Attributes:
        speak_end_elapsed: Stage elapsed time when the actor last finished
            speaking, or ``None`` if the actor has not yet spoken.
    """

    def __init__(
        self,
        actor_id: str,
        name: str,
        description: str,
        character_info: Any,
    ) -> None:
        """
        Args:
            actor_id: Unique string identifier for this actor.
            name: Character name used as the speaker label in dialogue.
            description: Short free-text description of the character.
            character_info: Arbitrary character data (game-specific config,
                stats, etc.).
        """
        super().__init__(actor_id, name, description, character_info)
        self.speak_end_elapsed: float | None = None

    async def tick(self) -> None:
        pass

    def reset(self) -> None:
        self.history.reset()
        self.speak_end_elapsed = None

    async def generate_next_line(
        self,
        emotions: list[str] | None = None,
        is_idle: bool = False,
        is_interrupt: bool = False,
        is_followup: bool = False,
        interrupt_count: int = 0,
    ) -> list[DialogueLine]:
        """Generate the next line, run TTS, and update :attr:`speak_end_elapsed`.

        Args:
            emotions: Optional player emotion tags for the current turn.
            is_idle: ``True`` if the actor is responding due to player
                inactivity.
            is_interrupt: ``True`` if the actor was interrupted by the player.
            is_followup: ``True`` if this is an unprompted followup line.
            interrupt_count: Number of consecutive interrupts in this turn.

        Returns:
            The list of generated :class:`~digital_actor.dialogue.DialogueLine`
            objects added to the actor's history this turn.
        """
        dialogue_line = await self.generate_next_text(
            emotions, is_idle, is_interrupt, is_followup, interrupt_count=interrupt_count
        )
        speech_started_at = stage_context.elapsed_time
        await self.run_tts(dialogue_line)
        self.speak_end_elapsed = speech_started_at + dialogue_line.audio_duration_sec
        return [dialogue_line]

    async def generate_next_text(
        self,
        emotions: list[str] | None = None,
        is_idle: bool = False,
        is_interrupt: bool = False,
        is_followup: bool = False,
        interrupt_count: int = 0,
    ) -> DialogueLine:
        """Generate the actor's next line via the LLM and append it to history.

        Args:
            emotions: Optional player emotion tags.
            is_idle: ``True`` if generating due to player inactivity.
            is_interrupt: ``True`` if the actor was interrupted.
            is_followup: ``True`` if this is an unprompted followup.
            interrupt_count: Consecutive interrupt count for this turn.

        Returns:
            The newly generated and recorded :class:`~digital_actor.dialogue.DialogueLine`.
        """
        with hierarchical_timer("generate_next_line"):
            prompt_info = self.get_next_line_prompt_info(
                is_idle=is_idle,
                is_interrupt=is_interrupt,
                is_followup=is_followup,
                interrupt_count=interrupt_count,
            )
            response = await stage_context.llm_acomplete(prompt_info, obs_name="generate_next_line")
        dialogue_line = self.history.add_message(self.name, response)
        # TODO(N1): same as DigitalActor.generate_next_text — tts_lib needs to
        # expose the chosen reference profile's emotion + intensity before we
        # can carry the authoritative values through.
        emotion = dialogue_line.tags[0] if dialogue_line.tags else None
        intensity = dialogue_line.tags[1] if len(dialogue_line.tags) > 1 else None
        stage_context.deliver_text(
            dialogue_line, interruptible=True, emotion=emotion, intensity=intensity
        )
        return dialogue_line

    @abstractmethod
    def get_next_line_prompt_info(
        self,
        is_idle: bool = False,
        is_interrupt: bool = False,
        is_followup: bool = False,
        interrupt_count: int = 0,
    ) -> PromptInfo:
        """Return the :class:`~digital_actor.data_models.PromptInfo` for the next dialogue line.

        Called by :meth:`generate_next_text` before every LLM call. The scene
        flags allow the implementation to adjust the prompt based on context
        (e.g. add an idle nudge, handle an interrupt gracefully).

        Args:
            is_idle: Actor is initiating due to player inactivity.
            is_interrupt: Player interrupted the actor mid-speech.
            is_followup: Actor is adding an unprompted followup line.
            interrupt_count: Number of consecutive interrupts in this turn.

        Returns:
            A :class:`~digital_actor.data_models.PromptInfo` ready to send to
            the LLM.
        """
