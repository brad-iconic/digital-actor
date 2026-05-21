"""Stage context protocol and global proxy.

Kept in a separate module to break import cycles between ``actor``, ``scene``,
and ``stage``.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, cast, runtime_checkable

from digital_actor.data_models import (
    PromptInfo,
    SceneData,
    StageData,
)
from digital_actor.dialogue import DialogueLine
from digital_actor.game_events import GameEvent
from digital_actor.messenger import Messenger
from llm_lib import LLMClient
from tts_lib import TTSClient


@runtime_checkable
class StageContext(Protocol):
    """Structural protocol describing the interface that actors and scenes use from the stage.

    Actors and scenes call methods on the module-level
    :data:`stage_context` proxy rather than holding a direct reference to
    the stage, preventing circular dependencies between layers.

    Implementations: all :class:`~digital_actor.stage.BaseStage` subclasses.
    """

    llm_client: LLMClient
    """The LLM client configured for this stage."""

    tts_client: TTSClient | None
    """The TTS client, or ``None`` if TTS is disabled."""

    messenger: Messenger
    """The outbound message router."""

    stage_data: StageData
    """Stage-level configuration data."""

    scene_data: SceneData
    """Current scene configuration data."""

    def llm_complete(self, prompt_info: PromptInfo, obs_name: str) -> str:
        """Blocking LLM completion. See :meth:`~digital_actor.stage.BaseStage.llm_complete`."""
        ...

    async def llm_acomplete(self, prompt_info: PromptInfo, obs_name: str) -> str:
        """Async LLM completion. See :meth:`~digital_actor.stage.BaseStage.llm_acomplete`."""
        ...

    @property
    def elapsed_time(self) -> float:
        """Simulated elapsed time in seconds since the stage last had :meth:`~digital_actor.stage.BaseStage.step` called."""
        ...

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
        """Deliver a text-only :class:`~digital_actor.messenger.OutboundPayload`."""
        ...

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
        """Deliver an audio :class:`~digital_actor.messenger.OutboundPayload`."""
        ...

    def deliver_event(self, event: GameEvent) -> None:
        """Queue a :class:`~digital_actor.game_events.GameEvent` for the client."""
        ...


class _StageProxy:
    def __getattr__(self, name: str):
        if _current is None:
            raise RuntimeError("Stage not initialized")
        return getattr(_current, name)


_current: Any = None
_proxy_singleton: _StageProxy | None = None

_T = TypeVar("_T")


def _proxy() -> _StageProxy:
    global _proxy_singleton
    if _proxy_singleton is None:
        _proxy_singleton = _StageProxy()
    return _proxy_singleton


def set_stage(stage: Any) -> None:
    """Register ``stage`` as the global stage context.

    Called automatically by :class:`~digital_actor.stage.BaseStage.__init__`.
    If a stage is already registered, a warning is logged and the new stage
    replaces it.

    Args:
        stage: Any :class:`~digital_actor.stage.BaseStage` subclass instance.
    """
    global _current
    if _current is not None:
        print(
            f"A stage is already registered ({type(_current).__name__}); it will be overwritten by {type(stage).__name__}."
        )
    _current = stage


def get_stage(context_type: type[_T]) -> _T:
    """Return the global stage proxy cast to ``context_type``.

    Args:
        context_type: The protocol or class to cast the proxy to.

    Returns:
        The proxy singleton, typed as ``context_type``.
    """
    return cast(_T, _proxy())


stage_context: StageContext = get_stage(StageContext)
"""Module-level proxy to the active stage.

Actors and scenes import this object and call methods on it directly. The
proxy forwards every attribute access to whatever stage was registered via
:func:`set_stage`, raising ``RuntimeError`` if no stage has been set.

Example:
    ```python
    from digital_actor.stage_context import stage_context

    response = await stage_context.llm_acomplete(prompt_info, obs_name="greeting")
    ```
"""
