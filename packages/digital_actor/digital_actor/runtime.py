"""Fixed-rate async tick loop for driving the stage."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress

logger = logging.getLogger(__name__)


class Runtime:
    """Fixed-rate async tick driver.

    Maintains an internal elapsed-time counter and calls all subscribed
    callbacks at every tick. Callbacks receive the current elapsed time in
    seconds. Exceptions in callbacks are logged but do not stop the loop.

    Typical usage:

    ```python
    runtime = Runtime()
    runtime.subscribe(stage.step)
    runtime.start(tick_rate=20)   # 20 Hz
    # ... later ...
    await runtime.stop()
    ```
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[[float], Awaitable[None]]] = []
        self._elapsed_time: float = 0.0
        self._tick_interval: float = 0.0
        self._task: asyncio.Task | None = None
        self.simulation_paused: bool = False

    def subscribe(self, callback: Callable[[float], Awaitable[None]]) -> None:
        """Register an async callable to be called on every tick.

        Args:
            callback: An async callable that accepts one positional argument —
                the current elapsed time in seconds (e.g. ``stage.step``).
        """
        self._callbacks.append(callback)

    def pause(self) -> None:
        """Pause the tick loop.

        Elapsed time stops advancing and callbacks are not invoked until
        :meth:`resume` is called.
        """
        self.simulation_paused = True

    def resume(self) -> None:
        """Resume the tick loop after a :meth:`pause`."""
        self.simulation_paused = False

    def start(self, tick_rate: int) -> None:
        """Start ticking at ``tick_rate`` Hz in the current event loop.

        Schedules an :class:`asyncio.Task` for the internal loop. The task
        runs until :meth:`stop` is called.

        Args:
            tick_rate: Target ticks per second. Must be at least ``1``.

        Raises:
            ValueError: If ``tick_rate`` is less than ``1``.
        """
        if tick_rate < 1:
            raise ValueError("tick_rate must be at least 1")
        self._tick_interval = 1.0 / tick_rate
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the tick task and wait for it to finish.

        Safe to call when the runtime has not been started or has already been
        stopped.
        """
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @property
    def elapsed_time(self) -> float:
        """Total simulated time elapsed in seconds since the runtime started."""
        return self._elapsed_time

    async def _run(self) -> None:
        last_tick = time.monotonic()
        while True:
            t0 = time.monotonic()
            if self.simulation_paused:
                # Hold the baseline so paused wall time isn't credited on resume.
                last_tick = t0
                await asyncio.sleep(self._tick_interval)
                continue
            self._elapsed_time += t0 - last_tick
            last_tick = t0
            for cb in self._callbacks:
                try:
                    await cb(self._elapsed_time)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("tick callback failed")
            await asyncio.sleep(max(0.0, self._tick_interval - (time.monotonic() - t0)))
