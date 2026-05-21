"""Dialogue line model and parsing utilities."""

from __future__ import annotations

import re
import uuid
from typing import ClassVar, Final, Literal

import pydantic

PLAYER_ROLE_NAME: Final = "Player"
"""Speaker name used for player dialogue lines."""

NARRATOR_ROLE_NAME: Final = "Narrator"
"""Speaker name used for narrator lines (not spoken by any character)."""

ACTOR_GENERAL_ROLE_NAME: Final = "Actor"
"""Generic actor speaker name used in checkpoint target specifications."""

CheckpointTarget = Literal["Player", "Actor"]
"""Valid values for checkpoint ``target`` fields."""

ELLIPSIS = "..."
"""Placeholder text used when a dialogue line is truncated by an interrupt."""


class DialogueLine(pydantic.BaseModel):
    """A single spoken or narrated line in the conversation history.

    Attributes:
        name: Speaker name (e.g. ``"Player"``, ``"Greta"``, ``"Narrator"``).
        text: The spoken or narrated content.
        tags: Emotion or direction tags extracted from bracketed annotations
            in the original text (e.g. ``["happy", "surprised"]``).
        line_id: UUID string assigned on creation, used to identify the line
            for interrupt handling.
        audio_duration_sec: Duration of the corresponding TTS audio in
            seconds. Updated by the actor after TTS delivery completes;
            ``0.0`` before audio is generated.
    """

    name: str
    text: str
    tags: list[str] = pydantic.Field(default_factory=list)
    line_id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    audio_duration_sec: float = 0.0

    _TAG_PATTERN: ClassVar[re.Pattern] = re.compile(r"\[([a-zA-Z]+(?:,\s*[a-zA-Z]+)*)\]")
    _NAME_PATTERN: ClassVar[re.Pattern] = re.compile(r"^\[(\w+)\]:\s*(.*)")

    @classmethod
    def parse_speech(cls, text: str, default_name: str | None = None) -> list[DialogueLine]:
        """Parse multi-line LLM output into a list of :class:`DialogueLine` objects.

        Expects lines in the format ``[Name]: [tag, tag] Content`` where the
        ``[Name]:`` prefix and ``[tag]`` annotations are optional.

        Lines without a ``[Name]:`` prefix use ``default_name`` if provided;
        otherwise they are skipped. Blank lines are always skipped.

        Args:
            text: Raw LLM output string, possibly spanning multiple lines.
            default_name: Fallback speaker name for lines without a prefix.

        Returns:
            List of :class:`DialogueLine` objects in input order, one per
            non-blank line that could be attributed to a speaker.

        Example:
            ```python
            lines = DialogueLine.parse_speech(
                "[Greta]: [happy] Welcome to the Rusty Flagon!\\n[Player]: Thanks.",
            )
            # → [DialogueLine(name="Greta", text="Welcome...", tags=["happy"]),
            #    DialogueLine(name="Player", text="Thanks.")]
            ```
        """
        all_lines = []
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            match = cls._NAME_PATTERN.match(raw_line)
            if match:
                name = match.group(1)
                body = match.group(2)
            elif default_name:
                name = default_name
                body = raw_line
            else:
                continue
            tags = cls._TAG_PATTERN.findall(body)
            clean_text = cls._TAG_PATTERN.sub("", body).strip()
            if clean_text:
                all_lines.append(cls(name=name, text=clean_text, tags=tags))
        return all_lines

    def to_string(self) -> str:
        """Serialise the line to ``Name: [tag, tag] content`` format.

        Returns:
            A single-line string representation of this dialogue line.
        """
        if self.tags:
            return f"{self.name}: [{', '.join(self.tags)}] {self.text}"
        else:
            return f"{self.name}: {self.text}"
