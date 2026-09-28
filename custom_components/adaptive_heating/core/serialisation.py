"""One evaluation of a room at a time, and one more pass for whatever arrived during it."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class OneAtATime:
    """Holds a room's evaluations apart.

    An evaluation reads the room, changes the heater loops and the power watch, then awaits one
    command per heater. The heaters are watched, so the command raises a change that would start a
    second evaluation inside the first one's await, and both would write the same fields.

    Two ways in, and the difference between them is the point:

    - A sensor change or a clock tick goes through `after_a_change`. Arriving while a pass runs, it
      asks for one more pass afterwards and returns. Any number of them collapse into that single
      trailing pass, and nothing is lost by the collapse: an evaluation reads every sensor afresh
      when it runs, so one trailing pass sees the newest value of each.
    - A person's action goes through `at_once`. It waits its turn instead of collapsing, because the
      change it makes and the store write that records it both have to land before the call returns.
    """

    def __init__(self, evaluate: Callable[[], Awaitable[None]]) -> None:
        self._evaluate = evaluate
        self._lock = asyncio.Lock()
        self._another_pass = False
        self._closed = False

    @property
    def another_pass_is_wanted(self) -> bool:
        return self._another_pass

    def close(self) -> None:
        """No further pass starts. Whatever is running is the caller's to cancel."""
        self._closed = True
        self._another_pass = False

    async def after_a_change(self) -> None:
        if self._closed:
            return
        if self._lock.locked():
            self._another_pass = True
            return
        async with self._lock:
            await self._evaluate()
            await self._trailing_passes()

    async def at_once(self, act: Callable[[], Awaitable[None]]) -> None:
        if self._closed:
            return
        async with self._lock:
            await act()
            await self._trailing_passes()

    async def _trailing_passes(self) -> None:
        while self._another_pass and not self._closed:
            self._another_pass = False
            await self._evaluate()
