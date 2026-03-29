import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from app import config, database
from app.api import app, setup_logging
from app import uploader, watcher, scheduler

def main():
    config.load()
    database.init()
    setup_logging()

    uploader.start()

    cfg = config.get()
    if cfg.get("monitor_enabled", False):
        watcher.start()

    scheduler.start()

    logging.info("rclone-sync started — WebUI at http://0.0.0.0:8080")

    app.run(host="0.0.0.0", port=8080, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()
