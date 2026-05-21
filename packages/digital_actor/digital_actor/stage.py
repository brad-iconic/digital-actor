"""Stage classes — infrastructure layer holding LLM/TTS clients and event queues."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod

from digital_actor.actor import DigitalActor
from digital_actor.data_models import PromptInfo
from digital_actor.dialogue import PLAYER_ROLE_NAME, DialogueLine
from digital_actor.game_events import GameEvent, GameEventBase
from digital_actor.messenger import (
    Messenger,
    MessengerType,
    NullMessenger,
    OutboundPayload,
    create_messenger,
)
from digital_actor.scene import SingleActorScene
from digital_actor.stage_context import set_stage
from llm_lib import LLMClient, get_llm_client
from tts_lib import TTSClient, get_tts_client

logger = logging.getLogger(__name__)


class _SpeechMetrics:
    """Per-line accumulator for server-side TTS chunk timing.

    Created lazily on the first chunk delivered for a given ``line_id``,
    finalised when ``record_chunk(..., is_final=True)`` is called.
    Captures the wall-clock produce time of each ``deliver_speech``
    invocation so we can distinguish TTS-provider stalls from downstream
    send-side stalls.
    """

    __slots__ = ("line_id", "sample_rate", "_t0", "_t_prev", "_max_gap_ms",
                 "_chunks", "_bytes", "_finalised")

    def __init__(self, *, line_id: str, sample_rate: int) -> None:
        self.line_id = line_id
        self.sample_rate = sample_rate
        self._t0: float | None = None
        self._t_prev: float | None = None
        self._max_gap_ms = 0
        self._chunks = 0
        self._bytes = 0
        self._finalised = False

    def record_chunk(self, *, num_bytes: int, is_final: bool) -> int:
        """Record one chunk arrival; return ms since the previous chunk."""
        now = time.monotonic()
        is_first = self._t0 is None
        if is_first:
            self._t0 = now
            self._t_prev = now
            delta_ms = 0
        else:
            assert self._t_prev is not None
            delta_ms = int(round((now - self._t_prev) * 1000))
            if delta_ms > self._max_gap_ms:
                self._max_gap_ms = delta_ms
            self._t_prev = now
        self._chunks += 1
        self._bytes += num_bytes
        if is_final:
            self._finalised = True
            if is_first:
                # Single-chunk stream: take a second timestamp so elapsed_s
                # captures the full produce window (including the trailing
                # empty sentinel emitted by run_tts) rather than reporting 0.
                self._t_prev = time.monotonic()
            # For non-first final chunks _t_prev is already set to `now`
            # above, which is the correct finalisation timestamp.
        return delta_ms

    def summarize(self) -> dict:
        """Return a dict snapshot for INFO-level logging."""
        t0 = self._t0 or 0.0
        t_last = self._t_prev or t0
        return {
            "line_id": self.line_id,
            "chunks": self._chunks,
            "bytes": self._bytes,
            "sample_rate": self.sample_rate,
            "t_first_ms": 0,  # by construction; kept for log symmetry
            "max_gap_ms": self._max_gap_ms,
            "elapsed_s": round(t_last - t0, 3),
        }


class BaseStage(ABC):
    """Abstract infrastructure layer for the digital_actor framework.

    Holds the :class:`~llm_lib.LLMClient`, optional :class:`~tts_lib.TTSClient`,
    :class:`~digital_actor.messenger.Messenger`, event queues, and elapsed
    time. Exposes :meth:`llm_complete` / :meth:`llm_acomplete` so actors and
    scenes can call the LLM without knowing which client is in use.

    The :meth:`step` method is called by :class:`~digital_actor.runtime.Runtime`
    or a game engine on each tick; it advances elapsed time, drains the inbound
    game event queue, and calls :meth:`tick`.

    All subclasses must implement :meth:`tick`, :meth:`on_game_event`, and
    :meth:`on_user_input`.
    """

    def __init__(
        self,
        llm_model: str,
        tts_provider: str | None = None,
        tts_voice_id: str | None = None,
        tts_model_id: str | None = None,
        messenger: Messenger | MessengerType | None = None,
    ) -> None:
        """
        Args:
            llm_model: Model string for :func:`~llm_lib.get_llm_client`
                (e.g. ``"cerebras/qwen-3-235b-a22b-instruct-2507"``).
            tts_provider: Provider name for :func:`~tts_lib.get_tts_client`
                (e.g. ``"elevenlabs"``). Pass ``None`` to disable TTS.
            tts_voice_id: Voice ID passed to the TTS provider.
            tts_model_id: Model ID passed to the TTS provider; falls back to
                the provider's built-in default when not specified.
            messenger: Outbound message router. Pass a :class:`~digital_actor.messenger.Messenger`
                instance, a :class:`~digital_actor.messenger.MessengerType` string,
                or ``None`` to use :class:`~digital_actor.messenger.NullMessenger`.
        """
        self._llm_client = get_llm_client(llm_model)
        self._tts_client = (
            get_tts_client(tts_provider, voice_id=tts_voice_id, model_id=tts_model_id)
            if tts_provider
            else None
        )
        if messenger is None:
            self._messenger: Messenger = NullMessenger()
        elif isinstance(messenger, MessengerType):
            self._messenger = create_messenger(messenger)
        else:
            self._messenger = messenger
        self._elapsed_time: float = 0.0
        self._game_inbound: asyncio.Queue = asyncio.Queue()
        # Per-line speech metrics, keyed by line_id. Each entry lives from
        # the first audio chunk until is_final_audio=True is recorded.
        self._speech_metrics: dict[str, _SpeechMetrics] = {}
        set_stage(self)

    def _log_llm_prompt(self, obs_name: str, prompt: str) -> None:
        """Log a banner + the full prompt before sending it to the LLM.

        Keeps each call visually self-contained in the log stream so prompts
        for different obs_names (next_line, query_followup, query checkpoints,
        summary…) don't visually blur together. Uses INFO so it appears with
        the default log level; switch to DEBUG if you want to silence it.
        """
        logger.info(
            "─── LLM PROMPT [%s] ───────────────────────────────────────────\n%s\n──────────────────────────────────────────────────────────────",
            obs_name, prompt,
        )

    def _log_llm_response(self, obs_name: str, response: str) -> None:
        """Log the full LLM response paired with its obs_name."""
        logger.info(
            "─── LLM RESPONSE [%s] ─────────────────────────────────────────\n%s\n──────────────────────────────────────────────────────────────",
            obs_name, response,
        )

    def llm_complete(self, prompt_info: PromptInfo, obs_name: str = "completion") -> str:
        """Run a blocking LLM completion from a :class:`~digital_actor.data_models.PromptInfo`.

        Wraps the prompt string and Langfuse metadata into the format expected
        by :meth:`~llm_lib.LLMClient.complete`.

        Args:
            prompt_info: Rendered prompt and tracing metadata.
            obs_name: Langfuse observation label. Defaults to ``"completion"``.

        Returns:
            The model's reply as a plain string.
        """
        self._log_llm_prompt(obs_name, prompt_info.prompt)
        response = self._llm_client.complete(
            [{"role": "user", "content": prompt_info.prompt}],
            obs_name=obs_name,
            langfuse_prompt=prompt_info.langfuse_prompt,
            metadata={"prompt_input": prompt_info.input_args, "prompt_state": prompt_info.langfuse_prompt_state},
        )
        self._log_llm_response(obs_name, response)
        return response

    async def llm_acomplete(self, prompt_info: PromptInfo, obs_name: str = "completion") -> str:
        """Run an async LLM completion from a :class:`~digital_actor.data_models.PromptInfo`.

        Args:
            prompt_info: Rendered prompt and tracing metadata.
            obs_name: Langfuse observation label. Defaults to ``"completion"``.

        Returns:
            The model's reply as a plain string.
        """
        self._log_llm_prompt(obs_name, prompt_info.prompt)
        response = await self._llm_client.acomplete(
            [{"role": "user", "content": prompt_info.prompt}],
            obs_name=obs_name,
            langfuse_prompt=prompt_info.langfuse_prompt,
            metadata={"prompt_input": prompt_info.input_args, "prompt_state": prompt_info.langfuse_prompt_state},
        )
        self._log_llm_response(obs_name, response)
        return response

    @property
    def messenger(self) -> Messenger:
        """The outbound :class:`~digital_actor.messenger.Messenger` for this stage."""
        return self._messenger

    @property
    def llm_client(self) -> LLMClient:
        """The :class:`~llm_lib.LLMClient` instance configured for this stage."""
        return self._llm_client

    @property
    def tts_client(self) -> TTSClient | None:
        """The :class:`~tts_lib.TTSClient`, or ``None`` if TTS is disabled."""
        return self._tts_client

    @property
    def elapsed_time(self) -> float:
        """Simulated elapsed time in seconds, updated on each :meth:`step` call."""
        return self._elapsed_time

    async def step(self, elapsed_time: float) -> None:
        """Advance the stage by one tick.

        Called by :class:`~digital_actor.runtime.Runtime` or a game engine.
        Updates :attr:`elapsed_time`, drains the inbound game event queue via
        :meth:`process_game_inbound`, then calls :meth:`tick`.

        Args:
            elapsed_time: Current elapsed time in seconds from the runtime.
        """
        self._elapsed_time = elapsed_time
        await self.process_game_inbound()
        await self.tick()

    async def process_game_inbound(self) -> None:
        """Drain and process all pending events from the inbound game event queue."""
        while True:
            try:
                event = self._game_inbound.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self.on_game_event(event)

    def queue_game_event(self, event: GameEventBase) -> None:
        """Enqueue an event from the game engine for processing on the next tick.

        Thread-safe. Events are drained by :meth:`process_game_inbound` at the
        start of each :meth:`step` call.

        Args:
            event: A :class:`~digital_actor.game_events.GameEventBase` subclass
                (e.g. :class:`~digital_actor.game_events.GameEvent` or
                :class:`~digital_actor.game_events.PlayerInterruptEvent`).
        """
        self._game_inbound.put_nowait(event)

    def deliver_event(self, event: GameEvent) -> None:
        """Broadcast a :class:`~digital_actor.game_events.GameEvent` via the messenger.

        Args:
            event: The event to deliver to the game client.
        """
        self._messenger.emit_game_event(event)

    def _emit_dialogue(self, payload: OutboundPayload) -> None:
        self.messenger.emit_payload(payload)

    def deliver_text(
        self,
        line: DialogueLine,
        *,
        interruptible: bool = True,
        user_input_ack: bool = False,
        is_final_audio: bool = False,
        tts_sample_rate: int = 0,
        emotion: str | None = None,
        intensity: str | None = None,
    ) -> None:
        """Emit a text-only :class:`~digital_actor.messenger.OutboundPayload` via the messenger.

        Args:
            line: The dialogue line to deliver.
            interruptible: Whether the client may interrupt this line.
            user_input_ack: Signal that the actor has acknowledged the player
                input.
            is_final_audio: ``True`` on the final frame for this line.
            tts_sample_rate: PCM sample rate; non-zero only on the first audio
                frame.
            emotion: Optional emotion tag for the line; surfaced on the
                ``text`` wire frame so the game client can drive non-audio
                expression channels.
            intensity: Optional intensity tag paired with ``emotion``.
        """
        # TODO(N1): wire emotion + intensity through from tts_lib's
        # reference-profile selector once the upstream API exposes them.
        # Today they propagate only when a caller passes them explicitly
        # (e.g. from DialogueLine.tags).
        logger.info(
            "─── ACTOR LINE [%s] emotion=%s intensity=%s line=%s ───────────\n%s\n──────────────────────────────────────────────────────────────",
            line.name,
            emotion or "-",
            intensity or "-",
            line.line_id,
            line.text,
        )
        self._emit_dialogue(
            OutboundPayload(
                actor_name=line.name,
                text=line.text,
                line_id=line.line_id,
                interruptible=interruptible,
                user_input_ack=user_input_ack,
                is_final_audio=is_final_audio,
                tts_sample_rate=tts_sample_rate,
                emotion=emotion,
                intensity=intensity,
            )
        )

    def deliver_speech(
        self,
        line: DialogueLine,
        chunk: bytes,
        *,
        interruptible: bool = True,
        user_input_ack: bool = False,
        is_final_audio: bool = False,
        tts_sample_rate: int = 0,
        emotion: str | None = None,
        intensity: str | None = None,
    ) -> None:
        """Emit an audio :class:`~digital_actor.messenger.OutboundPayload` via the messenger.

        Args:
            line: The dialogue line this audio belongs to.
            chunk: Raw PCM bytes for this frame.
            interruptible: Whether the client may interrupt this line.
            user_input_ack: Signal that the actor has acknowledged the player
                input (set on the first audio frame).
            is_final_audio: ``True`` on the last audio frame for this line.
            tts_sample_rate: PCM sample rate in Hz; non-zero on the first
                frame.
            emotion: Optional emotion tag carried for parity with
                :meth:`deliver_text`. Audio frames currently don't surface this
                on the wire — provided so callers can pass a single payload
                shape per line if it simplifies their code.
            intensity: Optional intensity tag; see ``emotion``.
        """
        # TODO(N1): see deliver_text — same upstream tts_lib dependency.
        # First chunk for this line: sample_rate is non-zero by convention.
        metrics = self._speech_metrics.get(line.line_id)
        if metrics is None and tts_sample_rate > 0:
            metrics = _SpeechMetrics(
                line_id=line.line_id, sample_rate=tts_sample_rate
            )
            self._speech_metrics[line.line_id] = metrics
            logger.info(
                ">>> deliver_speech start: actor=%s line=%s sample_rate=%d bytes=%d",
                line.name, line.line_id, tts_sample_rate, len(chunk),
            )

        if metrics is not None:
            delta_ms = metrics.record_chunk(
                num_bytes=len(chunk), is_final=is_final_audio
            )
            logger.debug(
                "speech chunk #%d line=%s bytes=%d +%dms_produced",
                metrics._chunks, line.line_id, len(chunk), delta_ms,
            )

        if is_final_audio:
            if metrics is not None:
                s = metrics.summarize()
                logger.info(
                    "speech summary line=%s chunks=%d bytes=%d sr=%d "
                    "max_gap=%dms elapsed=%.3fs",
                    s["line_id"], s["chunks"], s["bytes"], s["sample_rate"],
                    s["max_gap_ms"], s["elapsed_s"],
                )
                del self._speech_metrics[line.line_id]
            else:
                # Defensive: a stage with no TTS configured emits a single
                # empty final chunk without a prior first-chunk event. Log
                # the close so the line is still visible in the stream.
                logger.info(
                    ">>> deliver_speech final (no audio): actor=%s line=%s",
                    line.name, line.line_id,
                )

        self._emit_dialogue(
            OutboundPayload(
                actor_name=line.name,
                audio_chunk=chunk,
                line_id=line.line_id,
                interruptible=interruptible,
                user_input_ack=user_input_ack,
                is_final_audio=is_final_audio,
                tts_sample_rate=tts_sample_rate,
                emotion=emotion,
                intensity=intensity,
            )
        )

    @abstractmethod
    async def tick(self) -> None:
        """Per-tick logic. Called by :meth:`step` after draining the event queue."""
        ...

    @abstractmethod
    async def on_game_event(self, event: GameEventBase) -> None:
        """Handle one game event dequeued from the inbound queue."""
        ...

    @abstractmethod
    async def on_user_input(self, message: str) -> None:
        """Handle a player message."""
        ...

    async def on_audio_finished(self, line_id: str) -> None:
        """Handle confirmation from the game client that ``line_id``'s audio has finished playing.

        Default no-op. Stages with scenes (e.g. :class:`SingleSceneStage`,
        :class:`MultiSceneStage`) override to forward to their scenes so the
        followup deadline can be anchored to the real end of playback rather
        than the server-side streaming estimate.
        """

    async def await_idle(self) -> None:
        """Block until no response pipeline is in flight.

        Default no-op. Stages that own scenes with serialised response
        pipelines override to wait on their scene's response lock so that
        lifecycle code (e.g. ``reset`` on disconnect) does not clear state
        out from under a running response.
        """

    def reset(self) -> None:
        """Reset elapsed time. Subclasses should call ``super().reset()`` and reset their actors/scenes."""
        self._elapsed_time = 0.0
        self._speech_metrics.clear()


class SingleActorStage(BaseStage):
    """Minimal stage for one :class:`~digital_actor.actor.DigitalActor` with no scene layer.

    The simplest setup — player input is forwarded directly to the actor and
    the reply is returned as a string from :meth:`on_user_input`. No idle,
    followup, or checkpoint handling.

    Example:
        ```python
        actor = MyActor("id", "Name", "Description", character_info=None)
        stage = SingleActorStage(actor, llm_model="cerebras/qwen-3-235b-a22b-instruct-2507")
        set_stage(stage)

        reply = await stage.on_user_input("Hello!")
        ```

    Pass ``messenger`` to route output through a network connection instead of
    returning it directly (e.g. ``messenger=MessengerType.WEBSOCKET``).
    """

    def __init__(
        self,
        actor: DigitalActor,
        llm_model: str,
        tts_provider: str | None = None,
        tts_voice_id: str | None = None,
        tts_model_id: str | None = None,
        messenger: Messenger | MessengerType | None = None,
    ) -> None:
        """
        Args:
            actor: The :class:`~digital_actor.actor.DigitalActor` to drive.
            llm_model: Model string for :func:`~llm_lib.get_llm_client`.
            tts_provider: TTS provider name, or ``None`` to disable TTS.
            tts_voice_id: Voice ID passed to the TTS provider.
            tts_model_id: Model ID passed to the TTS provider.
            messenger: Outbound messenger, or ``None`` for
                :class:`~digital_actor.messenger.NullMessenger`.
        """
        super().__init__(llm_model, tts_provider, tts_voice_id, tts_model_id, messenger)
        self._actor = actor

    async def on_user_input(self, message: str) -> str:  # type: ignore[override]
        """Drive the actor with ``message`` and return its text response.

        Args:
            message: The player's input text.

        Returns:
            The actor's generated dialogue text as a plain string.
        """
        self._actor.history.add_message(PLAYER_ROLE_NAME, message)
        line = await self._actor.generate_next_text()
        await self._actor.run_tts(line)
        await self._actor.history.summarize_if_needed()
        return line.text

    async def tick(self) -> None:
        pass

    async def on_game_event(self, event: GameEventBase) -> None:
        pass

    def reset(self) -> None:
        super().reset()
        self._actor.reset()


class MultiActorStage(BaseStage):
    """Stage for multiple :class:`~digital_actor.actor.DigitalActor` instances with no scene layer.

    Actors are registered by ID via :meth:`register_actor`. Player input can
    be directed to a specific actor (by ``actor_id``) or broadcast to all
    actors. No idle, followup, or checkpoint handling — use
    :class:`MultiSceneStage` for those features.
    """

    def __init__(
        self,
        llm_model: str,
        tts_provider: str | None = None,
        tts_voice_id: str | None = None,
        tts_model_id: str | None = None,
        messenger: Messenger | MessengerType | None = None,
    ) -> None:
        """
        Args:
            llm_model: Model string for :func:`~llm_lib.get_llm_client`.
            tts_provider: TTS provider name, or ``None`` to disable TTS.
            tts_voice_id: Voice ID passed to the TTS provider.
            tts_model_id: Model ID passed to the TTS provider.
            messenger: Outbound messenger, or ``None`` for
                :class:`~digital_actor.messenger.NullMessenger`.
        """
        super().__init__(llm_model, tts_provider, tts_voice_id, tts_model_id, messenger)
        self._actors: dict[str, DigitalActor] = {}

    def register_actor(self, actor: DigitalActor, actor_id: str) -> None:
        """Register ``actor`` under ``actor_id`` so it can receive targeted input.

        Args:
            actor: The actor to register.
            actor_id: Key used with :meth:`on_user_input`'s ``actor_id``
                parameter.
        """
        self._actors[actor_id] = actor

    def _emit_dialogue(self, payload: OutboundPayload) -> None:
        self.messenger.emit_payload_for_actor(payload)

    async def tick(self) -> None:
        for actor in self._actors.values():
            await actor.tick()

    async def on_game_event(self, event: GameEventBase) -> None:
        pass

    async def on_user_input(
        self,
        message: str,
        actor_id: str | None = None,
        emotions: list[str] | None = None,
    ) -> None:
        """Forward a player message to the specified actor or all actors.

        Args:
            message: The player's input text.
            actor_id: If provided, send to this actor only; otherwise
                broadcast to all registered actors.
            emotions: Optional player emotion tags.
        """
        if actor_id is None:
            for actor in self._actors.values():
                await actor.on_user_input(message, emotions)
        else:
            actor = self._actors.get(actor_id)
            if actor is not None:
                await actor.on_user_input(message, emotions)

    def reset(self) -> None:
        super().reset()
        for actor in self._actors.values():
            actor.reset()


class SingleSceneStage(BaseStage):
    """Stage for a single :class:`~digital_actor.scene.SingleActorScene`.

    Manages one scene with the full scene feature set (idle, followup,
    checkpoints). Register the scene via :meth:`register_scene` after
    construction.
    """

    def __init__(
        self,
        llm_model: str,
        tts_provider: str | None = None,
        tts_voice_id: str | None = None,
        tts_model_id: str | None = None,
        messenger: Messenger | MessengerType | None = None,
    ) -> None:
        """
        Args:
            llm_model: Model string for :func:`~llm_lib.get_llm_client`.
            tts_provider: TTS provider name, or ``None`` to disable TTS.
            tts_voice_id: Voice ID passed to the TTS provider.
            tts_model_id: Model ID passed to the TTS provider.
            messenger: Outbound messenger, or ``None`` for
                :class:`~digital_actor.messenger.NullMessenger`.
        """
        super().__init__(llm_model, tts_provider, tts_voice_id, tts_model_id, messenger)
        self._scene: SingleActorScene | None = None

    def register_scene(self, scene: SingleActorScene) -> None:
        """Set the active scene for this stage.

        Args:
            scene: The :class:`~digital_actor.scene.SingleActorScene` to manage.
        """
        self._scene = scene

    async def tick(self) -> None:
        if self._scene is None:
            return
        await self._scene.tick()

    async def on_game_event(self, event: GameEvent) -> None:
        if self._scene is None:
            return
        await self._scene.on_game_event(event.name, event.info)

    async def on_user_input(self, message: str) -> None:
        if self._scene is None:
            return
        await self._scene.on_user_input(message)

    async def on_audio_finished(self, line_id: str) -> None:
        if self._scene is not None:
            await self._scene.on_audio_finished(line_id)

    async def await_idle(self) -> None:
        if self._scene is not None:
            await self._scene.await_idle()

    def reset(self) -> None:
        super().reset()
        if self._scene is not None:
            self._scene.reset()


class MultiSceneStage(BaseStage):
    """Stage that manages multiple :class:`~digital_actor.scene.SingleActorScene` instances.

    Scenes are registered by ID via :meth:`register_scene`. Player input and
    game events can be directed to a specific scene (by ``scene_id``) or
    broadcast to all scenes.
    """

    def __init__(
        self,
        llm_model: str,
        tts_provider: str | None = None,
        tts_voice_id: str | None = None,
        tts_model_id: str | None = None,
        messenger: Messenger | MessengerType | None = None,
    ) -> None:
        """
        Args:
            llm_model: Model string for :func:`~llm_lib.get_llm_client`.
            tts_provider: TTS provider name, or ``None`` to disable TTS.
            tts_voice_id: Voice ID passed to the TTS provider.
            tts_model_id: Model ID passed to the TTS provider.
            messenger: Outbound messenger, or ``None`` for
                :class:`~digital_actor.messenger.NullMessenger`.
        """
        super().__init__(llm_model, tts_provider, tts_voice_id, tts_model_id, messenger)
        self._scenes: dict[str, SingleActorScene] = {}

    def register_scene(self, scene: SingleActorScene, scene_id: str) -> None:
        """Register ``scene`` under ``scene_id``.

        Args:
            scene: The scene to register.
            scene_id: Key used with ``on_user_input``'s ``scene_id``
                parameter.
        """
        self._scenes[scene_id] = scene

    def _emit_dialogue(self, payload: OutboundPayload) -> None:
        self.messenger.emit_payload_for_actor(payload)

    async def tick(self) -> None:
        for scene in self._scenes.values():
            await scene.tick()

    async def on_game_event(self, event: GameEvent, scene_id: str | None = None) -> None:
        """Forward ``event`` to the specified scene or all scenes.

        Args:
            event: The :class:`~digital_actor.game_events.GameEvent` to handle.
            scene_id: If provided, send to this scene only; otherwise
                broadcast to all registered scenes.
        """
        if scene_id is None:
            for scene in self._scenes.values():
                await scene.on_game_event(event.name, event.info)
        else:
            scene = self._scenes.get(scene_id)
            if scene is not None:
                await scene.on_game_event(event.name, event.info)

    async def on_user_input(
        self,
        message: str,
        scene_id: str | None = None,
        emotions: list[str] | None = None,
    ) -> None:
        """Forward a player message to the specified scene or all scenes.

        Args:
            message: The player's input text.
            scene_id: If provided, send to this scene only; otherwise
                broadcast to all registered scenes.
            emotions: Optional player emotion tags.
        """
        if scene_id is None:
            for scene in self._scenes.values():
                await scene.on_user_input(message, emotions)
        else:
            scene = self._scenes.get(scene_id)
            if scene is not None:
                await scene.on_user_input(message, emotions)

    async def on_audio_finished(self, line_id: str) -> None:
        for scene in self._scenes.values():
            await scene.on_audio_finished(line_id)

    async def await_idle(self) -> None:
        for scene in self._scenes.values():
            await scene.await_idle()

    def reset(self) -> None:
        super().reset()
        for scene in self._scenes.values():
            scene.reset()
