"""GameDrivenStage — owns scenario lifecycle for the request-driven server.

Builds the actor + scene atomically on load, swaps scene_data on
set_scene/set_interaction while preserving actor history, and exposes the
scene_data property that stage_context (and thus the actor's prompt builder)
reads.
"""
from __future__ import annotations

import json

from app_logging import get_logger
from digital_actor.game_events import GameEventBase
from digital_actor.messenger import Messenger, MessengerType
from digital_actor.stage import SingleSceneStage
from tts_lib import get_tts_client

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.game_driven.scenario import GameDrivenScenario
from metahuman_actor.game_driven.scene import GameDrivenScene
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData

logger = get_logger(__name__)


class UnknownSceneError(ValueError):
    pass


class UnknownInteractionError(ValueError):
    pass


class UnknownNpcError(ValueError):
    pass


class GameDrivenStage(SingleSceneStage):
    _scene: GameDrivenScene | None

    def __init__(
        self,
        llm_model: str,
        messenger: Messenger | MessengerType | None = None,
        tts_enabled: bool = True,
    ) -> None:
        super().__init__(
            llm_model,
            tts_provider=None,
            tts_voice_id=None,
            tts_model_id=None,
            messenger=messenger,
        )
        self._scenario: GameDrivenScenario | None = None
        self.actor: MetaHumanDigitalActor | None = None
        self.current_scene: str | None = None
        self.current_interaction: str | None = None
        self._tts_enabled = tts_enabled
        logger.info("GameDrivenStage ready (no scenario loaded)")

    @property
    def scenario(self) -> GameDrivenScenario | None:
        return self._scenario

    @property
    def scene_data(self) -> GameDrivenSceneData | None:
        if self._scene is None:
            return None
        return self._scene.scene_data

    async def await_idle(self) -> None:
        # GameDrivenScene subclasses BaseScene, which (unlike SingleActorScene)
        # does not define await_idle. Guard so the inherited lifecycle calls in
        # set_scene/set_interaction/unload don't crash on a scene without it.
        scene = self._scene
        if scene is not None and hasattr(scene, "await_idle"):
            await scene.await_idle()

    async def on_game_event(self, event: GameEventBase) -> None:
        return

    async def on_user_input(self, message: str) -> None:
        if self._scene is not None:
            await self._scene.on_user_input(message)

    def _build_scene_data(self, scene: str, interaction: str) -> GameDrivenSceneData:
        assert self._scenario is not None and self.actor is not None
        return GameDrivenSceneData.load(
            self._scenario,
            scene=scene,
            character=self._scenario.default_character,
            interaction=interaction,
        )

    async def load_scenario(self, name: str) -> None:
        new_scenario = GameDrivenScenario.load(name)
        persona_path = new_scenario.persona_path(new_scenario.default_character)
        with open(persona_path, encoding="utf-8") as f:
            persona = json.load(f)
        voice = (persona.get("voice") or {}) if self._tts_enabled else {}
        new_actor = MetaHumanDigitalActor(persona)
        new_scene_data = GameDrivenSceneData.load(
            new_scenario,
            scene=new_scenario.default_scene,
            character=new_scenario.default_character,
            interaction=new_scenario.default_interaction,
        )
        new_tts = (
            get_tts_client(
                voice.get("provider"),
                voice_id=voice.get("voice_id"),
                model_id=voice.get("model_id"),
            )
            if voice.get("provider")
            else None
        )
        new_scene = GameDrivenScene(actor=new_actor, scene_data=new_scene_data)

        if self._scenario is not None:
            await self.await_idle()
        self.reset()
        self._scenario = new_scenario
        self.actor = new_actor
        self.current_scene = new_scenario.default_scene
        self.current_interaction = new_scenario.default_interaction
        self._tts_client = new_tts
        self.register_scene(new_scene)
        logger.info("Loaded game-driven scenario=%s", new_scenario.name)

    async def unload_scenario(self) -> None:
        if self._scenario is None:
            return
        await self.await_idle()
        self.reset()
        self._scene = None
        self._scenario = None
        self.actor = None
        self.current_scene = None
        self.current_interaction = None
        self._tts_client = None
        logger.info("Unloaded game-driven scenario")

    async def set_scene(self, scene: str) -> None:
        if self._scenario is None:
            raise UnknownSceneError("no scenario loaded")
        if not self._scenario.has_scene(scene):
            raise UnknownSceneError(scene)
        interaction = self._scenario.default_interaction
        if not self._scenario.has_interaction(
            scene, self._scenario.default_character, interaction
        ):
            raise UnknownInteractionError(f"{scene}/{interaction}")
        new_scene_data = self._build_scene_data(scene, interaction)
        await self.await_idle()
        self.current_scene = scene
        self.current_interaction = interaction
        assert self._scene is not None
        self._scene.scene_data = new_scene_data
        logger.info("Scene -> %s (interaction reset to %s)", scene, interaction)

    async def set_interaction(self, npc: str, interaction: str) -> None:
        if self._scenario is None or self.actor is None:
            raise UnknownNpcError("no scenario loaded")
        if npc != self._scenario.default_character:
            raise UnknownNpcError(npc)
        if not self._scenario.has_interaction(
            self.current_scene, npc, interaction
        ):
            raise UnknownInteractionError(interaction)
        new_scene_data = self._build_scene_data(self.current_scene, interaction)
        await self.await_idle()
        self.current_interaction = interaction
        assert self._scene is not None
        self._scene.scene_data = new_scene_data
        logger.info("Interaction -> %s", interaction)
