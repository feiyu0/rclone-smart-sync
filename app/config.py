import os
import json
import sqlite3
import time

DB_PATH = "/app/data/config.db"


def get_db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at INTEGER
    )
    """)

    conn.commit()
    conn.close()


def set_config(key, value):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    INSERT INTO config(key, value, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET
        value=excluded.value,
        updated_at=excluded.updated_at
    """, (key, json.dumps(value), int(time.time())))

    conn.commit()
    conn.close()


def get_config(key, default=None):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()

    conn.close()

    if row:
        return json.loads(row[0])
    return default


def get_all_config():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT key, value FROM config")
    rows = c.fetchall()

    conn.close()

    result = {}
    for k, v in rows:
        result[k] = json.loads(v)

    return result
