"""Tests for the `/tts` HTTP endpoint."""
from __future__ import annotations

import struct

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


pytestmark = pytest.mark.asyncio


class _FakeTTS:
    sample_rate = 24000

    async def generate_audio(self, text: str):
        # Two 4-byte PCM frames (2 samples each at 16-bit mono).
        yield b"\x01\x00\x02\x00"
        yield b"\x03\x00\x04\x00"


class _BrokenTTS:
    sample_rate = 24000

    async def generate_audio(self, text: str):
        raise RuntimeError("provider exploded")
        yield b""  # pragma: no cover  (make this an async generator)


async def _client_for(tts_client) -> TestClient:
    from metahuman_actor.http_api import build_app

    app = build_app(tts_client_getter=lambda: tts_client)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_tts_returns_wav() -> None:
    client = await _client_for(_FakeTTS())
    try:
        resp = await client.post("/tts", json={"text": "Hi"})
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "audio/wav"
        body = await resp.read()
        # RIFF header + 8 bytes of PCM (2 chunks of 4) = 44 + 8 = 52
        assert body[:4] == b"RIFF"
        assert body[8:12] == b"WAVE"
        # Sample rate at bytes 24..28 (little-endian uint32)
        sr = struct.unpack_from("<I", body, 24)[0]
        assert sr == 24000
        # PCM payload follows the 44-byte header
        assert body[44:] == b"\x01\x00\x02\x00\x03\x00\x04\x00"
    finally:
        await client.close()


async def test_tts_rejects_empty_text() -> None:
    client = await _client_for(_FakeTTS())
    try:
        resp = await client.post("/tts", json={"text": "   "})
        assert resp.status == 400
        body = await resp.json()
        assert "error" in body
    finally:
        await client.close()


async def test_tts_503_when_no_tts_client() -> None:
    client = await _client_for(None)
    try:
        resp = await client.post("/tts", json={"text": "Hello"})
        assert resp.status == 503
    finally:
        await client.close()


async def test_tts_500_on_provider_error() -> None:
    client = await _client_for(_BrokenTTS())
    try:
        resp = await client.post("/tts", json={"text": "Hello"})
        assert resp.status == 500
        body = await resp.json()
        assert "provider exploded" in body["error"]
    finally:
        await client.close()
