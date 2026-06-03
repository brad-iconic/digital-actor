@echo off
REM Boot the game-driven (request-driven) metahuman websocket server.
REM
REM Unlike run-server.bat (the authoritative runtime), this server produces
REM lines only when the game requests them (respond / trigger / set_scene /
REM set_interaction). It owns no clock. New-layout scenarios live under
REM .langfuse_prompts\scenarios\<name>\ (e.g. zeek_gd).
REM
REM Pass --langfuse-local to load prompts from .langfuse_prompts\ instead of
REM remote Langfuse. Drop the flag once you have LANGFUSE_BASE_URL /
REM LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY set in .env and prompts uploaded.
uv run python -m metahuman_actor.game_driven.server --port 8788 --llm nyx/RedHatAI/gemma-4-31B-it-FP8-block --langfuse-local %*
pause
