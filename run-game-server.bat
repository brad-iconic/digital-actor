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
REM LLM: the office GPU box (nyx) is unreachable over VPN, so use a cloud model.
REM This .env's CEREBRAS_API_KEY only has access to gpt-oss-120b and zai-glm-4.7
REM (NOT qwen-3-235b, which is why the default 404s). gpt-oss-120b returns usable
REM text; zai-glm-4.7 streams only hidden reasoning and comes back empty under
REM llm_lib. For Qwen-235B parity over VPN, add NEBIUS_API_KEY to .env and use:
REM   --llm nebius/Qwen/Qwen3-235B-A22B-Instruct-2507
uv run python -m metahuman_actor.game_driven.server --port 8788 --llm cerebras/gpt-oss-120b --langfuse-local %*
pause
