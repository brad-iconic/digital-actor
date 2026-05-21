import json
import sys
from pathlib import Path

from app_logging import get_logger
from digital_actor.game_events import GameEventBase, PlayerInterruptEvent
from digital_actor.messenger import Messenger, MessengerType
from digital_actor.stage import SingleSceneStage

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.data_models import MetaHumanSceneData
from metahuman_actor.scene import MetaHumanSingleActorScene
from metahuman_actor.settings import settings

logger = get_logger(__name__)


class MetaHumanStage(SingleSceneStage):
    _scene: MetaHumanSingleActorScene

    def __init__(
        self,
        llm_model: str,
        messenger: Messenger | MessengerType | None = None,
        tts_enabled: bool = True,
        persona_path: Path | None = None,
    ) -> None:
        with open(
            persona_path or settings.character_persona_path, encoding="utf-8"
        ) as f:
            persona = json.load(f)
        voice = (persona.get("voice") or {}) if tts_enabled else {}
        super().__init__(
            llm_model,
            tts_provider=voice.get("provider"),
            tts_voice_id=voice.get("voice_id"),
            tts_model_id=voice.get("model_id"),
            messenger=messenger,
        )
        self.actor = MetaHumanDigitalActor(persona)
        scene_data = MetaHumanSceneData.load(scene_idx=1, actor_name=self.actor.name)
        scene = MetaHumanSingleActorScene(
            self.actor,
            scene_data,
            **settings.digital_actor_server.model_dump(exclude={"prompt_label"}),
        )
        self.register_scene(scene)
        logger.info("Stage ready")
        sys.stdout.flush()

    @property
    def scene_data(self) -> MetaHumanSceneData:
        return self._scene.scene_data

    async def on_game_event(self, event: GameEventBase) -> None:
        if isinstance(event, PlayerInterruptEvent):
            if self._scene is not None:
                await self._scene.on_interrupt(event.line_id, event.elapsed_seconds)
        else:
            await super().on_game_event(event)

        if self._scene.is_finished():
            if self.load_next_scene():
                await self.deliver_opening_speech()

    async def on_user_input(self, message: str) -> None:
        await super().on_user_input(message)
        if self._scene.is_finished():
            if self.load_next_scene():
                await self.deliver_opening_speech()

    async def deliver_opening_speech(self) -> None:
        if self._scene is not None:
            await self._scene.deliver_opening_speech()

    def load_next_scene(self) -> bool:
        previous_completed = set(self._scene.scene_data.checkpoints.completed)
        next_scene_idx = self._scene.scene_data.scene_idx + 1
        next_scene_dir = settings.script_path / f"scene{next_scene_idx}"
        if not next_scene_dir.exists():
            logger.info("No scene %s found; staying on current scene", next_scene_idx)
            return False

        scene_data = MetaHumanSceneData.load(
            scene_idx=next_scene_idx, actor_name=self.actor.name
        )
        scene_data.checkpoints.completed.update(previous_completed)
        scene_data.checkpoints.active.clear()
        scene_data.checkpoints._recompute_active()
        scene = MetaHumanSingleActorScene(
            self.actor,
            scene_data,
            **settings.digital_actor_server.model_dump(exclude={"prompt_label"}),
        )
        self.register_scene(scene)
        logger.info("Transitioned to scene %s", next_scene_idx)
        return True
