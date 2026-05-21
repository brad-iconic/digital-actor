import argparse
import asyncio
import json
from pathlib import Path

from app_logging import get_logger, setup_logging
from digital_actor.messenger import MessengerType, WebSocketServer
from dotenv import load_dotenv
from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

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
    """Pauses the runtime + resets the stage on disconnect so the scene's
    followup loop doesn't keep firing LLM calls between sessions. Also resets
    on connect to clear any racey state from an in-flight tick that completed
    after the prior disconnect."""

    def __init__(self, stage, *, port: int = 8788, http_port: int | None = 8789,
                 tick_rate: int = 20) -> None:
        super().__init__(stage, port=port, tick_rate=tick_rate)
        self._http_port = http_port

    async def _handle_connection(self, ws) -> None:
        # On connect, wait for any in-flight response from a prior session to
        # finish before clearing scene state, so reset() doesn't yank the rug
        # out from under a still-running pipeline (which would leak state into
        # the new session and could corrupt history / followup scheduling).
        await self._stage.await_idle()
        self._stage.reset()
        self._runtime.resume()
        try:
            await super()._handle_connection(ws)
        finally:
            self._runtime.pause()
            # Same on disconnect: a user_input task that was dispatched right
            # before the socket closed may still be running (it was spawned
            # via create_task in _dispatch and isn't tied to the connection).
            # Wait for it to wind down before resetting state.
            await self._stage.await_idle()
            self._stage.reset()
            logger.info("client disconnected; runtime paused, stage reset")

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
                if msg.get("type") == "start_game":
                    logger.info("<<< start_game")
                    await self._stage.deliver_opening_speech()
                elif msg.get("type") == "say":
                    text = (msg.get("text") or "").strip()
                    if not text:
                        await ws.send(json.dumps({"type": "error", "message": "say: empty text"}))
                        continue
                    logger.info("<<< say: %s", text[:80])
                    asyncio.create_task(self._say_with_error_reporting(ws, text))
                else:
                    await self._dispatch(msg, ws)
            except Exception as exc:
                logger.exception("error handling %s", msg.get("type"))
                await ws.send(json.dumps({"type": "error", "message": str(exc)}))

    async def async_run(self) -> None:
        """Start the runtime, the WebSocket server, and the HTTP server."""
        import asyncio

        import websockets
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
                logger.info("HTTP TTS endpoint at http://localhost:%d/tts", self._http_port)
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


def _resolve_persona(value: str | None) -> Path | None:
    """Resolve --persona to a persona JSON path.

    Accepts a short name like ``"neutts"`` (→ ``scripts/persona_neutts.json``)
    or an absolute/relative path to a persona file. Returns ``None`` when
    ``value`` is falsy so the stage falls back to ``settings.character_persona_path``.
    """
    if not value:
        return None
    candidate = Path(value)
    if candidate.exists():
        return candidate
    named = settings.script_path / f"persona_{value}.json"
    if named.exists():
        return named
    raise FileNotFoundError(
        f"--persona {value!r}: neither {candidate} nor {named} exists"
    )


def main(
    port: int,
    llm_model: str,
    langfuse_local: bool = False,
    persona: str | None = None,
    http_port: int | None = 8789,
) -> None:
    persona_path = _resolve_persona(persona)
    session = langfuse_session(
        prompt_label=settings.digital_actor_server.prompt_label,
        local=langfuse_local,
    )
    with session:
        fetch_all_prompts_from_project()
        MetaHumanServer(
            MetaHumanStage(
                llm_model,
                messenger=MessengerType.WEBSOCKET,
                persona_path=persona_path,
            ),
            port=port,
            http_port=http_port,
        ).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default="cerebras/qwen-3-235b-a22b-instruct-2507")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--http-port", type=int, default=8789,
                        help="Port for the HTTP TTS endpoint. Default 8789.")
    parser.add_argument("--no-http", action="store_true",
                        help="Disable the HTTP TTS endpoint entirely.")
    parser.add_argument(
        "--langfuse-local",
        action="store_true",
        help="Load prompts from LOCAL_LANGFUSE_PATH (default: ./.langfuse_prompts) instead of remote Langfuse.",
    )
    parser.add_argument(
        "--persona",
        default=None,
        help=(
            "Persona to load. Short name resolves to metahuman_actor/scripts/persona_<NAME>.json "
            "(e.g. 'neutts', 'omnivoice'); a path is used as-is. Defaults to persona.json."
        ),
    )
    args = parser.parse_args()
    main(
        port=args.port,
        llm_model=args.llm,
        langfuse_local=args.langfuse_local,
        persona=args.persona,
        http_port=None if args.no_http else args.http_port,
    )
