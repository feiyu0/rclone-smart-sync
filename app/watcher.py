import os
import logging
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from app import config, uploader

logger = logging.getLogger(__name__)

_observer = None
_observer_lock = threading.Lock()


class VideoFileHandler(FileSystemEventHandler):

    def on_closed(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def _handle(self, path):
        cfg = config.get()

        ext = os.path.splitext(path)[1].lower()
        if ext not in cfg.get("video_extensions", []):
            return

        parts = path.replace("\\", "/").split("/")
        for part in parts:
            if part in cfg.get("ignore_dirs", []):
                logger.debug(f"Ignored dir match, skip: {path}")
                return

        if not os.path.exists(path):
            return

        file_size = os.path.getsize(path)
        if file_size == 0:
            return

        watch_dir = cfg.get("local_watch_dir", "/data").rstrip("/")
        rel = os.path.relpath(path, watch_dir)
        remote_dir = cfg.get("webdav_remote_dir", "/").rstrip("/")
        remote_path = f"{remote_dir}/{rel}".replace("\\", "/")

        uploader.enqueue(
            local_path=path,
            remote_path=remote_path,
            file_size=file_size,
            priority=10,
            source="monitor",
        )


def start():
    global _observer
    with _observer_lock:
        if _observer is not None and _observer.is_alive():
            logger.info("Watcher already running")
            return

        cfg = config.get()
        watch_dir = cfg.get("local_watch_dir", "/data")

        if not os.path.isdir(watch_dir):
            logger.error(f"Watch directory does not exist: {watch_dir}")
            return

        handler = VideoFileHandler()
        _observer = Observer()
        _observer.schedule(handler, watch_dir, recursive=True)
        _observer.start()
        logger.info(f"Watcher started: {watch_dir}")


def stop():
    global _observer
    with _observer_lock:
        if _observer is not None and _observer.is_alive():
            _observer.stop()
            _observer.join(timeout=5)
            _observer = None
            logger.info("Watcher stopped")


def is_running():
    with _observer_lock:
        return _observer is not None and _observer.is_alive()
