from __future__ import annotations

import logging
import signal
import threading

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.job_worker import AutopilotJobWorker


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("agent_hub.worker_main")

    init_db()
    worker = AutopilotJobWorker(
        session_factory=SessionLocal,
        poll_interval_sec=settings.job_worker_poll_interval_sec,
        stale_timeout_sec=settings.job_stale_timeout_sec,
    )

    stop_event = threading.Event()

    def _signal_handler(signum: int, _frame) -> None:
        logger.info("worker_signal_received signum=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    worker.start()
    logger.info("worker_process_started worker_id=%s", worker.worker_id)
    try:
        while not stop_event.wait(1.0):
            continue
    finally:
        worker.stop()
        logger.info("worker_process_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
