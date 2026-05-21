from __future__ import annotations

from typing import Protocol, runtime_checkable

from digital_actor.stage_context import StageContext, get_stage

from metahuman_actor.data_models import MetaHumanSceneData


@runtime_checkable
class MetaHumanStageContext(StageContext, Protocol):
    scene_data: MetaHumanSceneData


stage_context = get_stage(MetaHumanStageContext)
