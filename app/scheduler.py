from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime

from .collector import collect_all_once
from .db import WeatherDatabase

logger = logging.getLogger(__name__)


class CollectorScheduler:
    def __init__(self, db: WeatherDatabase, interval_seconds: int = 300):
        self.db = db
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._scheduler = None

    def start(self) -> None:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            self._scheduler = AsyncIOScheduler()
            self._scheduler.add_job(
                self.run_once_safely,
                "interval",
                seconds=self.interval_seconds,
                next_run_time=datetime.now(),
                max_instances=1,
                coalesce=True,
            )
            self._scheduler.start()
        except ImportError:
            self._task = asyncio.create_task(self._fallback_loop())

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
        if self._task is not None:
            self._task.cancel()

    def run_once_safely(self) -> None:
        try:
            collect_all_once(self.db, raise_on_weather_error=False)
        except Exception:
            logger.exception("SMG collection failed")

    async def _fallback_loop(self) -> None:
        while True:
            await asyncio.to_thread(self.run_once_safely)
            with suppress(asyncio.CancelledError):
                await asyncio.sleep(self.interval_seconds)
