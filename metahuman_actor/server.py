import argparse
import asyncio
import json

from app_logging import get_logger, setup_logging
from digital_actor.messenger import MessengerType, WebSocketServer
from dotenv import load_dotenv
from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

from metahuman_actor.scenario import list_available_scenarios
from metahuman_actor.settings import settings
from metahuman_actor.stage import MetaHumanStage

load_dotenv()
setup_logging()

logger = get_logger(__name__)

# The digital_actor package uses stdlib logging.getLogger(__name__) (so the
# package stays free of an app_logging dependency). Attach an app_logging-
# managed handler at the "digital_actor" namespace level so all child loggers
# (digital_actor.stage, digital_actor.scene, digital_actor.messenger, …) reach
# the same console + file handlers as the metahuman_actor loggers — otherwise
# every log call inside the package (LLM prompt banners, ACTOR LINE banners,
# PLAYER LINE banners, deliver_speech start/final, audio_done, …) silently
# disappears into a root logger that has no handler attached.
get_logger("digital_actor")


class MetaHumanServer(WebSocketServer):
    """WebSocket server with client-controlled scenario lifecycle.

    Starts with no scenario loaded — the client requests one via the
    `load_scenario` message. On disconnect, drains in-flight work and
    unloads the scenario via `MetaHumanStage.unload_scenario`, returning
    the stage to its empty state. Scenario-dependent inbound messages
    (`start_game`, `say`, dispatched events) are rejected with an
    `{"type": "error", "message": "no scenario loaded"}` frame when
    no scenario is active.
    """

    def __init__(
        self,
        stage,
        *,
        port: int = 8788,
        http_port: int | None = 8789,
        tick_rate: int = 20,
    ) -> None:
        super().__init__(stage, port=port, tick_rate=tick_rate)
        self._http_port = http_port
        self._pending_say_tasks: set[asyncio.Task] = set()

    async def _handle_connection(self, ws) -> None:
        # The stage starts empty (or was emptied by the prior disconnect).
        # Nothing to drain on connect.
        self._runtime.resume()
        try:
            await super()._handle_connection(ws)
        finally:
            self._runtime.pause()
            # Drain any in-flight say tasks before unloading so they can't
            # race against the scene being nulled out.
            if self._pending_say_tasks:
                await asyncio.gather(*self._pending_say_tasks, return_exceptions=True)
            await self._stage.unload_scenario()
            logger.info("client disconnected; runtime paused, scenario unloaded")

    async def _say_with_error_reporting(self, ws, text: str) -> None:
        """Drive scene.say and surface any failure to the WS client.

        Without this wrapper the create_task'd say coroutine would swallow
        exceptions into an unhandled-task warning, leaving the client
        with no audio_done and no error frame.
        """
        try:
            await self._stage._scene.say(text)
        except Exception as exc:
            logger.exception("error during say")
            try:
                await ws.send(json.dumps({"type": "error", "message": f"say: {exc}"}))
            except Exception:
                # Socket may already be closed; nothing useful to do.
                pass

    async def _handle_inbound(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"type": "error", "message": "invalid JSON"}))
                continue
            try:
                msg_type = msg.get("type")
                if msg_type == "list_scenarios":
                    active = (
                        self._stage.scenario.name if self._stage.scenario else None
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "type": "scenarios",
                                "names": list_available_scenarios(),
                                "active": active,
                            }
                        )
                    )
                    continue
                if msg_type == "unload_scenario":
                    logger.info("<<< unload_scenario")
                    await self._stage.unload_scenario()
                    await ws.send(json.dumps({"type": "scenario_unloaded"}))
                    continue
                if msg_type == "load_scenario":
                    name = (msg.get("name") or "").strip()
                    persona_variant = msg.get("persona") or None
                    if not name:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "message": "load_scenario: empty name",
                                }
                            )
                        )
                        continue
                    logger.info("<<< load_scenario: %s", name)
                    try:
                        await self._stage.load_scenario(
                            name, persona_variant=persona_variant
                        )
                    except Exception as exc:
                        logger.exception("load_scenario failed")
                        await ws.send(
                            json.dumps(
                                {"type": "error", "message": f"load_scenario: {exc}"}
                            )
                        )
                        continue
                    await ws.send(json.dumps({"type": "scenario_loaded", "name": name}))
                    # The new game-driven client does not send start_game; deliver
                    # the scene's authored opening line on load instead. Idempotent
                    # (guarded by the scene's _opening_delivered) and a no-op when
                    # there is no opening text.
                    await self._stage.deliver_opening_speech()
                    continue

                # All remaining message types require a loaded scenario.
                if self._stage.scenario is None:
                    await ws.send(
                        json.dumps(
                            {"type": "error", "message": "no scenario loaded"}
                        )
                    )
                    continue

                if msg_type == "start_game":
                    logger.info("<<< start_game")
                    await self._stage.deliver_opening_speech()
                elif msg_type == "respond":
                    # The new game-driven client sends `respond` (with extra
                    # npc/world_state/request_followup_hint/emotions fields the
                    # old authoritative server has no concept of) where this
                    # server expects a user line. Translate to on_user_input and
                    # ignore the unsupported fields.
                    text = (msg.get("text") or "").strip()
                    if not text:
                        await ws.send(
                            json.dumps(
                                {"type": "error", "message": "respond: empty text"}
                            )
                        )
                        continue
                    logger.info("<<< respond: %s", text[:80])
                    await self._stage.on_user_input(text)
                elif msg_type == "say":
                    text = (msg.get("text") or "").strip()
                    if not text:
                        await ws.send(
                            json.dumps({"type": "error", "message": "say: empty text"})
                        )
                        continue
                    logger.info("<<< say: %s", text[:80])
                    task = asyncio.create_task(self._say_with_error_reporting(ws, text))
                    self._pending_say_tasks.add(task)
                    task.add_done_callback(self._pending_say_tasks.discard)
                else:
                    await self._dispatch(msg, ws)
            except Exception as exc:
                logger.exception("error handling %s", msg.get("type"))
                await ws.send(json.dumps({"type": "error", "message": str(exc)}))

    async def async_run(self) -> None:
        """Start the runtime, the WebSocket server, and the HTTP server."""
        import asyncio

        from aiohttp import web

        from metahuman_actor.http_api import build_app

        logger.info("Starting actor runtime…")
        self._runtime.start(tick_rate=self._tick_rate)

        ws_task = asyncio.create_task(self._serve_websocket(), name="ws_server")
        tasks: list[asyncio.Task] = [ws_task]

        runner: web.AppRunner | None = None
        try:
            if self._http_port is not None:
                app = build_app(tts_client_getter=lambda: self._stage.tts_client)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, "localhost", self._http_port)
                await site.start()
                logger.info(
                    "HTTP TTS endpoint at http://localhost:%d/tts", self._http_port
                )
            await asyncio.gather(*tasks)
        finally:
            # Cancel the WS task if HTTP setup or gather raised so it
            # doesn't run on as an orphan after async_run returns.
            for t in tasks:
                if not t.done():
                    t.cancel()
            if runner is not None:
                await runner.cleanup()

    async def _serve_websocket(self) -> None:
        import websockets

        logger.info("Actor server listening on ws://localhost:%d", self._port)
        async with websockets.serve(self._handle_connection, "localhost", self._port):
            await asyncio.Future()

    def run(self) -> None:
        try:
            asyncio.run(self.async_run())
        except KeyboardInterrupt:
            logger.info("Actor server stopped")


def main(
    port: int,
    llm_model: str,
    langfuse_local: bool = False,
    http_port: int | None = 8789,
) -> None:
    session = langfuse_session(
        prompt_label=settings.digital_actor_server.prompt_label,
        local=langfuse_local,
    )
    with session:
        fetch_all_prompts_from_project()
        MetaHumanServer(
            MetaHumanStage(llm_model, messenger=MessengerType.WEBSOCKET),
            port=port,
            http_port=http_port,
        ).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default="cerebras/qwen-3-235b-a22b-instruct-2507")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument(
        "--http-port",
        type=int,
        default=8789,
        help="Port for the HTTP TTS endpoint. Default 8789.",
    )
    parser.add_argument(
        "--no-http",
        action="store_true",
        help="Disable the HTTP TTS endpoint entirely.",
    )
    parser.add_argument(
        "--langfuse-local",
        action="store_true",
        help=(
            "Load prompts from LOCAL_LANGFUSE_PATH (default: ./.langfuse_prompts) "
            "instead of remote Langfuse."
        ),
    )
    args = parser.parse_args()
    main(
        port=args.port,
        llm_model=args.llm,
        langfuse_local=args.langfuse_local,
        http_port=None if args.no_http else args.http_port,
    )
