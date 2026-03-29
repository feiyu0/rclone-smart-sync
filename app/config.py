import json
import os
import threading

CONFIG_PATH = "/config/config.json"

DEFAULT_CONFIG = {
    "webdav_url": "",
    "webdav_username": "",
    "webdav_password": "",
    "webdav_remote_dir": "/",
    "local_watch_dir": "/data",
    "video_extensions": [
        ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv",
        ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts",
        ".3gp", ".ogv", ".rmvb", ".vob", ".iso"
    ],
    "ignore_dirs": [
        "@eaDir", "@Recycle", "#recycle", "metadata",
        "tmp", ".tmp", "@Recently-Snapshot"
    ],
    "concurrent_uploads": 3,
    "overwrite_policy": "skip_if_same_size",
    "retry_count": 3,
    "single_file_timeout_minutes": 60,
    "monitor_enabled": False,
    "scheduler_enabled": False,
    "scheduler_time": "03:00",
    "sync_speed_limit": "10M",
    "webdav_snapshot_ttl_hours": 23,
    "log_retain_days": 30
}

_config = {}
_lock = threading.Lock()


def load():
    global _config
    with _lock:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(saved)
            _config = merged
        else:
            _config = DEFAULT_CONFIG.copy()
            _save_locked()
    return _config


def get():
    with _lock:
        if not _config:
            load()
        return dict(_config)


def update(new_values: dict):
    with _lock:
        _config.update(new_values)
        _save_locked()


def _save_locked():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(_config, f, ensure_ascii=False, indent=2)
