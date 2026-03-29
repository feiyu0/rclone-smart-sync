import sqlite3
import os
import threading
from datetime import datetime

DB_PATH = "/config/sync.db"
_local = threading.local()


def _conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


def init():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS app_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at  TEXT    NOT NULL,
            level      TEXT    NOT NULL,
            message    TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS upload_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            local_path  TEXT    NOT NULL,
            remote_path TEXT    NOT NULL,
            file_size   INTEGER,
            uploaded_at TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'success'
        );

        CREATE TABLE IF NOT EXISTS webdav_snapshot (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            remote_path TEXT    NOT NULL UNIQUE,
            file_size   INTEGER,
            synced_at   TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sync_tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            triggered_by TEXT    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'pending',
            started_at   TEXT,
            finished_at  TEXT,
            total        INTEGER DEFAULT 0,
            done         INTEGER DEFAULT 0,
            failed       INTEGER DEFAULT 0,
            skipped      INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_upload_local  ON upload_history(local_path);
        CREATE INDEX IF NOT EXISTS idx_snapshot_path ON webdav_snapshot(remote_path);
        CREATE INDEX IF NOT EXISTS idx_logs_at       ON app_logs(logged_at);
    """)
    c.commit()


# ── Config ────────────────────────────────────────────────

def config_get_all():
    import json
    c = _conn()
    rows = c.execute("SELECT key, value FROM app_config").fetchall()
    result = {}
    for row in rows:
        try:
            result[row["key"]] = json.loads(row["value"])
        except Exception:
            result[row["key"]] = row["value"]
    return result


def config_set(key: str, value):
    import json
    c = _conn()
    c.execute(
        "INSERT INTO app_config (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False))
    )
    c.commit()


def config_set_many(mapping: dict):
    import json
    c = _conn()
    c.executemany(
        "INSERT INTO app_config (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(k, json.dumps(v, ensure_ascii=False)) for k, v in mapping.items()]
    )
    c.commit()


# ── Logs ──────────────────────────────────────────────────

def log_insert(level: str, message: str):
    c = _conn()
    c.execute(
        "INSERT INTO app_logs (logged_at, level, message) VALUES (?, ?, ?)",
        (datetime.now().strftime("%H:%M:%S"), level, message)
    )
    c.commit()


def log_query(level_filter="all", limit=300):
    c = _conn()
    if level_filter == "error":
        rows = c.execute(
            "SELECT logged_at, level, message FROM app_logs"
            " WHERE level IN ('ERROR','WARNING')"
            " ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    elif level_filter == "success":
        rows = c.execute(
            "SELECT logged_at, level, message FROM app_logs"
            " WHERE message LIKE '%Done%' OR message LIKE '%成功%'"
            " ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT logged_at, level, message FROM app_logs"
            " ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {"time": r["logged_at"], "level": r["level"], "message": r["message"]}
        for r in reversed(rows)
    ]


def log_clear():
    c = _conn()
    c.execute("DELETE FROM app_logs")
    c.commit()


def log_purge_old(retain_days: int):
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=retain_days)).strftime("%H:%M:%S")
    c = _conn()
    c.execute(
        "DELETE FROM app_logs WHERE id IN ("
        "  SELECT id FROM app_logs ORDER BY id ASC LIMIT MAX(0,"
        "    (SELECT COUNT(*) FROM app_logs) - ?)"
        ")", (retain_days * 1000,)
    )
    c.commit()


# ── Upload history ────────────────────────────────────────

def record_upload(local_path, remote_path, file_size, status="success"):
    c = _conn()
    c.execute(
        "INSERT INTO upload_history"
        " (local_path, remote_path, file_size, uploaded_at, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (local_path, remote_path, file_size, datetime.now().isoformat(), status)
    )
    c.commit()


def get_upload_stats():
    c = _conn()
    today = datetime.now().strftime("%Y-%m-%d")
    row = c.execute(
        "SELECT"
        "  COUNT(*) as total,"
        "  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,"
        "  SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) as failed"
        " FROM upload_history WHERE uploaded_at LIKE ?",
        (today + "%",)
    ).fetchone()
    total_row = c.execute(
        "SELECT COUNT(*) as total, SUM(file_size) as total_bytes"
        " FROM upload_history WHERE status='success'"
    ).fetchone()
    return {
        "today_total":     row["total"]             or 0,
        "today_success":   row["success"]           or 0,
        "today_failed":    row["failed"]            or 0,
        "all_time_total":  total_row["total"]       or 0,
        "all_time_bytes":  total_row["total_bytes"] or 0,
    }


def get_recent_uploads(limit=200):
    c = _conn()
    rows = c.execute(
        "SELECT * FROM upload_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── WebDAV snapshot ───────────────────────────────────────

def upsert_snapshot(remote_path, file_size):
    c = _conn()
    c.execute(
        "INSERT INTO webdav_snapshot (remote_path, file_size, synced_at)"
        " VALUES (?, ?, ?)"
        " ON CONFLICT(remote_path) DO UPDATE SET"
        "   file_size=excluded.file_size, synced_at=excluded.synced_at",
        (remote_path, file_size, datetime.now().isoformat())
    )
    c.commit()


def clear_snapshot():
    c = _conn()
    c.execute("DELETE FROM webdav_snapshot")
    c.commit()


def get_snapshot_paths():
    c = _conn()
    rows = c.execute(
        "SELECT remote_path, file_size FROM webdav_snapshot"
    ).fetchall()
    return {row["remote_path"]: row["file_size"] for row in rows}


def get_snapshot_age_hours():
    c = _conn()
    row = c.execute(
        "SELECT MIN(synced_at) as oldest FROM webdav_snapshot"
    ).fetchone()
    if not row or not row["oldest"]:
        return None
    oldest = datetime.fromisoformat(row["oldest"])
    return (datetime.now() - oldest).total_seconds() / 3600


# ── Sync tasks ────────────────────────────────────────────

def create_sync_task(triggered_by):
    c = _conn()
    cur = c.execute(
        "INSERT INTO sync_tasks (triggered_by, status, started_at)"
        " VALUES (?, 'running', ?)",
        (triggered_by, datetime.now().isoformat())
    )
    c.commit()
    return cur.lastrowid


def update_sync_task(task_id, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [task_id]
    c = _conn()
    c.execute(f"UPDATE sync_tasks SET {fields} WHERE id=?", values)
    c.commit()


def get_last_sync_task():
    c = _conn()
    row = c.execute(
        "SELECT * FROM sync_tasks ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
