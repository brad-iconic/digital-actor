import json
import sys

from app_logging import get_logger
from digital_actor.game_events import GameEventBase, PlayerInterruptEvent
from digital_actor.messenger import Messenger, MessengerType
from digital_actor.stage import SingleSceneStage
from tts_lib import get_tts_client

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
        self._scenario: Scenario | None = None
        self._persona_variant: str | None = None
        self.actor: MetaHumanDigitalActor | None = None
        self._tts_enabled = tts_enabled
        logger.info("Stage ready (no scenario loaded)")
        sys.stdout.flush()

    @property
    def scenario(self) -> Scenario | None:
        return self._scenario

    @property
    def scene_data(self) -> MetaHumanSceneData | None:
        if self._scene is None:
            return None
        return self._scene.scene_data

    async def on_game_event(self, event: GameEventBase) -> None:
        if isinstance(event, PlayerInterruptEvent):
            if self._scene is not None:
                await self._scene.on_interrupt(event.line_id, event.elapsed_seconds)
        else:
            await super().on_game_event(event)

        if self._scene is not None and self._scene.is_finished():
            if self.load_next_scene():
                await self.deliver_opening_speech()

    async def on_user_input(self, message: str) -> None:
        await super().on_user_input(message)
        if self._scene is not None and self._scene.is_finished():
            if self.load_next_scene():
                await self.deliver_opening_speech()

    async def deliver_opening_speech(self) -> None:
        if self._scene is not None:
            await self._scene.deliver_opening_speech()

    def load_next_scene(self) -> bool:
        if self._scenario is None or self._scene is None or self.actor is None:
            return False
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
        """Load or hot-swap a scenario. Atomic: builds new state locally and
        only swaps in after every construction step succeeds — so a failure
        leaves the prior state (empty or loaded) untouched.

        Rebuilds the TTS client from the scenario's persona.voice, so
        scenarios with different voice configs work correctly across loads.
        """
        new_scenario = Scenario.load(name, persona_variant=persona_variant)
        with open(new_scenario.persona_path, encoding="utf-8") as f:
            persona = json.load(f)
        voice = (persona.get("voice") or {}) if self._tts_enabled else {}
        new_actor = MetaHumanDigitalActor(persona)
        new_scene_data = MetaHumanSceneData.load(
            new_scenario, scene_idx=1, actor_name=new_actor.name
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
        new_scene = MetaHumanSingleActorScene(
            new_actor,
            new_scene_data,
            **new_scenario.settings.model_dump(exclude={"prompt_label"}),
        )

        # Construction succeeded — drain any in-flight pipeline before swap.
        if self._scenario is not None:
            await self.await_idle()
        self.reset()
        self._scenario = new_scenario
        self._persona_variant = persona_variant
        self.actor = new_actor
        self._tts_client = new_tts
        self.register_scene(new_scene)
        logger.info("Loaded scenario=%s", new_scenario.name)

    async def unload_scenario(self) -> None:
        """Drain in-flight work and drop scenario, actor, scene, TTS client.

        Safe to call when nothing is loaded (no-op).
        """
        if self._scenario is None:
            return
        await self.await_idle()
        self.reset()
        self._scene = None
        self._scenario = None
        self._persona_variant = None
        self.actor = None
        self._tts_client = None
        logger.info("Unloaded scenario")
