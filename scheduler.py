from __future__ import annotations

import threading

from config import CHECK_INTERVAL_SECONDS


class PowerStateScheduler:
    def __init__(self, monitor_service):
        self.monitor_service = monitor_service
        self._stop_event = threading.Event()

    def run_forever(self):
        while not self._stop_event.is_set():
            self.monitor_service.mark_missing_power()
            self._stop_event.wait(CHECK_INTERVAL_SECONDS)

    def stop(self):
        self._stop_event.set()
