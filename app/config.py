import json
import threading
from app import database

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

_config_cache = {}
_cache_lock = threading.Lock()


def load():
    """从数据库加载配置到缓存"""
    global _config_cache
    with _cache_lock:
        db_config = database.get_all_configs()
        _config_cache = DEFAULT_CONFIG.copy()
        _config_cache.update(db_config)
    return _config_cache


def get():
    """获取当前配置（从缓存）"""
    with _cache_lock:
        if not _config_cache:
            load()
        return dict(_config_cache)


def update(new_values: dict):
    """更新配置（保存到数据库并更新缓存）"""
    with _cache_lock:
        # 更新缓存
        _config_cache.update(new_values)
        # 保存到数据库
        database.set_all_configs(_config_cache)
    return _config_cache


def reset_to_default():
    """重置所有配置为默认值"""
    with _cache_lock:
        _config_cache = DEFAULT_CONFIG.copy()
        database.set_all_configs(_config_cache)
    return _config_cache
