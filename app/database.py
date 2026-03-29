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
    return _local.conn


def init():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS upload_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_path TEXT NOT NULL,
            remote_path TEXT NOT NULL,
            file_size INTEGER,
            uploaded_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'success'
        );

        CREATE TABLE IF NOT EXISTS webdav_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remote_path TEXT NOT NULL UNIQUE,
            file_size INTEGER,
            synced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sync_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            triggered_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            finished_at TEXT,
            total INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_upload_local ON upload_history(local_path);
        CREATE INDEX IF NOT EXISTS idx_snapshot_path ON webdav_snapshot(remote_path);
    """)
    c.commit()


def record_upload(local_path, remote_path, file_size, status="success"):
    c = _conn()
    c.execute(
        "INSERT INTO upload_history (local_path, remote_path, file_size, uploaded_at, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (local_path, remote_path, file_size, datetime.now().isoformat(), status)
    )
    c.commit()


def get_upload_stats():
    c = _conn()
    today = datetime.now().strftime("%Y-%m-%d")
    row = c.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success, "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed "
        "FROM upload_history WHERE uploaded_at LIKE ?",
        (today + "%",)
    ).fetchone()
    total_row = c.execute(
        "SELECT COUNT(*) as total, SUM(file_size) as total_bytes "
        "FROM upload_history WHERE status='success'"
    ).fetchone()
    return {
        "today_total": row["total"] or 0,
        "today_success": row["success"] or 0,
        "today_failed": row["failed"] or 0,
        "all_time_total": total_row["total"] or 0,
        "all_time_bytes": total_row["total_bytes"] or 0,
    }


def upsert_snapshot(remote_path, file_size):
    c = _conn()
    c.execute(
        "INSERT INTO webdav_snapshot (remote_path, file_size, synced_at) VALUES (?, ?, ?) "
        "ON CONFLICT(remote_path) DO UPDATE SET file_size=excluded.file_size, synced_at=excluded.synced_at",
        (remote_path, file_size, datetime.now().isoformat())
    )
    c.commit()


def clear_snapshot():
    c = _conn()
    c.execute("DELETE FROM webdav_snapshot")
    c.commit()


def get_snapshot_paths():
    c = _conn()
    rows = c.execute("SELECT remote_path, file_size FROM webdav_snapshot").fetchall()
    return {row["remote_path"]: row["file_size"] for row in rows}


def get_snapshot_age_hours():
    c = _conn()
    row = c.execute("SELECT MIN(synced_at) as oldest FROM webdav_snapshot").fetchone()
    if not row or not row["oldest"]:
        return None
    oldest = datetime.fromisoformat(row["oldest"])
    delta = datetime.now() - oldest
    return delta.total_seconds() / 3600


def create_sync_task(triggered_by):
    c = _conn()
    cur = c.execute(
        "INSERT INTO sync_tasks (triggered_by, status, started_at) VALUES (?, 'running', ?)",
        (triggered_by, datetime.now().isoformat())
    )
    c.commit()
    return cur.lastrowid


def update_sync_task(task_id, **kwargs):
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


def get_recent_uploads(limit=200):
    c = _conn()
    rows = c.execute(
        "SELECT * FROM upload_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
