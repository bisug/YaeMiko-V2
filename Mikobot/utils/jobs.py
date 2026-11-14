"""One-shot scheduled callbacks.

Wraps APScheduler directly for delayed execution like ``run_once``.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


class JobQueue:
    def __init__(self):
        self._scheduler = AsyncIOScheduler(timezone=UTC)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def run_once(
        self,
        callback,
        delay: float,
        *args,
        name: str | None = None,
        **kwargs,
    ) -> str:
        """Run ``callback(*args, **kwargs)`` once, ``delay`` seconds from now."""
        self.start()
        run_date = datetime.now(UTC) + timedelta(seconds=delay)
        job = self._scheduler.add_job(
            self._call,
            trigger=DateTrigger(run_date=run_date),
            args=(callback, args, kwargs),
            name=name,
        )
        return job.id

    async def _call(self, callback, args, kwargs):
        result = callback(*args, **kwargs)
        if asyncio.iscoroutine(result):
            await result

    def shutdown(self, wait: bool = False) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)


job_queue = JobQueue()
