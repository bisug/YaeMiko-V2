"""One-shot scheduled callbacks.

python-telegram-bot shipped a job queue through its ``[job-queue]`` extra, which
was APScheduler; aiogram has no scheduler at all. The bot only ever needs
``run_once`` (deleting a join message after a delay), so this wraps APScheduler
directly and keeps the call shape the plugins already use.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


class JobQueue:
    def __init__(self):
        self._scheduler = AsyncIOScheduler(timezone=timezone.utc)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def run_once(self, callback, delay: float, *args, **kwargs) -> str:
        """Run ``callback(*args, **kwargs)`` once, ``delay`` seconds from now."""
        self.start()
        run_date = datetime.now(timezone.utc) + timedelta(seconds=delay)
        job = self._scheduler.add_job(
            self._call,
            trigger=DateTrigger(run_date=run_date),
            args=(callback, args, kwargs),
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
