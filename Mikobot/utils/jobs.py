"""One-shot delayed callbacks.

A task per callback is enough for the bot's single 120 s verification timer.
The task is held until it finishes so a failure can be logged.
"""

import asyncio

from Mikobot.logger import LOGGER


class JobQueue:
    def __init__(self):
        self._tasks: set[asyncio.Task] = set()

    def run_once(
        self,
        callback,
        delay: float,
        *args,
        name: str | None = None,
        **kwargs,
    ) -> None:
        """Run ``callback(*args, **kwargs)`` once, ``delay`` seconds from now."""

        async def run():
            await asyncio.sleep(delay)
            result = callback(*args, **kwargs)
            if asyncio.iscoroutine(result):
                await result

        task = asyncio.create_task(run(), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._report)

    @staticmethod
    def _report(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            LOGGER.error("Scheduled job failed", exc_info=error)

    def shutdown(self, wait: bool = False) -> None:
        for task in list(self._tasks):
            task.cancel()


job_queue = JobQueue()
