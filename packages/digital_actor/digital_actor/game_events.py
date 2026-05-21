"""Event models for game-engine → AI server communication."""

import pydantic


class GameEventBase(pydantic.BaseModel):
    """Immutable base for all events queued via :meth:`~digital_actor.stage.BaseStage.queue_game_event`."""

    model_config = pydantic.ConfigDict(frozen=True)


class GameEvent(GameEventBase):
    """A named game event sent from the game engine to the AI server.

    Maps to the protobuf ``GameEvent`` message (``SendGameToAiEvent`` RPC).
    Matched against active :class:`~digital_actor.checkpoints.EventCheckpoint`
    nodes in the current scene.

    Attributes:
        name: Event identifier (e.g. ``"door_opened"``). Matched against
            :attr:`~digital_actor.checkpoints.EventCheckpoint.event_id`.
        info: Arbitrary string key-value metadata about the event.
    """

    name: str
    info: dict[str, str]


class PlayerInterruptEvent(GameEventBase):
    """Signals that the player interrupted the actor mid-line.

    Sent by the game engine when the player speaks before the actor finishes
    delivering their line.

    Attributes:
        actor_name: Name of the actor whose line was interrupted.
        line_id: :attr:`~digital_actor.dialogue.DialogueLine.line_id` of the
            interrupted line.
        elapsed_seconds: How many seconds of the line had been delivered when
            the interrupt occurred, used to truncate the line text accurately.
    """

    actor_name: str
    line_id: str
    elapsed_seconds: float
