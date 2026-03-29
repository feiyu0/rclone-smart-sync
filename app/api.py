import os
import json
import time
import queue
import logging
import threading
import requests
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from app import config, database, uploader, watcher, syncer, scheduler

logger = logging.getLogger(__name__)
app = Flask(__name__, template_folder="templates", static_folder="static")

_sse_clients = []
_sse_lock = threading.Lock()
_log_buffer = []
_LOG_BUFFER_MAX = 500


class SSELogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg,
            }
            _log_buffer.append(entry)
            if len(_log_buffer) > _LOG_BUFFER_MAX:
                _log_buffer.pop(0)
            _push_sse("log", entry)
        except Exception:
            pass


def setup_logging():
    """添加 SSE 日志处理器，避免重复添加"""
    root_logger = logging.getLogger()
    if not any(isinstance(h, SSELogHandler) for h in root_logger.handlers):
        handler = SSELogHandler()
        handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))
        root_logger.addHandler(handler)


def _push_sse(event, data):
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


# ── Pages ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── SSE stream ─────────────────────────────────────────────────────────

@app.route("/api/stream")
def stream():
    q = queue.Queue(maxsize=200)
    with _sse_lock:
        _sse_clients.append(q)

    def generate():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    data = q.get(timeout=20)
                    yield data
                except Exception:
                    yield ": ping\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Status ─────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    stats = database.get_upload_stats()
    queue_info = uploader.get_queue_snapshot()
    last_sync = database.get_last_sync_task()
    snap_age = database.get_snapshot_age_hours()
    return jsonify({
        "monitor_running": watcher.is_running(),
        "sync_running": syncer.is_running(),
        "stats": stats,
        "queue": queue_info,
        "last_sync": last_sync,
        "snapshot_age_hours": round(snap_age, 1) if snap_age is not None else None,
    })


@app.route("/api/logs")
def api_logs():
    level = request.args.get("level", "all")
    logs = _log_buffer[-200:]
    if level == "error":
        logs = [l for l in logs if l["level"] in ("ERROR", "WARNING")]
    elif level == "success":
        logs = [l for l in logs if "Done" in l["message"]]
    return jsonify(logs)


# ── Config ─────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def api_config_get():
    cfg = config.get()
    safe = dict(cfg)
    safe["webdav_password"] = "••••••" if cfg.get("webdav_password") else ""
    return jsonify(safe)


@app.route("/api/config", methods=["POST"])
def api_config_save():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400
    if "webdav_password" in data and data["webdav_password"].startswith("•"):
        data.pop("webdav_password")
    
    config.update(data)
    
    if "monitor_enabled" in data:
        if data["monitor_enabled"] and not watcher.is_running():
            watcher.start()
        elif not data["monitor_enabled"] and watcher.is_running():
            watcher.stop()
    
    if "scheduler_enabled" in data or "scheduler_time" in data:
        scheduler.reschedule()
    
    return jsonify({"ok": True})


# ── Connection tests ────────────────────────────────────────────────────

@app.route("/api/test/webdav", methods=["POST"])
def api_test_webdav():
    data = request.get_json(force=True) or {}
    url = data.get("webdav_url", "").rstrip("/") + "/"
    username = data.get("webdav_username", "")
    password = data.get("webdav_password", "")
    if password.startswith("•"):
        password = config.get().get("webdav_password", "")
    try:
        auth = (username, password) if username else None
        resp = requests.request(
            "PROPFIND", url, auth=auth,
            headers={"Depth": "0"},
            timeout=10,
        )
        if resp.status_code in (200, 207):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": f"HTTP {resp.status_code}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/test/localdir", methods=["POST"])
def api_test_localdir():
    data = request.get_json(force=True) or {}
    path = data.get("path", "")
    if not path:
        return jsonify({"ok": False, "error": "No path provided"})
    if not os.path.isdir(path):
        return jsonify({"ok": False, "error": "Directory not found"})
    if not os.access(path, os.R_OK):
        return jsonify({"ok": False, "error": "No read permission"})
    count = sum(len(files) for _, _, files in os.walk(path))
    return jsonify({"ok": True, "file_count": count})


# ── Monitor control ─────────────────────────────────────────────────────

@app.route("/api/monitor/start", methods=["POST"])
def api_monitor_start():
    config.update({"monitor_enabled": True})
    watcher.start()
    _push_sse("status", {"monitor_running": True})
    return jsonify({"ok": True})


@app.route("/api/monitor/stop", methods=["POST"])
def api_monitor_stop():
    config.update({"monitor_enabled": False})
    watcher.stop()
    _push_sse("status", {"monitor_running": False})
    return jsonify({"ok": True})


# ── Sync control ────────────────────────────────────────────────────────

@app.route("/api/sync/start", methods=["POST"])
def api_sync_start():
    if syncer.is_running():
        return jsonify({"ok": False, "error": "Sync already running"})
    syncer.run_in_thread(triggered_by="manual")
    return jsonify({"ok": True})


@app.route("/api/sync/abort", methods=["POST"])
def api_sync_abort():
    syncer.abort()
    return jsonify({"ok": True})


# ── Queue control ───────────────────────────────────────────────────────

@app.route("/api/queue/clear", methods=["POST"])
def api_queue_clear():
    cleared = 0
    while True:
        try:
            uploader._task_queue.get_nowait()
            cleared += 1
        except queue.Empty:
            break
    with uploader._in_queue_lock:
        uploader._in_queue_set.clear()
    logger.info(f"Queue cleared: {cleared} tasks removed")
    return jsonify({"ok": True, "cleared": cleared})
