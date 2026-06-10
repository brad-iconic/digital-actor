"""Game-driven (request-driven) dialogue server.

The server produces in-character NPC lines only when the game requests one.
It owns no clock: no tick-driven behaviour, no followup/idle timers, no
playback estimation. See docs/superpowers/specs/2026-06-03-game-driven-dialogue-server-design.md.
"""
