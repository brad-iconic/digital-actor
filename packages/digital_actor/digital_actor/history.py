"""Conversation history with automatic summarisation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from digital_actor.dialogue import (
    ELLIPSIS,
    NARRATOR_ROLE_NAME,
    PLAYER_ROLE_NAME,
    DialogueLine,
)
from digital_actor.stage_context import stage_context

if TYPE_CHECKING:
    from digital_actor.actor import BaseDigitalActor


class DialogueHistory:
    """Ordered conversation history for one actor with automatic summarisation.

    Tracks all :class:`~digital_actor.dialogue.DialogueLine` objects exchanged
    during a scene. When the number of non-narrator messages exceeds
    ``summarize_threshold``, the oldest messages (beyond
    ``preserve_recent_messages``) are condensed into a single summary string
    via an LLM call. The formatted output always ends with a ``Player: ...``
    hint if the actor spoke last, so LLM prompts correctly anticipate a player
    turn next.

    Attributes:
        actor: The actor this history belongs to.
        messages: All recorded dialogue lines in chronological order.
        summary: Most recent condensed summary, or ``None`` if none has been
            generated.
        summarize_threshold: Non-narrator message count that triggers
            summarisation.
        preserve_recent_messages: Number of recent non-narrator messages kept
            verbatim when summarising.
    """

    def __init__(
        self,
        actor: BaseDigitalActor,
        summarize_threshold: int = 10,
        preserve_recent_messages: int = 4,
        player_name: str = PLAYER_ROLE_NAME,
    ):
        """
        Args:
            actor: The actor that owns this history.
            summarize_threshold: Number of non-narrator messages after which
                :meth:`summarize_if_needed` triggers a summary. Defaults to
                ``10``.
            preserve_recent_messages: Number of recent non-narrator messages
                kept verbatim (not included in the summary). Defaults to ``4``.
        """
        self.actor = actor
        self.messages: list[DialogueLine] = []
        self.summary_idx: int = 0
        self.summary: str | None = None
        self.summarize_threshold = summarize_threshold
        self.preserve_recent_messages = preserve_recent_messages
        self.player_name = player_name

    def reset(self) -> None:
        """Clear all messages, the summary index, and the summary text."""
        self.messages = []
        self.summary_idx = 0
        self.summary = None

    def add_line(self, line: DialogueLine) -> None:
        """Append an already-constructed :class:`~digital_actor.dialogue.DialogueLine`.

        Args:
            line: Line to append.
        """
        self.messages.append(line)

    def add_message(self, source: str, message: str, tags: list[str] | None = None) -> DialogueLine:
        """Create a new :class:`~digital_actor.dialogue.DialogueLine` and append it.

        Args:
            source: Speaker name (e.g. ``"Player"``, actor name).
            message: The spoken text.
            tags: Optional list of emotion/direction tags.

        Returns:
            The newly created and appended :class:`~digital_actor.dialogue.DialogueLine`.
        """
        line = DialogueLine(name=source, text=message, tags=tags or [])
        self.messages.append(line)
        return line

    def to_string(self, include_summary: bool = True) -> str:
        """Render the history as a formatted string for LLM prompts.

        If a summary exists and ``include_summary`` is ``True``, it is
        prepended as ``Summary: <text>``. Appends ``Player: ...`` at the end
        if the last non-narrator speaker was the actor, indicating the player
        is expected to reply.

        Args:
            include_summary: Whether to prepend the summary. Defaults to
                ``True``.

        Returns:
            Multi-line string with one entry per message plus an optional
            trailing ``Player: ...`` hint.
        """
        all_lines = []
        if self.summary_idx > 0 and include_summary:
            all_lines.append(f"Summary: {self.summary}")

        for line in self.messages[self.summary_idx :]:
            all_lines.append(line.to_string())

        if len(self.messages) > 0 and not self._is_last_line_from_player():
            all_lines.append(f"{self.player_name}: {ELLIPSIS}")

        return "\n\n".join(all_lines)

    def last_actor_line(self) -> tuple[DialogueLine, int] | None:
        """Return the most recent actor line and its index.

        Walks backwards from the end of :attr:`messages`, skipping narrator
        and player lines. Returns ``None`` if the actor has not spoken yet.
        """
        for idx in range(len(self.messages) - 1, -1, -1):
            line = self.messages[idx]
            if line.name not in (NARRATOR_ROLE_NAME, self.player_name):
                return line, idx
        return None

    def _is_last_line_from_player(self, filter_narrator: bool = True) -> bool:
        if len(self.messages) == 0:
            return False
        if filter_narrator:
            last_non_narrator_message_idx = len(self.messages) - 1
            while (
                last_non_narrator_message_idx >= 0
                and self.messages[last_non_narrator_message_idx].name == NARRATOR_ROLE_NAME
            ):
                last_non_narrator_message_idx -= 1
            if last_non_narrator_message_idx < 0:
                return False
            return self.messages[last_non_narrator_message_idx].name == self.player_name
        return self.messages[-1].name == self.player_name

    def get_message_count(self, role_filter: str | list[str] | None = None) -> int:
        """Count messages since the summary index, optionally excluding certain roles.

        Args:
            role_filter: Speaker name(s) to **exclude** from the count. Pass
                ``NARRATOR_ROLE_NAME`` to count only player and actor lines.
                ``None`` counts all messages.

        Returns:
            Number of messages since the last summary.
        """
        count = 0
        if isinstance(role_filter, str):
            role_filter = [role_filter]
        for i in range(self.summary_idx, len(self.messages)):
            if role_filter is None or self.messages[i].name not in role_filter:
                count += 1
        return count

    async def summarize_if_needed(self) -> None:
        """Summarise the history if the non-narrator message count exceeds the threshold.

        Calls :meth:`summarize` when
        ``get_message_count(NARRATOR_ROLE_NAME) > summarize_threshold``.
        """
        if self.get_message_count(role_filter=NARRATOR_ROLE_NAME) > self.summarize_threshold:
            await self.summarize()

    async def summarize(self) -> None:
        """Summarise older messages into :attr:`summary` via the stage LLM.

        Preserves the most recent ``preserve_recent_messages`` non-narrator
        messages verbatim. The messages before that point are condensed via
        the actor's :meth:`~digital_actor.actor.BaseDigitalActor.get_summary_prompt_info`
        prompt. Updates :attr:`summary_idx` so condensed messages are replaced
        by the summary in future :meth:`to_string` calls.
        """
        preserve_idx = 0
        non_narrator_msg_cnt = 0
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].name != NARRATOR_ROLE_NAME:
                non_narrator_msg_cnt += 1
                if non_narrator_msg_cnt == self.preserve_recent_messages:
                    preserve_idx = i
                    break

        if preserve_idx <= self.summary_idx:
            return

        dialogue_lines = []
        for line in self.messages[self.summary_idx : preserve_idx]:
            dialogue_lines.append(f"{line.name}: {line.text}")
        dialogue = "\n".join(dialogue_lines)

        prompt_info = self.actor.get_summary_prompt_info(dialogue)
        response = await stage_context.llm_acomplete(prompt_info, obs_name="summarise_history")

        self.summary = response
        self.summary_idx = preserve_idx

    def __repr__(self):
        return self.to_string(include_summary=True)
