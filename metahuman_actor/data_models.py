import json

from digital_actor.checkpoints import SceneCheckpoints
from digital_actor.data_models import SceneData
from langfuse_utils import get_prompt

from metahuman_actor.scenario import Scenario


class MetaHumanSceneData(SceneData):
    character_back_story: str
    scene_idx: int
    opening_speech: str

    @classmethod
    def load(cls, scenario: Scenario, scene_idx: int, actor_name: str):
        scene_dir = scenario.scene_dir(scene_idx)
        with open(scene_dir / "checkpoints.json", encoding="utf-8") as f:
            checkpoints_data = json.load(f)
        p = scenario.prompts_root
        return cls(
            scene_idx=scene_idx,
            scene_back_story=get_prompt(f"{p}/back_story").compile(),
            character_back_story=get_prompt(
                f"{p}/scene{scene_idx}/character_back_story"
            ).compile(),
            prev_scene_description=""
            if scene_idx == 1
            else get_prompt(f"{p}/scene{scene_idx}/prev_scene_description").compile(),
            scene_description=get_prompt(
                f"{p}/scene{scene_idx}/scene_description"
            ).compile(),
            steer_back_instruction=get_prompt(
                f"{p}/scene{scene_idx}/steer_back_instructions"
            ).compile(),
            scene_supplement=get_prompt(f"{p}/scene_supplement").compile(
                actor_name=actor_name
            ),
            checkpoints=SceneCheckpoints.from_dict(checkpoints_data),
            opening_speech=get_prompt(f"{p}/scene{scene_idx}/opening_speech").compile(),
        )

    def is_finished(self) -> bool:
        return self.checkpoints.is_finished()
