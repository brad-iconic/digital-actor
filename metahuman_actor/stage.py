import json
import sys

from app_logging import get_logger
from digital_actor.game_events import GameEventBase, PlayerInterruptEvent
from digital_actor.messenger import Messenger, MessengerType
from digital_actor.stage import SingleSceneStage

from metahuman_actor.actor import MetaHumanDigitalActor
from metahuman_actor.data_models import MetaHumanSceneData
from metahuman_actor.scenario import Scenario
from metahuman_actor.scene import MetaHumanSingleActorScene

logger = get_logger(__name__)


class MetaHumanStage(SingleSceneStage):
    _scene: MetaHumanSingleActorScene

    def __init__(
        self,
        llm_model: str,
        scenario_name: str,
        messenger: Messenger | MessengerType | None = None,
        tts_enabled: bool = True,
        persona_variant: str | None = None,
    ) -> None:
        scenario = Scenario.load(scenario_name, persona_variant=persona_variant)
        with open(scenario.persona_path, encoding="utf-8") as f:
            persona = json.load(f)
        voice = (persona.get("voice") or {}) if tts_enabled else {}
        super().__init__(
            llm_model,
            tts_provider=voice.get("provider"),
            tts_voice_id=voice.get("voice_id"),
            tts_model_id=voice.get("model_id"),
            messenger=messenger,
        )
        self._scenario = scenario
        self._persona_variant = persona_variant
        self.actor = MetaHumanDigitalActor(persona)
        scene_data = MetaHumanSceneData.load(
            scenario, scene_idx=1, actor_name=self.actor.name
        )
        scene = MetaHumanSingleActorScene(
            self.actor,
            scene_data,
            **scenario.settings.model_dump(exclude={"prompt_label"}),
        )
        self.register_scene(scene)
        logger.info("Stage ready with scenario=%s", scenario.name)
        sys.stdout.flush()

    @property
    def scenario(self) -> Scenario:
        return self._scenario

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
        next_scene_dir = self._scenario.scene_dir(next_scene_idx)
        if not next_scene_dir.exists():
            logger.info(
                "No scene %s found under scenario %s; staying on current scene",
                next_scene_idx,
                self._scenario.name,
            )
            return False

        scene_data = MetaHumanSceneData.load(
            self._scenario, scene_idx=next_scene_idx, actor_name=self.actor.name
        )
        scene_data.checkpoints.completed.update(previous_completed)
        scene_data.checkpoints.active.clear()
        scene_data.checkpoints._recompute_active()
        scene = MetaHumanSingleActorScene(
            self.actor,
            scene_data,
            **self._scenario.settings.model_dump(exclude={"prompt_label"}),
        )
        self.register_scene(scene)
        logger.info(
            "Transitioned to scene %s within scenario %s",
            next_scene_idx,
            self._scenario.name,
        )
        return True

    async def load_scenario(
        self, name: str, persona_variant: str | None = None
    ) -> None:
        """Tear down the current scene and rebuild for a different scenario.

        Raises before any teardown if the new scenario / persona can't be
        loaded — leaving the current state intact.
        """
        new_scenario = Scenario.load(name, persona_variant=persona_variant)
        with open(new_scenario.persona_path, encoding="utf-8") as f:
            persona = json.load(f)
        # Drain any in-flight pipeline before we replace the actor/scene.
        await self.await_idle()
        self.reset()
        self._scenario = new_scenario
        self._persona_variant = persona_variant
        self.actor = MetaHumanDigitalActor(persona)
        scene_data = MetaHumanSceneData.load(
            new_scenario, scene_idx=1, actor_name=self.actor.name
        )
        scene = MetaHumanSingleActorScene(
            self.actor,
            scene_data,
            **new_scenario.settings.model_dump(exclude={"prompt_label"}),
        )
        self.register_scene(scene)
        logger.info("Hot-swapped to scenario=%s", new_scenario.name)
