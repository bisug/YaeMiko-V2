"""Global rate limiting for outgoing Telegram API calls.

python-telegram-bot shipped ``AIORateLimiter``; aiogram has no equivalent
(``AiohttpSession(limit=...)`` is only an aiohttp connection-pool size), so the
bot keeps its own leaky bucket inside the session. The defaults match what the
bot relied on before: 30 requests per second overall and per method, a burst of
30, and a 50ms floor between two calls of the same method.
"""

import asyncio
import time

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import DEFAULT_TIMEOUT


class ThrottledSession(AiohttpSession):
    def __init__(
        self,
        rate: float = 30.0,
        burst: int = 30,
        min_delay: float = 0.05,
        timeout: float = DEFAULT_TIMEOUT,
        limit: int = 100,
        **kwargs,
    ):
        # aiogram's AiohttpSession takes limit as the aiohttp connection pool
        # size and forwards the rest to ClientSession, so timeout has to be
        # passed through explicitly rather than set after construction.
        super().__init__(limit=limit, timeout=timeout, **kwargs)
        self.rate = rate
        self.burst = burst
        self.min_delay = min_delay
        self._overall_bucket = [float(burst), time.monotonic()]
        self._overall_lock = asyncio.Lock()
        self._method_state: dict[str, list] = {}
        self._method_locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}

    async def _consume(self, state: list, lock: asyncio.Lock) -> None:
        async with lock:
            now = time.monotonic()
            state[0] = min(self.burst, state[0] + (now - state[1]) * self.rate)
            if state[0] < 1.0:
                await asyncio.sleep((1.0 - state[0]) / self.rate)
                now = time.monotonic()
                state[0] = min(self.burst, state[0] + (now - state[1]) * self.rate)
            state[0] -= 1.0
            state[1] = now

    async def acquire(self, method: str) -> None:
        await self._consume(self._overall_bucket, self._overall_lock)
        state = self._method_state.setdefault(method, [float(self.burst), time.monotonic()])
        await self._consume(state, self._method_locks.setdefault(method, asyncio.Lock()))
        wait = self.min_delay - (time.monotonic() - self._last_call.get(method, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call[method] = time.monotonic()

    async def make_request(self, bot, method, timeout=None):
        await self.acquire(getattr(method, "__api_method__", type(method).__name__))
        return await super().make_request(bot, method, timeout=timeout)
