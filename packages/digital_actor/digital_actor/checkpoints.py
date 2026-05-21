"""Story checkpoint graph for conditional dialogue triggers."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

import pydantic
from digital_actor.dialogue import CheckpointTarget


class RequireExpr(pydantic.BaseModel):
    """Boolean expression over checkpoint node IDs used as activation conditions.

    A ``RequireExpr`` can be a simple string ID or a nested ``AND``/``OR``
    tree, allowing complex dependency graphs between checkpoints.

    Attributes:
        op: Logical operator — ``"AND"`` (all deps must be completed) or
            ``"OR"`` (any dep must be completed).
        deps: Child dependencies, each a node ID string or another
            :class:`RequireExpr`.
    """

    op: Literal["AND", "OR"]
    deps: list[Annotated[RequireExpr | str, pydantic.Field(union_mode="left_to_right")]]


RequireExpr.model_rebuild()

RequireDep = str | RequireExpr
"""A dependency reference — either a node ID string or a :class:`RequireExpr`."""


class CheckpointResult(Enum):
    """Result of evaluating the active checkpoints for a conversation turn.

    Attributes:
        NOT_EVALUATED: No active checkpoints existed for the target.
        PASSED: All active checkpoints were satisfied.
        FAILED: At least one active checkpoint was not satisfied.
    """

    NOT_EVALUATED = "not_evaluated"
    PASSED = "passed"
    FAILED = "failed"


def _is_satisfied(dependency: RequireDep | None, completed: set[str]) -> bool:
    if dependency is None:
        return True
    if isinstance(dependency, str):
        return dependency in completed
    if dependency.op == "AND":
        return all(_is_satisfied(dep, completed) for dep in dependency.deps)
    return any(_is_satisfied(dep, completed) for dep in dependency.deps)


def _dep_contains(dependency: RequireDep, node_id: str) -> bool:
    if isinstance(dependency, str):
        return dependency == node_id
    return any(_dep_contains(dep, node_id) for dep in dependency.deps)


def _collect_leaves(dependency: RequireDep) -> set[str]:
    if isinstance(dependency, str):
        return {dependency}
    result: set[str] = set()
    for dep in dependency.deps:
        result |= _collect_leaves(dep)
    return result


def _collect_or_peers(dependency: RequireDep | None, completed_id: str) -> set[str]:
    if dependency is None or isinstance(dependency, str):
        return set()
    peers: set[str] = set()
    if dependency.op == "OR" and _dep_contains(dependency, completed_id):
        for dep in dependency.deps:
            if not _dep_contains(dep, completed_id):
                peers |= _collect_leaves(dep)
    for dep in dependency.deps:
        peers |= _collect_or_peers(dep, completed_id)
    return peers


def _is_blocked(dependency: RequireDep | None, dropped: set[str], completed: set[str]) -> bool:
    if dependency is None:
        return False
    if isinstance(dependency, str):
        return dependency in dropped and dependency not in completed
    if dependency.op == "AND":
        return any(_is_blocked(dep, dropped, completed) for dep in dependency.deps)
    return all(_is_blocked(dep, dropped, completed) for dep in dependency.deps)


class Checkpoint(pydantic.BaseModel):
    """Base class for individual checkpoint nodes.

    Attributes:
        id: Unique node identifier within the :class:`SceneCheckpoints` graph.
            Auto-assigned from position if not provided.
        type: Discriminator for the concrete subclass (``"Event"`` or
            ``"Query"``).
        callbacks: List of :class:`~digital_actor.game_events.GameEvent` names
            emitted when this checkpoint is completed.
        dependency: Activation condition. ``None`` means the node is
            immediately active.
    """

    id: str = ""
    type: str
    callbacks: list[str] | None = None
    dependency: RequireDep | None = None


class EventCheckpoint(Checkpoint):
    """Checkpoint triggered by a named :class:`~digital_actor.game_events.GameEvent`.

    Becomes completed when a :class:`~digital_actor.game_events.GameEvent`
    with a matching ``name`` is received by the scene.

    Attributes:
        event_id: The game event name to match (e.g. ``"door_opened"``).
        narrator_message: Optional dict with ``"true"`` and/or ``"false"``
            keys mapping to narrator text injected into the history on
            completion.
    """

    type: Literal["Event"]
    event_id: str
    narrator_message: dict[Literal["true", "false"], str] | None = None
    callbacks: list[str] | None = None


class QueryCheckpoint(Checkpoint):
    """Checkpoint evaluated by asking the LLM a yes/no question about the conversation.

    The scene runs :meth:`~digital_actor.scene.SingleActorScene.run_query` with
    ``query_str`` after each actor or player turn to determine whether the
    condition has been met.

    Attributes:
        target: Which turn to evaluate — ``"Player"`` checks after the player
            speaks; ``"Actor"`` checks after the actor responds.
        query_str: A yes/no question evaluated against the conversation history
            (e.g. ``"Has the player agreed to help?"``).
        narrator_message: Optional dict with ``"true"`` and/or ``"false"``
            keys mapping to narrator text injected on each evaluation result.
    """

    type: Literal["Query"]
    target: CheckpointTarget
    query_str: str
    narrator_message: dict[Literal["true", "false"], str] | None = None
    callbacks: list[str] | None = None


class SceneCheckpoints(pydantic.BaseModel):
    """Directed acyclic graph of story checkpoints for a scene.

    Manages which nodes are active, completed, or dropped. Completing a node
    may activate downstream nodes (dependency satisfied) or drop sibling nodes
    (``OR`` branch resolved).

    Attributes:
        nodes: All checkpoint nodes in the graph, keyed by node ID.
        completed: IDs of nodes that have been completed.
        active: IDs of nodes currently eligible for evaluation.
        dropped: IDs of nodes that can no longer be reached (e.g. a sibling
            ``OR`` branch was resolved).
    """

    nodes: dict[str, EventCheckpoint | QueryCheckpoint]
    completed: set[str] = pydantic.Field(default_factory=set)
    active: set[str] = pydantic.Field(default_factory=set)
    dropped: set[str] = pydantic.Field(default_factory=set)

    def model_post_init(self, __context: object) -> None:
        self._recompute_active()

    def _recompute_active(self) -> None:
        for node_id, node in self.nodes.items():
            if node_id not in self.completed and node_id not in self.active and node_id not in self.dropped:
                if _is_satisfied(node.dependency, self.completed):
                    self.active.add(node_id)

    def complete(self, node_id: str) -> list[str]:
        """Mark ``node_id`` as completed and update the active/dropped sets.

        Completing a node may activate downstream nodes whose dependencies are
        now satisfied, and may drop alternative branches in ``OR`` expressions.

        Args:
            node_id: ID of the checkpoint to complete.

        Returns:
            List of node IDs that became newly active as a result.
        """
        self.completed.add(node_id)
        self.active.discard(node_id)
        newly_active: list[str] = []
        for nid, node in self.nodes.items():
            if nid not in self.completed and nid not in self.active and nid not in self.dropped:
                if _is_satisfied(node.dependency, self.completed):
                    self.active.add(nid)
                    newly_active.append(nid)

        to_drop: set[str] = set()
        for nid in newly_active:
            to_drop |= _collect_or_peers(self.nodes[nid].dependency, node_id)
        if to_drop:
            for drop_id in to_drop:
                self.active.discard(drop_id)
                self.dropped.add(drop_id)
            changed = True
            while changed:
                changed = False
                for nid in list(self.active):
                    if _is_blocked(self.nodes[nid].dependency, self.dropped, self.completed):
                        self.active.discard(nid)
                        self.dropped.add(nid)
                        changed = True

        return newly_active

    def active_nodes(self) -> list[EventCheckpoint | QueryCheckpoint]:
        """Return all currently active checkpoint nodes.

        Returns:
            List of active :class:`EventCheckpoint` or :class:`QueryCheckpoint`
            objects in graph definition order.
        """
        return [self.nodes[nid] for nid in self.nodes if nid in self.active]

    def any_completed(self) -> bool:
        """Return ``True`` if at least one checkpoint has been completed.

        Returns:
            ``True`` if :attr:`completed` is non-empty.
        """
        return len(self.completed) > 0

    def is_finished(self) -> bool:
        """Return ``True`` when no more checkpoints can be evaluated.

        The graph is finished when there are no active nodes and every node is
        either completed or dropped.

        Returns:
            ``True`` if the checkpoint graph has reached a terminal state.
        """
        return len(self.active) == 0 and all(nid in self.completed or nid in self.dropped for nid in self.nodes)

    @classmethod
    def from_dict(cls, graph_dict: dict) -> SceneCheckpoints:
        """Construct a :class:`SceneCheckpoints` graph from a raw dictionary.

        The dict must have a ``"nodes"`` key containing a list of node dicts.
        Each node dict must include a ``"type"`` field (``"Event"`` or
        ``"Query"``). If a node has no ``"id"`` field it is assigned ``cp_<i>``
        where ``i`` is its zero-based index in the list.

        Args:
            graph_dict: Dictionary with a ``"nodes"`` list of checkpoint dicts.

        Returns:
            A new :class:`SceneCheckpoints` instance.

        Raises:
            ValueError: If a node has an unknown ``"type"`` value.
        """
        nodes_raw: list[dict] = graph_dict["nodes"]
        nodes: dict[str, EventCheckpoint | QueryCheckpoint] = {}
        for i, raw in enumerate(nodes_raw):
            raw = dict(raw)
            node_id = raw.get("id") or f"cp_{i}"
            raw["id"] = node_id
            node_type = raw.get("type")
            if node_type == "Event":
                node = EventCheckpoint.model_validate(raw)
            elif node_type == "Query":
                node = QueryCheckpoint.model_validate(raw)
            else:
                raise ValueError(f"Unknown checkpoint type {node_type!r} at index {i}")
            nodes[node_id] = node
        return cls(nodes=nodes)
