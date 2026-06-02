"""Terminal-only driver for the MetaHuman digital actor.

Runs the conversation in the terminal with text input/output — no browser,
no WebSocket, no TTS audio. Useful for iterating on prompts and checkpoints
without spinning up the front end and proxy.

Usage::

    uv run python -m metahuman_actor.terminal --scenario zeek
    uv run python -m metahuman_actor.terminal --scenario zeek --llm cerebras/qwen-3-235b-a22b-instruct-2507

In-session commands:
    /quit | /exit | /q   — end the session
    /history             — print the conversation history
    /event <name>        — queue a GameEvent with the given name
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading

from app_logging import get_logger, setup_logging
from digital_actor.game_events import GameEvent
from digital_actor.messenger import NullMessenger, OutboundPayload
from digital_actor.runtime import Runtime
from dotenv import load_dotenv
from langfuse_utils import fetch_all_prompts_from_project, langfuse_session

from metahuman_actor.settings import settings
from metahuman_actor.stage import MetaHumanStage

load_dotenv()
setup_logging()

logger = get_logger(__name__)

# ANSI colors — match foxhole-server/terminal_simulator.py style.
_PLAYER_PROMPT = "\033[1;34m[Player]: "
_RESET = "\033[0m"
_NPC_COLOR = "\033[1;32m"
_EVENT_COLOR = "\033[2;36m"
_QUERY_COLOR = "\033[0;33m"


class TerminalMessenger(NullMessenger):
    """Prints payloads and game events directly to stdout.

    The session-routing messengers (WebSocket / gRPC) defer delivery via
    ``loop.call_soon`` so the drainer task can write to the wire on the next
    tick. In a terminal we don't want that — printing inline keeps the actor's
    line strictly before the next ``input()`` prompt.
    """

    def emit_payload(self, payload: OutboundPayload) -> None:
        if payload.text:
            _print_npc_line(payload.actor_name, payload.text)

    def emit_game_event(self, event) -> None:
        _print_event(event.name, event.info)


class _QueryConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"{_QUERY_COLOR}{record.getMessage()}{_RESET}"


class _QueryOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().startswith("Q:")


def _install_query_console_handler() -> None:
    """Print `Q: <bool> | <question>` lines from digital_actor.scene to stdout.

    digital_actor.scene logs query results at DEBUG; the default console
    handler is at INFO, so they're invisible. Attach a dedicated DEBUG-level
    handler with a `Q:` filter so we surface only the query results, not the
    rest of the debug stream.
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_QueryConsoleFormatter())
    handler.addFilter(_QueryOnlyFilter())
    scene_logger = logging.getLogger("digital_actor.scene")
    scene_logger.setLevel(logging.DEBUG)
    scene_logger.addHandler(handler)


def _print_npc_line(name: str, text: str) -> None:
    print(f"\n{_NPC_COLOR}[{name}]: {text}{_RESET}")


def _print_event(name: str, info: dict) -> None:
    suffix = f" {info}" if info else ""
    print(f"\n{_EVENT_COLOR}[event] {name}{suffix}{_RESET}")


def _print_banner(npc_name: str) -> None:
    bar = "=" * 50
    print()
    print(bar)
    print("MetaHuman Terminal Simulator")
    print(f"NPC: {npc_name}")
    print(bar)
    print("Commands: /history, /event <name>, /quit")
    print(bar)
    print()


def _start_stdin_reader(loop: asyncio.AbstractEventLoop) -> asyncio.Queue[str | None]:
    """Bridge stdin lines into an asyncio queue from a daemon thread.

    Using a daemon thread (instead of `asyncio.to_thread(input, ...)`) means a
    Ctrl-C doesn't have to wait for a blocked stdin read to unwind. The default
    executor's worker threads aren't daemon, so the atexit hook would otherwise
    join the still-blocked worker and the user would need a second Ctrl-C.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _reader() -> None:
        try:
            for line in sys.stdin:
                loop.call_soon_threadsafe(queue.put_nowait, line.rstrip("\n"))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_reader, daemon=True, name="stdin-reader").start()
    return queue


async def _run(llm_model: str, scenario: str) -> None:
    stage = MetaHumanStage(
        llm_model,
        messenger=TerminalMessenger(),
        tts_enabled=False,
    )
    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)

    await stage.load_scenario(scenario)

    _print_banner(stage.actor.name)

    stdin_queue = _start_stdin_reader(asyncio.get_running_loop())

    try:
        await stage.deliver_opening_speech()
        while True:
            print(_PLAYER_PROMPT, end="", flush=True)
            raw = await stdin_queue.get()
            print(_RESET, end="", flush=True)
            if raw is None:
                break  # stdin closed
            msg = raw.strip()
            if not msg:
                continue
            low = msg.lower()
            if low in ("/quit", "/exit", "/q"):
                print("Exiting...")
                break
            if low == "/history":
                print(stage.actor.history.to_string())
                continue
            if low.startswith("/event "):
                name = msg[len("/event ") :].strip()
                if name:
                    stage.queue_game_event(GameEvent(name=name, info={}))
                    logger.info("queued game event: %s", name)
                else:
                    logger.warning("Usage: /event <event_name>")
                continue
            await stage.on_user_input(msg)
    finally:
        await runtime.stop()


def main(llm_model: str, scenario: str) -> None:
    _install_query_console_handler()
    with langfuse_session(prompt_label=settings.digital_actor_server.prompt_label):
        fetch_all_prompts_from_project()
        try:
            asyncio.run(_run(llm_model, scenario))
        except KeyboardInterrupt:
            print(_RESET)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default="cerebras/qwen-3-235b-a22b-instruct-2507")
    parser.add_argument(
        "--scenario",
        required=True,
        help=(
            "Scenario to load (directory name under metahuman_actor/scenarios/). "
            "Required — there is no default."
        ),
    )
    args = parser.parse_args()
    main(args.llm, args.scenario)
