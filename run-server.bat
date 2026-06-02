@echo off
REM Boot the metahuman websocket server.
REM
REM Pass --langfuse-local to load prompts from .langfuse_prompts\ instead of
REM remote Langfuse. Drop the flag once you have LANGFUSE_BASE_URL /
REM LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY set in .env and prompts uploaded.
uv run python -m metahuman_actor.server --port 8788 --llm nyx/RedHatAI/gemma-4-31B-it-FP8-block --langfuse-local %*
pause
