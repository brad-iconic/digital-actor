"""HTTP API surface for the metahuman server.

Exposes a single ``POST /tts`` endpoint that takes ``{"text": "..."}``
and returns a complete RIFF/WAVE file synthesised via the stage's TTS
client. Designed as a baseline/offline tool — it accumulates the entire
PCM stream before responding, so the resulting WAV is always
well-formed.
"""
from __future__ import annotations

import struct
from typing import Callable

from aiohttp import web


def _write_wav_header(pcm_size: int, sample_rate: int) -> bytes:
    """Return the 44-byte RIFF/WAVE header for ``pcm_size`` bytes of
    16-bit mono PCM at ``sample_rate`` Hz."""
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    return b"".join([
        b"RIFF",
        struct.pack("<I", 36 + pcm_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<I", 16),
        struct.pack("<H", 1),                    # PCM
        struct.pack("<H", num_channels),
        struct.pack("<I", sample_rate),
        struct.pack("<I", byte_rate),
        struct.pack("<H", block_align),
        struct.pack("<H", bits_per_sample),
        b"data",
        struct.pack("<I", pcm_size),
    ])


async def _extract_text(request: web.Request) -> str | None:
    """Pull ``text`` from either a JSON body or a ``text/plain`` body."""
    ctype = (request.headers.get("Content-Type") or "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        value = data.get("text")
        return value if isinstance(value, str) else None
    raw = await request.text()
    return raw if isinstance(raw, str) else None


def build_app(*, tts_client_getter: Callable[[], object | None]) -> web.Application:
    """Return an aiohttp app with the ``/tts`` route wired up.

    Args:
        tts_client_getter: Callable returning the current TTS client
            instance (or ``None`` if not configured). A callable is used
            so the route always reads the live client even if it changes.
    """
    app = web.Application()

    async def handle_tts(request: web.Request) -> web.Response:
        text = await _extract_text(request)
        if text is None or not text.strip():
            return web.json_response(
                {"error": "missing or empty 'text'"}, status=400,
            )
        tts = tts_client_getter()
        if tts is None:
            return web.json_response(
                {"error": "no TTS client configured"}, status=503,
            )
        chunks: list[bytes] = []
        try:
            async for chunk in tts.generate_audio(text):
                if chunk:
                    chunks.append(chunk)
        except Exception as exc:  # noqa: BLE001 — surface provider error
            return web.json_response({"error": str(exc)}, status=500)
        pcm = b"".join(chunks)
        wav = _write_wav_header(len(pcm), int(tts.sample_rate)) + pcm
        return web.Response(body=wav, content_type="audio/wav")

    app.router.add_post("/tts", handle_tts)
    return app
