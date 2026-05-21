"""Outbound message routing and transport servers for digital_actor stages.

Messenger classes handle session routing; server classes wrap a stage in a
network transport. Both WebSocket and gRPC share the same dispatch interface —
override :meth:`~WebSocketServer.handle_message` /
:meth:`~GrpcServer.handle_message` to add custom inbound message types.

Usage — WebSocket::

    stage = MyStage(messenger=MessengerType.WEBSOCKET)
    WebSocketServer(stage, port=8788).main()

Usage — gRPC::

    class MyServicer(ActorServicer, GrpcServer):
        def __init__(self, stage):
            GrpcServer.__init__(self, stage)
        def deserialize_request(self, req) -> dict: ...
        async def serialize_payload(self, payload, ctx) -> None: ...
        async def serialize_game_event(self, event, ctx) -> None: ...
        async def Chat(self, request_iterator, context):
            await self._handle_session(request_iterator, context)

Wire protocol (JSON for WebSocket, dict-equivalent for gRPC):

  Inbound:
    {"type": "user_input",      "text": "..."}
    {"type": "game_event",      "name": "...", "info": {...}}
    {"type": "interrupt",       "actor_name": "...", "line_id": "...", "elapsed_seconds": 1.5}
    {"type": "audio_finished",  "line_id": "..."}
    {"type": "reset"}
    {"type": "ping"}

  Outbound (WebSocket JSON):
    {"type": "text",        "line_id": "...", "actor_name": "...", "text": "...",
                            "user_input_ack": bool, "interruptible": bool,
                            "emotion": str?, "intensity": str?}
    {"type": "audio_chunk", "line_id": "...", "data": "<base64>",
                            "sample_rate": int, "is_final": bool}
    {"type": "audio_done",  "line_id": "..."}
    {"type": "game_event",  "name": "...", "info": {...}}
    {"type": "error",       "message": "..."}
    {"type": "pong"}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import uuid4
from enum import StrEnum

import pydantic
from digital_actor.game_events import GameEvent

logger = logging.getLogger(__name__)


class MessengerType(StrEnum):
    GRPC = "grpc"
    """Use :class:`GrpcMessenger` (wraps gRPC Chat stream)."""

    WEBSOCKET = "websocket"
    """Use :class:`WebSocketMessenger` (asyncio WebSocket server)."""



class OutboundPayload(pydantic.BaseModel):
    """One outbound frame delivered to a game client."""

    model_config = pydantic.ConfigDict(frozen=True)

    actor_name: str
    text: str | None = None
    audio_chunk: bytes | None = None
    line_id: str = ""
    interruptible: bool = True
    user_input_ack: bool = False
    is_final_audio: bool = False
    tts_sample_rate: int = 0

    # Emotion metadata for the active line. Both optional; ``None`` when the
    # underlying TTS path didn't compute them. Surfaced by the Unreal client as
    # an ``OnTTSEmotion(FName Emotion, FName Intensity)`` Blueprint delegate so
    # anim BPs / UI can react to non-audio expression channels.
    emotion: str | None = None
    intensity: str | None = None


# ---------------------------------------------------------------------------
# Shared session-routing base
# ---------------------------------------------------------------------------

DeliveryHandler = Callable[[OutboundPayload], None]

current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)
"""Context variable set by :meth:`Messenger.delivering` for the active session."""


class MessageDelivery:
    """Wired delivery callback for one active session."""

    __slots__ = ("_handler",)

    def __init__(self) -> None:
        self._handler: DeliveryHandler | None = None

    def wire(self, handler: DeliveryHandler) -> None:
        """Attach ``handler`` as the active delivery callback.

        Args:
            handler: Callable that receives each :class:`OutboundPayload`.
        """
        self._handler = handler

    def clear_wiring(self) -> None:
        """Detach the delivery callback, silencing further sends."""
        self._handler = None

    @property
    def empty(self) -> bool:
        """``True`` when no handler is currently wired."""
        return self._handler is None

    def send(self, payload: OutboundPayload) -> None:
        """Deliver ``payload`` to the wired handler if one is attached.

        Args:
            payload: The outbound frame to deliver.
        """
        if self._handler is not None:
            self._handler(payload)


class Messenger(ABC):
    """Abstract outbound message router.

    Shared interface for gRPC and WebSocket transports. The stage calls
    :meth:`emit_payload` and :meth:`emit_game_event`; the transport wraps
    each connected session in :meth:`delivering` to wire up routing.
    """

    @asynccontextmanager
    async def delivering(
        self, request_id: str
    ) -> AsyncIterator[asyncio.Queue[OutboundPayload | None]]:
        """Wire delivery for one session and yield the outbound queue.

        Sets :data:`current_request_id` for the duration so :meth:`emit_payload`
        routes to this session automatically. Puts a ``None`` sentinel in the
        queue on exit so the drain loop can stop cleanly.

        Args:
            request_id: Unique identifier for this session / connection.
        """
        queue: asyncio.Queue[OutboundPayload | None] = asyncio.Queue()
        delivery = self._ensure_delivery(request_id)
        delivery.wire(lambda p: queue.put_nowait(p))
        token = current_request_id.set(request_id)
        try:
            yield queue
        finally:
            current_request_id.reset(token)
            self._release_delivery(request_id)
            queue.put_nowait(None)

    @abstractmethod
    def emit_payload(self, payload: OutboundPayload) -> None:
        """Send ``payload`` to the session identified by :data:`current_request_id`.

        Falls back to the only active session when :data:`current_request_id`
        is unset (e.g. payloads emitted by runtime tasks between requests).
        """

    def emit_payload_for_actor(self, payload: OutboundPayload) -> None:
        """Route ``payload`` via actor → session binding, or fall back to :meth:`emit_payload`.

        Used in multi-actor setups where each actor is bound to a specific
        session via :meth:`bind_actor_to_session`.
        """
        self.emit_payload(payload)

    @abstractmethod
    def emit_game_event(self, event: GameEvent) -> None:
        """Broadcast ``event`` to the game client."""

    @abstractmethod
    def game_events(self) -> AsyncIterator[GameEvent]:
        """Async iterator that yields outbound game events as they are emitted."""

    @abstractmethod
    def bind_actor_to_session(self, actor_name: str, session_id: str) -> None:
        """Route all payloads for ``actor_name`` to ``session_id``."""

    @abstractmethod
    def clear_actor_session_bindings(self) -> None:
        """Remove all actor → session bindings."""

    # --- internal session-routing helpers (implemented by concrete classes) ---

    @abstractmethod
    def _ensure_delivery(self, request_id: str) -> MessageDelivery: ...

    @abstractmethod
    def _release_delivery(self, request_id: str) -> None: ...


class _SessionMessenger(Messenger):
    """Shared session-routing implementation for gRPC and WebSocket messengers.

    Manages a dict of per-session :class:`MessageDelivery` objects and routes
    :meth:`emit_payload` to the correct one via :data:`current_request_id`.
    When no context var is set (runtime tasks between requests), falls back to
    the single active delivery if exactly one session is live.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._deliveries: dict[str, MessageDelivery] = {}
        self._actor_session: dict[str, str] = {}
        self._game_event_queue: asyncio.Queue[GameEvent] = asyncio.Queue()


    def emit_payload(self, payload: OutboundPayload) -> None:
        request_id = current_request_id.get()
        if request_id is None:
            if len(self._deliveries) == 1:
                request_id = next(iter(self._deliveries))
            else:
                logger.warning("No active session; dropping payload from %s", payload.actor_name)
                return
        self._route(request_id, payload)

    def emit_payload_for_actor(self, payload: OutboundPayload) -> None:
        session_id = self._actor_session.get(payload.actor_name)
        if session_id is not None:
            self._route(session_id, payload)
        else:
            self.emit_payload(payload)

    def bind_actor_to_session(self, actor_name: str, session_id: str) -> None:
        self._actor_session[actor_name] = session_id

    def clear_actor_session_bindings(self) -> None:
        self._actor_session.clear()

    def emit_game_event(self, event: GameEvent) -> None:
        self._game_event_queue.put_nowait(event)

    async def game_events(self) -> AsyncIterator[GameEvent]:  # type: ignore[override]
        while True:
            yield await self._game_event_queue.get()

    def _ensure_delivery(self, request_id: str) -> MessageDelivery:
        delivery = self._deliveries.get(request_id)
        if delivery is None:
            delivery = MessageDelivery()
            self._deliveries[request_id] = delivery
            self._refresh_loop()
        return delivery

    def _release_delivery(self, request_id: str) -> None:
        delivery = self._deliveries.get(request_id)
        if delivery is not None:
            delivery.clear_wiring()
            if delivery.empty:
                del self._deliveries[request_id]
                self._refresh_loop()

    def _refresh_loop(self) -> None:
        if self._deliveries:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        else:
            self._loop = None

    def _route(self, request_id: str, payload: OutboundPayload) -> None:
        delivery = self._deliveries.get(request_id)
        if delivery is None or delivery.empty:
            logger.warning("No delivery wired for %r; dropping payload from %s", request_id, payload.actor_name)
            return
        if self._loop is None:
            return
        fn = lambda: delivery.send(payload)  # noqa: E731
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.call_soon(fn)
        else:
            self._loop.call_soon_threadsafe(fn)


# ---------------------------------------------------------------------------
# gRPC messenger
# ---------------------------------------------------------------------------

class GrpcMessenger(_SessionMessenger):
    """Messenger for gRPC.

    Wrap each Chat RPC handler in :meth:`~Messenger.delivering` to wire the
    outbound queue for that session::

        async def Chat(self, request_iterator, context):
            async with messenger.delivering(context.peer()) as queue:
                # drain queue → gRPC stream
                ...
    """


# ---------------------------------------------------------------------------
# WebSocket messenger
# ---------------------------------------------------------------------------

class WebSocketMessenger(_SessionMessenger):
    """Messenger for asyncio WebSocket servers."""


# ---------------------------------------------------------------------------
# Null messenger
# ---------------------------------------------------------------------------

class NullMessenger(Messenger):
    """Discards all payloads and events. Used when no transport is configured."""

    def emit_payload(self, payload: OutboundPayload) -> None:
        pass

    def emit_game_event(self, event: GameEvent) -> None:
        pass

    async def game_events(self) -> AsyncIterator[GameEvent]:  # type: ignore[override]
        return
        yield  # pragma: no cover

    def bind_actor_to_session(self, actor_name: str, session_id: str) -> None:
        pass

    def clear_actor_session_bindings(self) -> None:
        pass

    def _ensure_delivery(self, request_id: str) -> MessageDelivery:
        return MessageDelivery()

    def _release_delivery(self, request_id: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _coerce_messenger_type(kind: MessengerType | str) -> MessengerType:
    if isinstance(kind, MessengerType):
        return kind
    try:
        return MessengerType(kind)
    except ValueError:
        known = ", ".join(repr(m.value) for m in MessengerType)
        raise ValueError(f"Unknown messenger type {kind!r} (expected one of {known}).")


def create_messenger(kind: MessengerType | str = MessengerType.GRPC) -> Messenger:
    """Instantiate a :class:`Messenger` from a :class:`MessengerType` or string."""
    match _coerce_messenger_type(kind):
        case MessengerType.GRPC:
            return GrpcMessenger()
        case MessengerType.WEBSOCKET:
            return WebSocketMessenger()


# ---------------------------------------------------------------------------
# Transport servers
# ---------------------------------------------------------------------------

def _payload_to_ws_frame(payload: OutboundPayload) -> dict | None:
    if payload.text is not None:
        # Stage.deliver_text already prints a full ACTOR LINE banner with
        # the same content; emit a short wire-confirmation here so we can
        # tell the frame actually left the server without duplicating the
        # full text in the log stream.
        logger.info(
            ">>> sent text frame: actor=%s line=%s len=%d",
            payload.actor_name,
            payload.line_id,
            len(payload.text),
        )
        frame = {
            "type": "text",
            "line_id": payload.line_id,
            "actor_name": payload.actor_name,
            "text": payload.text,
            "user_input_ack": payload.user_input_ack,
            "interruptible": payload.interruptible,
        }
        if payload.emotion is not None:
            frame["emotion"] = payload.emotion
        if payload.intensity is not None:
            frame["intensity"] = payload.intensity
        return frame
    if payload.audio_chunk:
        # Per-chunk logs would flood (dozens per utterance); rely on the Stage layer's
        # deliver_speech log and the audio_done close. Skip entirely.
        return {
            "type": "audio_chunk",
            "line_id": payload.line_id,
            "data": base64.b64encode(payload.audio_chunk).decode(),
            "sample_rate": payload.tts_sample_rate,
            "is_final": payload.is_final_audio,
        }
    if payload.is_final_audio:
        logger.info(">>> audio_done: line=%s", payload.line_id)
        return {"type": "audio_done", "line_id": payload.line_id}
    return None


class _ServerBase:
    """Shared inbound dispatch logic for WebSocket and gRPC servers."""

    def __init__(self, stage: "BaseStage", tick_rate: int = 20) -> None:  # type: ignore[name-defined]
        from digital_actor.runtime import Runtime
        self._stage = stage
        self._tick_rate = tick_rate
        self._runtime = Runtime()
        self._runtime.subscribe(stage.step)

    @property
    def stage(self) -> "BaseStage":  # type: ignore[name-defined]
        return self._stage

    async def _dispatch(self, msg: dict, transport) -> None:
        """Handle built-in message types. Call from :meth:`_handle_inbound`."""
        from digital_actor.game_events import GameEvent, PlayerInterruptEvent
        msg_type = msg.get("type")
        if msg_type == "user_input":
            text = msg.get("text", "").strip()
            if text:
                logger.info(
                    "─── PLAYER LINE ───────────────────────────────────────────────\n%s\n──────────────────────────────────────────────────────────────",
                    text,
                )
                asyncio.create_task(self._stage.on_user_input(text))
        elif msg_type == "game_event":
            name = msg.get("name", "")
            info = {str(k): str(v) for k, v in (msg.get("info") or {}).items()}
            logger.info("<<< game_event: %s %s", name, info)
            self._stage.queue_game_event(GameEvent(name=name, info=info))
        elif msg_type == "interrupt":
            logger.info(
                "<<< interrupt: actor=%s line=%s elapsed=%.2fs",
                msg.get("actor_name"),
                msg.get("line_id"),
                float(msg.get("elapsed_seconds", 0.0)),
            )
            self._stage.queue_game_event(PlayerInterruptEvent(
                actor_name=msg.get("actor_name", ""),
                line_id=msg.get("line_id", ""),
                elapsed_seconds=float(msg.get("elapsed_seconds", 0.0)),
            ))
        elif msg_type == "audio_finished":
            line_id = msg.get("line_id", "")
            logger.info("<<< audio_finished: line=%s", line_id)
            asyncio.create_task(self._stage.on_audio_finished(line_id))
        elif msg_type == "reset":
            logger.info("<<< reset")
            self._stage.reset()
            await self._send_reset_ack(transport)
        elif msg_type == "ping":
            # keepalive; silent
            await self._send_pong(transport)
        else:
            logger.warning("Unknown message type: %s", msg_type)

    async def _send_reset_ack(self, transport) -> None: ...
    async def _send_pong(self, transport) -> None: ...


class WebSocketServer(_ServerBase):
    """WebSocket server for a digital_actor stage.

    Handles connection lifecycle, frame serialisation, and outbound delivery.
    Override :meth:`_handle_inbound` to customise message handling; call
    ``await self._dispatch(msg, ws)`` inside it for built-in type handling.

    Usage (no custom messages)::

        stage = MyStage(messenger=MessengerType.WEBSOCKET)
        WebSocketServer(stage, port=8788).main()

    Usage (custom messages)::

        class MyServer(WebSocketServer):
            async def _handle_inbound(self, ws):
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "my_event":
                        ...
                    else:
                        await self._dispatch(msg, ws)
    """

    def __init__(self, stage: "BaseStage", port: int = 8788, tick_rate: int = 20) -> None:  # type: ignore[name-defined]
        super().__init__(stage, tick_rate)
        self._port = port

    async def _send_reset_ack(self, ws) -> None:
        import websockets
        if isinstance(ws, websockets.ServerConnection):
            await ws.send(json.dumps({"type": "game_event", "name": "reset_ack", "info": {}}))

    async def _send_pong(self, ws) -> None:
        import websockets
        if isinstance(ws, websockets.ServerConnection):
            await ws.send(json.dumps({"type": "pong"}))

    async def _drain_outbound(self, ws, queue: asyncio.Queue) -> None:
        # Per-line audio chunk indices for send-side timing diagnostics.
        # Keyed by line_id; ticks once per audio_chunk frame sent.
        sent_index: dict[str, int] = {}
        sent_prev_ts: dict[str, float] = {}
        while True:
            payload = await queue.get()
            if payload is None:
                break
            try:
                frame = _payload_to_ws_frame(payload)
                if frame is None:
                    continue
                t_before = time.monotonic()
                await ws.send(json.dumps(frame))
                t_after = time.monotonic()
                if frame.get("type") == "audio_chunk":
                    lid = payload.line_id
                    idx = sent_index.get(lid, 0) + 1
                    sent_index[lid] = idx
                    prev = sent_prev_ts.get(lid)
                    sent_prev_ts[lid] = t_after
                    delta_ms = 0 if prev is None else int(round((t_after - prev) * 1000))
                    send_ms = int(round((t_after - t_before) * 1000))
                    logger.debug(
                        "speech chunk sent #%d line=%s send=%dms +%dms_sent",
                        idx, lid, send_ms, delta_ms,
                    )
                elif frame.get("type") == "audio_done":
                    # Clean up per-line tracking when the line closes.
                    sent_index.pop(payload.line_id, None)
                    sent_prev_ts.pop(payload.line_id, None)
            except Exception:
                logger.exception("Failed to send payload frame")

    async def _drain_game_events(self, ws) -> None:
        try:
            async for event in self._stage.messenger.game_events():
                frame = {"type": "game_event", "name": event.name, "info": event.info}
                try:
                    await ws.send(json.dumps(frame))
                except Exception:
                    logger.exception("Failed to send game event")
        except asyncio.CancelledError:
            pass

    async def _handle_inbound(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"type": "error", "message": "invalid JSON"}))
                continue
            try:
                await self._dispatch(msg, ws)
            except Exception as exc:
                logger.exception("Error handling message type=%s", msg.get("type"))
                await ws.send(json.dumps({"type": "error", "message": str(exc)}))

    async def _handle_connection(self, ws) -> None:
        session_id = str(uuid4())
        logger.info("[session %s] connected", session_id[:8])
        async with self._stage.messenger.delivering(session_id) as queue:
            event_task = asyncio.create_task(self._drain_game_events(ws), name=f"game_events_{session_id[:8]}")
            inbound_task = asyncio.create_task(self._handle_inbound(ws), name=f"inbound_{session_id[:8]}")
            outbound_task = asyncio.create_task(self._drain_outbound(ws, queue), name=f"outbound_{session_id[:8]}")
            try:
                await asyncio.wait([inbound_task, outbound_task], return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in [inbound_task, outbound_task, event_task]:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
        logger.info("[session %s] disconnected", session_id[:8])

    async def async_run(self) -> None:
        """Start the runtime and serve forever."""
        import websockets
        logger.info("Starting actor runtime…")
        self._runtime.start(tick_rate=self._tick_rate)
        logger.info("Actor server listening on ws://localhost:%d", self._port)
        async with websockets.serve(self._handle_connection, "localhost", self._port):
            await asyncio.Future()

    def run(self) -> None:
        """Synchronous entry point. Runs until KeyboardInterrupt."""
        try:
            asyncio.run(self.async_run())
        except KeyboardInterrupt:
            logger.info("Actor server stopped")


class GrpcServer(_ServerBase, ABC):
    """Base class for gRPC digital_actor servicers.

    Provides the same dispatch interface as :class:`WebSocketServer`. Subclass
    alongside your proto-generated servicer and implement the three abstract
    conversion methods.

    Usage::

        class MyServicer(ActorServicer, GrpcServer):
            def __init__(self, stage):
                GrpcServer.__init__(self, stage)

            def deserialize_request(self, request) -> dict:
                return {"type": request.type, "text": request.text}

            async def serialize_payload(self, payload, context) -> None:
                await context.write(ActorResponse(text=payload.text or ""))

            async def serialize_game_event(self, event, context) -> None:
                await context.write(ActorResponse(event_name=event.name))

            async def Chat(self, request_iterator, context):
                await self._handle_session(request_iterator, context)
    """

    def start_runtime(self) -> None:
        """Start the tick loop. Call once before accepting connections."""
        self._runtime.start(tick_rate=self._tick_rate)

    @abstractmethod
    def deserialize_request(self, request) -> dict:
        """Convert a proto request to a dict with a ``type`` key."""

    @abstractmethod
    async def serialize_payload(self, payload: OutboundPayload, context) -> None:
        """Write one :class:`OutboundPayload` to the gRPC context."""

    @abstractmethod
    async def serialize_game_event(self, event, context) -> None:
        """Write one game event to the gRPC context."""

    async def _send_reset_ack(self, context) -> None:
        pass  # subclass may override to send a typed reset_ack response

    async def _send_pong(self, context) -> None:
        pass

    async def _drain_outbound(self, queue: asyncio.Queue, context) -> None:
        while True:
            payload = await queue.get()
            if payload is None:
                break
            try:
                await self.serialize_payload(payload, context)
            except Exception:
                logger.exception("Failed to send payload")

    async def _drain_game_events(self, context) -> None:
        try:
            async for event in self._stage.messenger.game_events():
                try:
                    await self.serialize_game_event(event, context)
                except Exception:
                    logger.exception("Failed to send game event")
        except asyncio.CancelledError:
            pass

    async def _handle_inbound(self, request_iterator, context) -> None:
        """Override to customise inbound handling. Call self._dispatch(msg, context) for built-ins."""
        async for request in request_iterator:
            try:
                msg = self.deserialize_request(request)
                await self._dispatch(msg, context)
            except Exception:
                logger.exception("Error handling request")

    async def _handle_session(self, request_iterator, context) -> None:
        """Drive one gRPC streaming session. Call from your Chat RPC handler."""
        session_id = context.peer() if hasattr(context, "peer") else str(uuid4())
        logger.info("[session %s] connected", session_id[:8])
        async with self._stage.messenger.delivering(session_id) as queue:
            event_task = asyncio.create_task(self._drain_game_events(context), name=f"game_events_{session_id[:8]}")
            inbound_task = asyncio.create_task(self._handle_inbound(request_iterator, context), name=f"inbound_{session_id[:8]}")
            outbound_task = asyncio.create_task(self._drain_outbound(queue, context), name=f"outbound_{session_id[:8]}")
            try:
                await asyncio.wait([inbound_task, outbound_task], return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in [inbound_task, outbound_task, event_task]:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
        logger.info("[session %s] disconnected", session_id[:8])
