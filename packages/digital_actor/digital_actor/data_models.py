"""Pydantic data models shared across the actor, scene, and stage layers."""

from digital_actor.checkpoints import SceneCheckpoints
from digital_actor.dialogue import DialogueLine
from langfuse_utils import LangfusePromptLike
from pydantic import BaseModel, ConfigDict, Field


class PromptInfo(BaseModel):
    """Container for a rendered prompt and its Langfuse tracing metadata.

    Passed to :meth:`~digital_actor.stage.BaseStage.llm_acomplete` so that
    the stage can attach prompt versioning and input metadata to the Langfuse
    observation without the actor needing to know about the LLM client.

    Attributes:
        prompt: The fully rendered prompt string sent to the LLM.
        input_args: Key-value pairs describing the template variables used to
            render ``prompt``. Stored as ``metadata.prompt_input`` in Langfuse.
        langfuse_prompt: The versioned prompt object returned by
            :func:`~langfuse_utils.get_prompt`, used to link the observation to
            a specific prompt version in Langfuse. ``None`` when prompts are
            constructed inline without Langfuse.
        langfuse_prompt_state: Additional prompt state metadata. Stored as
            ``metadata.prompt_state`` in Langfuse.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    prompt: str
    input_args: dict
    langfuse_prompt: LangfusePromptLike | None = None
    langfuse_prompt_state: dict | None = None


class StageData(BaseModel):
    """Base class for stage-level configuration data.

    Subclass to attach custom configuration to a stage without modifying the
    stage class itself.
    """


class SceneData(BaseModel):
    """Configuration and narrative data for a single scene.

    Passed to :class:`~digital_actor.actor.SceneDigitalActor` and
    :class:`~digital_actor.scene.SingleActorScene` on construction.

    Attributes:
        opening_lines: Dialogue lines delivered at scene start before player
            input is accepted. ``None`` means no scripted opening.
        checkpoints: Story checkpoint graph evaluated during the scene.
            Defaults to an empty graph (no checkpoints).
        scene_back_story: Background narrative context injected into the
            actor's prompt.
        prev_scene_description: Summary of the previous scene, available for
            continuity prompts.
        scene_description: Description of the current scene context.
        steer_back_instruction: Instruction injected when the actor needs to
            be redirected back on-topic.
        scene_supplement: Additional narrative text appended to the prompt.
    """

    opening_speech: list[DialogueLine] | None = None
    checkpoints: SceneCheckpoints = Field(default_factory=lambda: SceneCheckpoints.from_dict({"nodes": []}))
    scene_back_story: str | None = None
    prev_scene_description: str | None = None
    scene_description: str | None = None
    steer_back_instruction: str | None = None
    scene_supplement: str | None = None
