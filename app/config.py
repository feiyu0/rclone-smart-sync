import threading

DEFAULT_CONFIG = {
    "webdav_url":                  "",
    "webdav_username":             "",
    "webdav_password":             "",
    "webdav_remote_dir":           "/",
    "local_watch_dir":             "/data",
    "video_extensions": [
        ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv",
        ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts",
        ".3gp", ".ogv", ".rmvb", ".vob", ".iso"
    ],
    "ignore_dirs": [
        "@eaDir", "@Recycle", "#recycle", "metadata",
        "tmp", ".tmp", "@Recently-Snapshot"
    ],
    "concurrent_uploads":          3,
    "overwrite_policy":            "skip_if_same_size",
    "retry_count":                 3,
    "single_file_timeout_minutes": 60,
    "monitor_enabled":             False,
    "scheduler_enabled":           False,
    "scheduler_time":              "03:00",
    "sync_speed_limit":            "10M",
    "webdav_snapshot_ttl_hours":   23,
    "log_retain_days":             30,
}

_lock = threading.Lock()


def load():
    from app import database
    existing = database.config_get_all()
    missing = {k: v for k, v in DEFAULT_CONFIG.items() if k not in existing}
    if missing:
        database.config_set_many(missing)


def get() -> dict:
    from app import database
    with _lock:
        stored = database.config_get_all()
    result = dict(DEFAULT_CONFIG)
    result.update(stored)
    return result


def update(new_values: dict):
    from app import database
    with _lock:
        database.config_set_many(new_values)
