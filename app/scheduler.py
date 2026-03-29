import schedule
import time
import threading
import logging
from app import config, syncer

logger = logging.getLogger(__name__)

_thread = None
_running = False


def start():
    global _thread, _running
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    _reschedule()
    logger.info("Scheduler started")


def stop():
    global _running
    _running = False
    schedule.clear()
    logger.info("Scheduler stopped")


def reschedule():
    _reschedule()


def _reschedule():
    schedule.clear()
    cfg = config.get()
    if not cfg.get("scheduler_enabled", False):
        logger.info("Scheduled sync disabled")
        return
    run_time = cfg.get("scheduler_time", "03:00")
    schedule.every().day.at(run_time).do(_trigger)
    logger.info(f"Scheduled sync set to {run_time} daily")


def _trigger():
    cfg = config.get()
    if not cfg.get("scheduler_enabled", False):
        return
    logger.info("Scheduled sync triggered")
    syncer.run_in_thread(triggered_by="scheduled")


def _loop():
    while _running:
        schedule.run_pending()
        time.sleep(30)
