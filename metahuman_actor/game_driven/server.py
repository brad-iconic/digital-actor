"""WebSocket server for the game-driven dialogue path.

Implements the request-driven wire protocol (respond/trigger/set_scene/
set_interaction). Dialogue text/audio frames flow through the messenger's
outbound drain (inherited from WebSocketServer); the new control/hint frames
are sent directly over the socket here.
"""
from __future__ import annotations

import argparse
import json

from app_logging import get_logger, setup_logging
from digital_actor.messenger import MessengerType, WebSocketServer
from dotenv import load_dotenv
from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

from metahuman_actor.game_driven.scenario import list_game_driven_scenarios
from metahuman_actor.game_driven.stage import GameDrivenStage
from metahuman_actor.settings import settings

logger = get_logger(__name__)
get_logger("digital_actor")


class GameDrivenServer(WebSocketServer):
    def __init__(
        self, stage: GameDrivenStage, *, port: int = 8788, tick_rate: int = 20
    ) -> None:
        super().__init__(stage, port=port, tick_rate=tick_rate)

    async def _handle_connection(self, ws) -> None:
        self._runtime.resume()
        try:
            await super()._handle_connection(ws)
        finally:
            self._runtime.pause()
            await self._stage.unload_scenario()
            logger.info("client disconnected; scenario unloaded")

    async def _handle_inbound(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"type": "error", "message": "invalid JSON"}))
                continue
            await self._handle_message(msg, ws)

    async def _handle_message(self, msg: dict, ws) -> None:
        msg_type = msg.get("type")
        stage: GameDrivenStage = self._stage
        logger.info("<<< %s", msg_type)
        try:
            if msg_type == "list_scenarios":
                active = stage.scenario.name if stage.scenario else None
                await ws.send(
                    json.dumps(
                        {
                            "type": "scenarios",
                            "names": list_game_driven_scenarios(),
                            "active": active,
                        }
                    )
                )
                return

            if msg_type == "load_scenario":
                name = (msg.get("name") or "").strip()
                if not name:
                    await ws.send(
                        json.dumps(
                            {"type": "error", "message": "load_scenario: empty name"}
                        )
                    )
                    return
                await stage.load_scenario(name)
                await ws.send(
                    json.dumps(
                        {
                            "type": "scenario_loaded",
                            "name": name,
                            "scene": stage.current_scene,
                            "interactions": {
                                stage.actor.actor_id: stage.current_interaction
                            },
                        }
                    )
                )
                return

            if msg_type == "unload_scenario":
                await stage.unload_scenario()
                await ws.send(json.dumps({"type": "scenario_unloaded"}))
                return

            # Everything below requires a loaded scenario.
            if stage.scenario is None:
                await ws.send(
                    json.dumps({"type": "error", "message": "no scenario loaded"})
                )
                return

            if msg_type == "set_scene":
                scene = (msg.get("scene") or "").strip()
                await stage.set_scene(scene)
                await ws.send(
                    json.dumps(
                        {
                            "type": "scene_changed",
                            "scene": stage.current_scene,
                            "interactions": {
                                stage.actor.actor_id: stage.current_interaction
                            },
                        }
                    )
                )
                return

            if msg_type == "set_interaction":
                npc = (msg.get("npc") or "").strip()
                interaction = (msg.get("interaction") or "").strip()
                await stage.set_interaction(npc, interaction)
                await ws.send(
                    json.dumps(
                        {
                            "type": "interaction_changed",
                            "npc": npc,
                            "interaction": stage.current_interaction,
                        }
                    )
                )
                return

            if msg_type == "respond":
                npc = (msg.get("npc") or "").strip()
                self._validate_npc(npc)
                text = (msg.get("text") or "").strip()
                if not text:
                    await ws.send(
                        json.dumps({"type": "error", "message": "respond: empty text"})
                    )
                    return
                world_state = msg.get("world_state") or {}
                request_followup = bool(msg.get("request_followup_hint", False))
                emotions = msg.get("emotions")
                # respond_with_hint/trigger_with_hint aren't on the stage's
                # public API (its on_user_input doesn't return the hint), so the
                # server reaches the scene directly for the hint-bearing path.
                _, hint = await stage._scene.respond_with_hint(
                    text,
                    world_state,
                    emotions=emotions,
                    request_followup_hint=request_followup,
                )
                await self._maybe_send_hint(ws, npc, hint)
                return

            if msg_type == "trigger":
                npc = (msg.get("npc") or "").strip()
                self._validate_npc(npc)
                name = (msg.get("name") or "").strip()
                info = {
                    str(k): str(v) for k, v in (msg.get("info") or {}).items()
                }
                world_state = msg.get("world_state") or {}
                request_followup = bool(msg.get("request_followup_hint", False))
                _, hint = await stage._scene.trigger_with_hint(
                    name,
                    info,
                    world_state,
                    request_followup_hint=request_followup,
                )
                await self._maybe_send_hint(ws, npc, hint)
                return

            await ws.send(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"unknown message type {msg_type!r}",
                    }
                )
            )
        except Exception as exc:
            logger.exception("error handling %s", msg_type)
            await ws.send(json.dumps({"type": "error", "message": str(exc)}))

    def _validate_npc(self, npc: str) -> None:
        stage: GameDrivenStage = self._stage
        if stage.actor is None or npc != stage.actor.actor_id:
            raise ValueError(f"unknown npc {npc!r}")

    async def _maybe_send_hint(self, ws, npc: str, hint) -> None:
        if hint is None:
            return
        await ws.send(
            json.dumps(
                {
                    "type": "followup_hint",
                    "npc": npc,
                    "line_id": hint.line_id,
                    "available": hint.available,
                    "suggested_delay_seconds": hint.suggested_delay_seconds,
                }
            )
        )


def main(port: int, llm_model: str, langfuse_local: bool = False) -> None:
    session = langfuse_session(
        prompt_label=settings.digital_actor_server.prompt_label,
        local=langfuse_local,
    )
    with session:
        fetch_all_prompts_from_project()
        GameDrivenServer(
            GameDrivenStage(llm_model, messenger=MessengerType.WEBSOCKET),
            port=port,
        ).run()


if __name__ == "__main__":
    load_dotenv()
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default="cerebras/qwen-3-235b-a22b-instruct-2507")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--langfuse-local", action="store_true")
    args = parser.parse_args()
    main(port=args.port, llm_model=args.llm, langfuse_local=args.langfuse_local)
