"""Scene layer — interaction management on top of an actor."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from digital_actor.actor import SceneDigitalActor
from digital_actor.checkpoints import CheckpointResult, EventCheckpoint, QueryCheckpoint
from digital_actor.data_models import PromptInfo, SceneData
from digital_actor.dialogue import (
    ELLIPSIS,
    NARRATOR_ROLE_NAME,
    PLAYER_ROLE_NAME,
    CheckpointTarget,
    DialogueLine,
)
from digital_actor.game_events import GameEvent
from digital_actor.stage_context import stage_context
from timer_stack import hierarchical_timer, print_timer_tree

logger = logging.getLogger(__name__)


class BaseScene(ABC):
    """Abstract interface for scene objects managed by a stage."""

    @abstractmethod
    async def on_user_input(self, message: str, emotions: list[str] | None = None) -> None:
        """Handle a player message."""
        ...

    @abstractmethod
    async def tick(self) -> None:
        """Called on each runtime tick to handle time-driven behaviour."""
        ...

    @abstractmethod
    async def on_game_event(self, name: str, event_info: dict[str, str]) -> None:
        """Handle a named game event from the game engine."""
        ...

    @abstractmethod
    async def on_interrupt(self, line_id: str, elapsed_seconds: float) -> None:
        """Handle a player interrupt of the actor's current line."""
        ...

    async def on_audio_finished(self, line_id: str) -> None:
        """Handle confirmation that the client finished playing ``line_id``.

        Default no-op. Override in scenes that anchor follow-up timing to the
        real end of audio playback rather than a server-side estimate.
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset all mutable scene state."""
        ...


class SingleActorScene(BaseScene):
    """Interaction manager for a single :class:`~digital_actor.actor.SceneDigitalActor`.

    Wraps one actor with the full suite of scene behaviours:

    - **Player input**: records and responds via the actor.
    - **Idle timeout**: generates an unprompted actor line when the player has
      been silent for ``idle_timeout`` seconds after the actor last spoke.
    - **Followup**: schedules a short actor followup after each response when
      the LLM query indicates one is warranted.
    - **Interrupt handling**: truncates the interrupted line in the history to
      the approximate playback position.
    - **Checkpoints**: evaluates active :class:`~digital_actor.checkpoints.QueryCheckpoint`
      and :class:`~digital_actor.checkpoints.EventCheckpoint` nodes after each
      turn and fires callbacks or injects narrator messages.

    Subclasses must implement :meth:`get_query_followup_prompt_info` and
    :meth:`get_query_prompt_info`.

    Attributes:
        actor: The :class:`~digital_actor.actor.SceneDigitalActor` managed by
            this scene.
        scene_data: Scene configuration (checkpoints, opening lines, etc.).
    """

    def __init__(
        self,
        actor: SceneDigitalActor,
        scene_data: SceneData,
        idle_timeout: float | None = 30.0,
        default_followup_timeout: float | None = 8.0,
        query_followup_timeout: float | None = 2.0,
        actor_query_failure_timeout: float | None = 6.0,
        playback_end_buffer_sec: float = 0.5,
    ):
        """
        Args:
            actor: The scene actor.
            scene_data: Scene configuration.
            idle_timeout: Seconds after the actor last spoke before an idle
                line is generated. ``None`` disables idle lines.
            default_followup_timeout: Default seconds after a response before
                a followup is generated. ``None`` disables followups.
            query_followup_timeout: Shortened followup delay when the LLM
                query suggests a followup is warranted. ``None`` disables.
            actor_query_failure_timeout: Followup delay used when an actor
                checkpoint query fails. ``None`` disables.
            playback_end_buffer_sec: Extra seconds added to the server-side
                playback-end estimate before releasing the response lock for
                the next pipeline. Compensates for client-side latency
                between ``speech_started_at`` and when audio actually starts
                playing (network + first-chunk TTFB + Unreal audio buffer
                warmup). Defaults to 0.5s. Set higher if you still observe
                the previous line's tail being clipped when the next line
                arrives; set to 0 if the client sends reliable
                ``audio_finished`` confirmations.
        """
        self.actor = actor
        self.scene_data = scene_data
        self.default_followup_timeout = default_followup_timeout
        self.idle_timeout = idle_timeout
        self.query_followup_timeout = query_followup_timeout
        self.actor_query_failure_timeout = actor_query_failure_timeout
        self.playback_end_buffer_sec = playback_end_buffer_sec

        self.interrupt_flag: bool = False
        self.interrupt_count: int = 0
        self.followup_deadline: float | None = None
        self._query_cache: dict[str, bool] = {}
        self.allow_followup = False
        self._conversation_player_role_id: str | None = None
        # Per-line elapsed_time at which the client confirmed playback ended.
        # Populated by on_audio_finished so generate_actor_response can use a
        # precise anchor when the confirmation arrives during the post-turn gather.
        self._audio_finished_at: dict[str, float] = {}
        # If a followup was scheduled using the streaming-time estimate, these
        # args let on_audio_finished reschedule it precisely on the real end of
        # playback. Format: (line_id, actor_checkpoint_failed, query_followup_result).
        self._pending_followup_args: tuple[str, bool, bool] | None = None
        # Serialises generate_actor_response so a new user_input cannot start a
        # second response pipeline while the previous line is still streaming.
        # Without this, the new pipeline's TTS chunks would interleave into the
        # same per-session outbound queue as the in-flight line, causing the
        # already-playing audio to hang on the Unreal side.
        self._response_lock = asyncio.Lock()

    def is_busy(self) -> bool:
        """Return ``True`` while a response pipeline is in flight.

        Tick-driven idle/followup paths consult this and skip generating new
        lines while a previous response (TTS streaming + post-turn queries)
        is still running, to keep audio streaming smooth and avoid
        interleaving chunks for different line_ids on the outbound queue.
        """
        return self._response_lock.locked()

    async def await_idle(self) -> None:
        """Block until no response pipeline is in flight.

        Used by lifecycle code (e.g. session teardown / reset) that needs to
        avoid clearing scene state out from under a running response.
        """
        async with self._response_lock:
            pass

    def set_conversation_binding(self, player_role_id: str) -> None:
        """Bind this scene to a specific player role for the current conversation.

        Args:
            player_role_id: The player role ID (e.g. from ``ListPlayerRoles``)
                that is actively talking to this scene's NPC.
        """
        self._conversation_player_role_id = player_role_id.strip()

    def clear_conversation_binding(self) -> None:
        """Remove the current player role binding."""
        self._conversation_player_role_id = None

    def _apply_bound_role_to_actor(self) -> None:
        """Copy the bound player role ID onto the actor. Override in subclasses as needed."""

    async def on_user_input(self, message: str, emotions: list[str] | None = None) -> None:
        """Process a player message and generate an actor response.

        Records the message, evaluates checkpoints, generates an actor line,
        queries for followup scheduling, and summarises history if needed.
        Prints the timer tree after completion.

        Args:
            message: The player's input text. Empty or whitespace-only messages
                are silently ignored (interrupt flag is cleared).
            emotions: Optional list of detected player emotion tags.
        """
        with hierarchical_timer("process_user_input"):
            if not message or not message.strip():
                self.interrupt_flag = False
                return

            await self.generate_actor_response(message.strip(), emotions=emotions, is_idle=False, is_followup=False)
            self.allow_followup = True
        print_timer_tree()

    async def say(self, text: str) -> None:
        """Speak ``text`` exactly, bypassing the LLM and conversation history.

        Acquires the same ``_response_lock`` used by LLM-driven responses,
        so audio chunks for this line cannot interleave with another
        line's chunks on the per-session outbound queue. Does not record
        the line in history, schedule a followup, or mutate checkpoint
        state — this is a diagnostic / external-trigger entry point.
        """
        text = (text or "").strip()
        if not text:
            return
        async with self._response_lock:
            line = DialogueLine(name=self.actor.name, text=text)
            stage_context.deliver_text(line, interruptible=True)
            await self.actor.run_tts(line)

    async def tick(self) -> None:
        """Check for pending followup or idle timeouts and generate actor lines if due.

        Called by the stage on each runtime tick. Generates a followup line
        when ``followup_deadline`` has passed, or an idle line when the actor
        has been silent for longer than ``idle_timeout``.

        Skipped entirely while a response pipeline is in flight; the deadline
        is rechecked on the next tick after the active response completes, so
        tick-driven followups can't race a user_input or stomp on the
        outbound stream of an in-progress line.
        """
        if self._response_lock.locked():
            return

        now = stage_context.elapsed_time

        if self.followup_deadline is not None and now >= self.followup_deadline:
            await self.generate_actor_response(None, is_followup=True)
            self.followup_deadline = None

        elif (
            self.idle_timeout is not None
            and self.actor.speak_end_elapsed is not None
            and now - self.actor.speak_end_elapsed > self.idle_timeout
            and self.actor.history.messages
            and self.actor.history.messages[-1].name == self.actor.name
        ):
            await self.generate_actor_response(None, is_idle=True)

    async def on_game_event(self, name: str, event_info: dict[str, str]) -> None:
        """Match a game event against active :class:`~digital_actor.checkpoints.EventCheckpoint` nodes.

        When a matching checkpoint is found, its narrator message (if any) is
        injected into the actor's history, the checkpoint is completed, and its
        callbacks are emitted as :class:`~digital_actor.game_events.GameEvent` objects.

        Args:
            name: The event identifier to match.
            event_info: Arbitrary metadata about the event (currently unused
                in checkpoint matching).
        """
        checkpoints = self.scene_data.checkpoints
        if not checkpoints or not checkpoints.nodes:
            return
        matched: EventCheckpoint | None = None
        for node in checkpoints.active_nodes():
            if isinstance(node, EventCheckpoint) and node.event_id == name:
                matched = node
                break
        if matched is None:
            return
        logger.info("Event checkpoint matched: %s", name)
        if matched.narrator_message and "true" in matched.narrator_message:
            self.actor.history.add_message(NARRATOR_ROLE_NAME, matched.narrator_message["true"])
        checkpoints.complete(matched.id)
        self.emit_checkpoint_callbacks(matched.callbacks)

    async def on_interrupt(self, line_id: str, elapsed_seconds: float) -> None:
        """Handle a player interrupt: truncate the interrupted line in history.

        Sets the interrupt flag so the next :meth:`generate_actor_response`
        call passes ``is_interrupt=True`` to the actor. Truncates the
        interrupted line's text to approximately the playback position based
        on ``elapsed_seconds`` and ``audio_duration_sec``.

        Args:
            line_id: :attr:`~digital_actor.dialogue.DialogueLine.line_id` of
                the interrupted line.
            elapsed_seconds: How many seconds of the line had been delivered.
        """
        self.followup_deadline = None
        self.interrupt_flag = True
        self.actor.speak_end_elapsed = stage_context.elapsed_time
        self._pending_followup_args = None
        self._audio_finished_at.clear()

        stop_npc: str | None = None
        for line in self.actor.history.messages:
            if stop_npc is None and line.line_id == line_id:
                if line.audio_duration_sec <= 0:
                    idx = max(1, len(line.text) // 4)
                    line.text = line.text[:idx].strip().rstrip(".") + ELLIPSIS
                else:
                    idx = int((elapsed_seconds / line.audio_duration_sec) * len(line.text))
                    idx = max(0, min(idx, len(line.text)))
                    line.text = line.text[:idx].strip().rstrip(".") + ELLIPSIS
                stop_npc = line.name
            elif stop_npc is not None and line.name == stop_npc:
                line.text = ELLIPSIS + line.text
        if stop_npc is None:
            logger.warning(f"Interrupt: line_id {line_id} not found for {self.actor.name}")

    def emit_checkpoint_callbacks(self, callbacks: list[str] | None) -> None:
        """Emit each callback name as a :class:`~digital_actor.game_events.GameEvent`.

        Args:
            callbacks: List of event names to emit, or ``None`` for no-op.
        """
        if not callbacks:
            return
        for callback in callbacks:
            stage_context.deliver_event(GameEvent(name=callback, info={}))

    async def run_query(self, text: str, question: str, latch: bool, obs_name: str) -> bool:
        """Ask the LLM a yes/no question about ``text`` and return the boolean result.

        Results are cached per ``(question, text)`` pair to avoid duplicate
        LLM calls within the same turn. When ``latch=True``, a ``True`` result
        is cached permanently so the question is never re-evaluated once it
        returns ``True``.

        Args:
            text: The conversation text to evaluate the question against.
            question: A yes/no question (e.g. ``"Has the player agreed?"``).
            latch: If ``True``, cache a ``True`` result across turns.
            obs_name: Langfuse observation label for this LLM call.

        Returns:
            ``True`` if the LLM response is ``"yes"`` or ``"true"``
            (case-insensitive); ``False`` otherwise.
        """
        if latch:
            latch_key = f"LATCH:{question}"
            if latch_key in self._query_cache:
                logger.debug("Q: %s *LATCH HIT* | %s", self._query_cache[latch_key], question)
                return self._query_cache[latch_key]
            inner = await self.run_query(text, question, latch=False, obs_name=obs_name)
            if inner:
                self._query_cache[latch_key] = True
            return inner

        cache_key = f"QUERY:{question}:{text}"
        if cache_key in self._query_cache:
            logger.debug("Q: %s *CACHE HIT* | %s", self._query_cache[cache_key], question)
            return self._query_cache[cache_key]

        prompt_info = self.get_query_prompt_info(text, question)
        response = await stage_context.llm_acomplete(prompt_info, obs_name=obs_name)
        result = response.strip().lower() in ("true", "yes")
        self._query_cache[cache_key] = result
        logger.debug("Q: %s | %s", result, question)
        return result

    async def run_checkpoint_queries_parallel(self, nodes: list[QueryCheckpoint]) -> dict[str, bool]:
        """Evaluate multiple :class:`~digital_actor.checkpoints.QueryCheckpoint` nodes concurrently.

        Args:
            nodes: Query checkpoints to evaluate in parallel.

        Returns:
            Dict mapping node ID → boolean result.
        """
        if not nodes:
            return {}
        history_text = self.actor.history.to_string(include_summary=True)
        results = await asyncio.gather(
            *(
                self.run_query(history_text, n.query_str, latch=False, obs_name=f"query_{n.target.lower()}_line")
                for n in nodes
            )
        )
        return {node.id: result for node, result in zip(nodes, results)}

    async def query_checkpoints(self, target: CheckpointTarget) -> CheckpointResult:
        """Evaluate active :class:`~digital_actor.checkpoints.QueryCheckpoint` nodes for ``target``.

        Runs all active query checkpoints for ``target`` in parallel. Completed
        checkpoints have their narrator messages injected into history and their
        callbacks emitted. Returns a summary result.

        Args:
            target: ``"Player"`` to evaluate checkpoints after a player turn;
                ``"Actor"`` after an actor turn.

        Returns:
            :attr:`~digital_actor.checkpoints.CheckpointResult.NOT_EVALUATED`
            if no checkpoints were active, :attr:`~digital_actor.checkpoints.CheckpointResult.PASSED`
            if all passed, or :attr:`~digital_actor.checkpoints.CheckpointResult.FAILED`
            if at least one did not pass.
        """
        checkpoints = self.scene_data.checkpoints
        if not checkpoints or not checkpoints.nodes:
            return CheckpointResult.NOT_EVALUATED
        with hierarchical_timer(f"query_{target.lower()}_checkpoints"):
            active = checkpoints.active_nodes()
            active_target = [n for n in active if isinstance(n, QueryCheckpoint) and n.target.lower() == target.lower()]
            if not active_target:
                return CheckpointResult.NOT_EVALUATED
            results = await self.run_checkpoint_queries_parallel(active_target)

            any_failed = False
            narrator_messages: list[str] = []
            for node in active_target:
                if results.get(node.id, True):
                    if node.narrator_message is not None and "true" in node.narrator_message:
                        narrator_messages.append(node.narrator_message["true"])
                    self.emit_checkpoint_callbacks(node.callbacks)
                    checkpoints.complete(node.id)
                else:
                    any_failed = True
                    if node.narrator_message is not None and "false" in node.narrator_message:
                        narrator_messages.append(node.narrator_message["false"])
            if narrator_messages:
                self.actor.history.add_message(NARRATOR_ROLE_NAME, " ".join(narrator_messages))
            return CheckpointResult.FAILED if any_failed else CheckpointResult.PASSED

    async def generate_actor_response(
        self,
        message: str | None,
        emotions: list[str] | None = None,
        is_idle: bool = False,
        is_followup: bool = False,
    ) -> list[DialogueLine]:
        """Full response pipeline: record message, run checkpoints, generate line, schedule followup.

        Args:
            message: Player message text, or ``None`` for idle/followup lines
                (recorded as ``ELLIPSIS`` in history).
            emotions: Optional player emotion tags.
            is_idle: ``True`` when generating due to player inactivity.
            is_followup: ``True`` when generating an unprompted followup.

        Returns:
            The list of :class:`~digital_actor.dialogue.DialogueLine` objects
            generated by the actor this turn.
        """
        # Serialise the full response pipeline. A new user_input that arrives
        # mid-stream queues here on the lock instead of starting a parallel
        # pipeline that would dump chunks for a different line_id into the
        # same outbound websocket queue and stall the audio Unreal is playing.
        async with self._response_lock:
            self.followup_deadline = None
            if is_idle or is_followup:
                is_interrupt = False
            else:
                is_interrupt = self.interrupt_flag
                self.interrupt_flag = False
                if is_interrupt:
                    self.interrupt_count += 1
                else:
                    self.interrupt_count = 0

            player_message = ELLIPSIS if message is None else message
            self.actor.history.add_message(PLAYER_ROLE_NAME, player_message)

            if message is not None:
                await self.query_checkpoints(target=PLAYER_ROLE_NAME)

            dialogue_line = await self.actor.generate_next_text(
                emotions=emotions,
                is_idle=is_idle,
                is_interrupt=is_interrupt,
                is_followup=is_followup,
                interrupt_count=self.interrupt_count,
            )
            # The actor is now speaking; suppress idle until on_audio_finished sets the real end.
            self.actor.speak_end_elapsed = None
            # Approximate when the client begins playback. The server streams
            # all chunks for short utterances in tens of milliseconds, while
            # client-side playback takes the full audio_duration_sec. Recording
            # the start here lets us hold the response lock until estimated
            # playback completes, even when the client does not send
            # audio_finished confirmations.
            speech_started_at = stage_context.elapsed_time

            # Run post-turn LLM queries concurrently with TTS streaming. The
            # TTS stream is mostly network-bound on the server side, so the
            # checkpoint/summary/followup queries can run during the same
            # window that would otherwise be dead air before the followup.
            async def _post_turn_queries() -> tuple[CheckpointResult, bool]:
                cp_result = await self.query_checkpoints(target="Actor")
                await self.actor.history.summarize_if_needed()
                followup = (
                    await self.query_followup()
                    if self.query_followup_timeout is not None
                    else False
                )
                return cp_result, followup

            _, (actor_checkpoint_result, query_followup_result) = await asyncio.gather(
                self.actor.run_tts(dialogue_line),
                _post_turn_queries(),
            )
            actor_checkpoint_failed = actor_checkpoint_result is CheckpointResult.FAILED
            followup_enabled = (
                self.default_followup_timeout is not None
                or self.query_followup_timeout is not None
                or self.actor_query_failure_timeout is not None
            )

            # Hold the response lock until the client is estimated to have
            # finished playing this line. The server streams a line's bytes
            # in tens of milliseconds, while client-side playback takes the
            # full audio_duration_sec; without this wait, the next response
            # pipeline would start delivering chunks (with user_input_ack=True
            # on its first frame) while Unreal is still playing the previous
            # line, causing the audible "pause then resume" hiccup the user
            # reported.
            #
            # Prefer the client-confirmed end-of-playback timestamp when
            # on_audio_finished has already arrived; otherwise pace on the
            # server-side estimate. This also fixes the followup never being
            # scheduled when the client doesn't send audio_finished.
            finish_time = self._audio_finished_at.pop(dialogue_line.line_id, None)
            if finish_time is None:
                # speech_started_at is captured before the first chunk leaves
                # the server, but the client's actual playback start lags
                # behind it by network latency + first-chunk TTFB + Unreal
                # audio buffer warmup (~0.2-0.5s typically). Add a buffer so
                # the lock is released closer to actual playback end rather
                # than the optimistic server-side estimate. Without this,
                # Unreal's audio component receives the next line's first
                # chunk while the previous line still has buffered audio,
                # and discards the tail.
                expected_playback_end = (
                    speech_started_at
                    + dialogue_line.audio_duration_sec
                    + self.playback_end_buffer_sec
                )
                remaining = expected_playback_end - stage_context.elapsed_time
                if remaining > 0:
                    logger.debug(
                        "Holding response lock for %.2fs to let client finish playing %s",
                        remaining, dialogue_line.line_id,
                    )
                    await asyncio.sleep(remaining)
                # If audio_finished arrived during the sleep, honour it;
                # otherwise fall back to the estimated end.
                finish_time = self._audio_finished_at.pop(
                    dialogue_line.line_id, expected_playback_end
                )

            self.actor.speak_end_elapsed = finish_time
            self._pending_followup_args = None
            if followup_enabled:
                self.schedule_followup(
                    actor_checkpoint_failed, query_followup_result, anchor=finish_time
                )
            return [dialogue_line]

    def schedule_followup(
        self,
        actor_checkpoint_failed: bool,
        query_followup_result: bool,
        anchor: float,
    ) -> None:
        """Set :attr:`followup_deadline` based on checkpoint and query results.

        Picks the shortest applicable timeout:

        - ``actor_query_failure_timeout`` when an actor checkpoint failed.
        - ``query_followup_timeout`` when the followup query returned ``True``.
        - ``default_followup_timeout`` always.

        Args:
            actor_checkpoint_failed: ``True`` if an actor checkpoint did not
                pass this turn.
            query_followup_result: ``True`` if the followup LLM query returned
                yes.
            anchor: Stage elapsed time the delay is measured from. Should be
                the client-confirmed end of playback so the gap counts dead
                air after the audio ends, not after server-side TTS streaming.
        """
        followup_candidates = [self.default_followup_timeout]
        if actor_checkpoint_failed:
            followup_candidates.append(self.actor_query_failure_timeout)
        elif query_followup_result:
            followup_candidates.append(self.query_followup_timeout)
        followup_candidates = [candidate for candidate in followup_candidates if candidate is not None]
        if not followup_candidates:
            return
        followup_delay = sorted(followup_candidates)[0]

        if followup_delay == self.actor_query_failure_timeout:
            logger.warning("NPC checkpoint query false; scheduling retry in %s s", followup_delay)
        elif followup_delay == self.query_followup_timeout:
            logger.debug("NPC followup query true; scheduling followup in %s s", followup_delay)

        self.followup_deadline = anchor + followup_delay

    async def on_audio_finished(self, line_id: str) -> None:
        """Anchor :attr:`~digital_actor.actor.SceneDigitalActor.speak_end_elapsed` and the followup deadline to the real end of playback.

        Called by the stage when the game client confirms ``line_id``'s audio
        has finished playing. If the post-turn pipeline has already scheduled a
        followup using the streaming-time estimate, reschedule it now using the
        precise timestamp; otherwise just record the timestamp so a still-running
        :meth:`generate_actor_response` can pick it up.
        """
        finish_time = stage_context.elapsed_time
        self.actor.speak_end_elapsed = finish_time
        args = self._pending_followup_args
        if args is not None and args[0] == line_id:
            _, actor_checkpoint_failed, query_followup_result = args
            self._pending_followup_args = None
            self.schedule_followup(
                actor_checkpoint_failed, query_followup_result, anchor=finish_time
            )
        else:
            # generate_actor_response is still in-flight; stash the timestamp
            # so it picks the precise anchor when it completes.
            self._audio_finished_at[line_id] = finish_time

    async def query_followup(self) -> bool:
        """Ask the LLM whether the actor should generate an unprompted followup.

        Returns:
            ``True`` if the LLM answers ``"yes"`` or ``"true"``.
        """
        with hierarchical_timer("query_followup"):
            prompt_info = self.get_query_followup_prompt_info()
            response = await stage_context.llm_acomplete(prompt_info, obs_name="query_followup")
            result = response.strip().lower() in ("yes", "true")
            logger.debug("Q: %s | followup", result)
            return result

    def reset(self) -> None:
        """Reset all scene state: interrupt flags, followup deadline, and query cache."""
        self.interrupt_flag = False
        self.interrupt_count = 0
        self.followup_deadline = None
        self._query_cache.clear()
        self.allow_followup = False
        self._audio_finished_at.clear()
        self._pending_followup_args = None
        self.clear_conversation_binding()

    @abstractmethod
    def get_query_followup_prompt_info(self) -> PromptInfo:
        """Return the :class:`~digital_actor.data_models.PromptInfo` for the followup query.

        The LLM is expected to return ``"yes"`` or ``"no"`` indicating whether
        the actor should add a followup line after a short delay.

        Returns:
            A :class:`~digital_actor.data_models.PromptInfo` for a yes/no
            followup query.
        """

    @abstractmethod
    def get_query_prompt_info(self, text: str, question: str) -> PromptInfo:
        """Return the :class:`~digital_actor.data_models.PromptInfo` for a yes/no checkpoint query.

        Args:
            text: The conversation history text to evaluate.
            question: The yes/no question to ask the LLM.

        Returns:
            A :class:`~digital_actor.data_models.PromptInfo` for a yes/no
            checkpoint query.
        """
