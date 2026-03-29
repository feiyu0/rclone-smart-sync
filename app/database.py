import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Optional, Any
import os

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "/data/sync.db"):
        self.db_path = db_path
        self.init_tables()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def init_tables(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS upload_history (
                        id INTEGER PRIMARY KEY,
                        local_path TEXT NOT NULL,
                        remote_path TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(local_path, file_size, mtime)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pending_tasks (
                        id INTEGER PRIMARY KEY,
                        local_path TEXT NOT NULL,
                        remote_path TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        source TEXT NOT NULL,
                        retry_count INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS webdav_snapshot (
                        id INTEGER PRIMARY KEY,
                        remote_path TEXT NOT NULL UNIQUE,
                        file_size INTEGER,
                        mtime REAL,
                        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sync_tasks (
                        id INTEGER PRIMARY KEY,
                        triggered_by TEXT NOT NULL,
                        status TEXT NOT NULL,
                        total_files INTEGER DEFAULT 0,
                        uploaded_files INTEGER DEFAULT 0,
                        failed_files INTEGER DEFAULT 0,
                        started_at TIMESTAMP,
                        finished_at TIMESTAMP,
                        error_message TEXT
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS scheduler_config (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        enabled BOOLEAN DEFAULT 0,
                        cron_expr TEXT DEFAULT '0 3 * * *',
                        bwlimit TEXT DEFAULT '',
                        overwrite_policy TEXT DEFAULT 'skip',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("INSERT OR IGNORE INTO scheduler_config (id, enabled, cron_expr, bwlimit, overwrite_policy) VALUES (1, 0, '0 3 * * *', '', 'skip')")
        except Exception as e:
            logger.error(f"Failed to init tables: {e}")
            raise
    
    def add_upload_history(self, local_path: str, remote_path: str, file_size: int, mtime: float) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO upload_history (local_path, remote_path, file_size, mtime)
                    VALUES (?, ?, ?, ?)
                """, (local_path, remote_path, file_size, mtime))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to add upload history: {e}")
            return False
    
    def is_uploaded(self, local_path: str, file_size: int, mtime: float) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 1 FROM upload_history
                    WHERE local_path = ? AND file_size = ? AND mtime = ?
                """, (local_path, file_size, mtime))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to check uploaded: {e}")
            return False
    
    def add_pending_task(self, local_path: str, remote_path: str, file_size: int, mtime: float, source: str) -> int:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO pending_tasks (local_path, remote_path, file_size, mtime, source, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                """, (local_path, remote_path, file_size, mtime, source))
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            logger.warning(f"Task already exists: {local_path}")
            return -1
        except Exception as e:
            logger.error(f"Failed to add pending task: {e}")
            return -1
    
    def get_pending_tasks(self, status: str = 'pending') -> List[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM pending_tasks WHERE status = ? ORDER BY created_at
                """, (status,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get pending tasks: {e}")
            return []
    
    def update_pending_task_status(self, task_id: int, status: str, retry_count: int = None) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if retry_count is not None:
                    cursor.execute("""
                        UPDATE pending_tasks
                        SET status = ?, retry_count = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (status, retry_count, task_id))
                else:
                    cursor.execute("""
                        UPDATE pending_tasks
                        SET status = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (status, task_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update task status: {e}")
            return False
    
    def delete_pending_task(self, task_id: int) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM pending_tasks WHERE id = ?", (task_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete pending task: {e}")
            return False
    
    def update_webdav_snapshot(self, snapshot: List[Dict]) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM webdav_snapshot")
                for item in snapshot:
                    cursor.execute("""
                        INSERT INTO webdav_snapshot (remote_path, file_size, mtime)
                        VALUES (?, ?, ?)
                    """, (item['path'], item.get('size'), item.get('mtime')))
                return True
        except Exception as e:
            logger.error(f"Failed to update snapshot: {e}")
            return False
    
    def get_webdav_snapshot(self) -> Dict[str, Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT remote_path, file_size, mtime FROM webdav_snapshot")
                return {row['remote_path']: {'size': row['file_size'], 'mtime': row['mtime']} for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get snapshot: {e}")
            return {}
    
    def create_sync_task(self, triggered_by: str) -> int:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sync_tasks (triggered_by, status, started_at)
                    VALUES (?, 'running', CURRENT_TIMESTAMP)
                """, (triggered_by,))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to create sync task: {e}")
            return -1
    
    def update_sync_task(self, task_id: int, status: str = None, total_files: int = None,
                         uploaded_files: int = None, failed_files: int = None,
                         error_message: str = None) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                updates = []
                params = []
                if status:
                    updates.append("status = ?")
                    params.append(status)
                if total_files is not None:
                    updates.append("total_files = ?")
                    params.append(total_files)
                if uploaded_files is not None:
                    updates.append("uploaded_files = ?")
                    params.append(uploaded_files)
                if failed_files is not None:
                    updates.append("failed_files = ?")
                    params.append(failed_files)
                if error_message is not None:
                    updates.append("error_message = ?")
                    params.append(error_message)
                if status in ('done', 'failed', 'cancelled'):
                    updates.append("finished_at = CURRENT_TIMESTAMP")
                
                if updates:
                    params.append(task_id)
                    cursor.execute(f"UPDATE sync_tasks SET {', '.join(updates)} WHERE id = ?", params)
                return True
        except Exception as e:
            logger.error(f"Failed to update sync task: {e}")
            return False
    
    def get_scheduler_config(self) -> Optional[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM scheduler_config WHERE id = 1")
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get scheduler config: {e}")
            return None
    
    def update_scheduler_config(self, enabled: bool = None, cron_expr: str = None,
                                bwlimit: str = None, overwrite_policy: str = None) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                updates = []
                params = []
                if enabled is not None:
                    updates.append("enabled = ?")
                    params.append(1 if enabled else 0)
                if cron_expr is not None:
                    updates.append("cron_expr = ?")
                    params.append(cron_expr)
                if bwlimit is not None:
                    updates.append("bwlimit = ?")
                    params.append(bwlimit)
                if overwrite_policy is not None:
                    updates.append("overwrite_policy = ?")
                    params.append(overwrite_policy)
                updates.append("updated_at = CURRENT_TIMESTAMP")
                
                if updates:
                    params.append(1)
                    cursor.execute(f"UPDATE scheduler_config SET {', '.join(updates)} WHERE id = ?", params)
                return True
        except Exception as e:
            logger.error(f"Failed to update scheduler config: {e}")
            return False

db = Database()
