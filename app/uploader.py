import threading
import queue
import subprocess
import os
import time
import logging
from datetime import datetime
from app import config, database

logger = logging.getLogger(__name__)

_task_queue = queue.PriorityQueue(maxsize=500)
_active_uploads = {}
_active_lock = threading.Lock()
_in_queue_set = set()
_in_queue_lock = threading.Lock()
_workers = []
_running = False


class UploadTask:
    def __init__(self, local_path, remote_path, file_size=0, priority=10, source="monitor"):
        self.local_path = local_path
        self.remote_path = remote_path
        self.file_size = file_size
        self.priority = priority
        self.source = source
        self.retry_count = 0
        self.created_at = datetime.now().isoformat()

    def __lt__(self, other):
        return self.priority < other.priority


def enqueue(local_path, remote_path, file_size=0, priority=10, source="monitor"):
    key = local_path
    with _in_queue_lock:
        if key in _in_queue_set:
            logger.debug(f"Already in queue, skip: {local_path}")
            return False
        _in_queue_set.add(key)

    task = UploadTask(local_path, remote_path, file_size, priority, source)
    try:
        _task_queue.put_nowait((priority, task))
        logger.info(f"Enqueued [{source}]: {os.path.basename(local_path)} ({_fmt_size(file_size)})")
        return True
    except queue.Full:
        with _in_queue_lock:
            _in_queue_set.discard(key)
        logger.warning(f"Queue full, dropped: {local_path}")
        return False


def get_queue_snapshot():
    with _active_lock:
        uploading = [
            {
                "name": os.path.basename(k),
                "local_path": k,
                "progress": v.get("progress", 0),
                "file_size": v.get("file_size", 0),
                "transferred": v.get("transferred", 0),
                "source": v.get("source", ""),
                "status": "uploading",
            }
            for k, v in _active_uploads.items()
        ]

    tmp = []
    waiting = []
    while not _task_queue.empty():
        try:
            item = _task_queue.get_nowait()
            tmp.append(item)
            _, task = item
            waiting.append({
                "name": os.path.basename(task.local_path),
                "local_path": task.local_path,
                "file_size": task.file_size,
                "source": task.source,
                "retry_count": task.retry_count,
                "status": "waiting",
            })
        except queue.Empty:
            break
    for item in tmp:
        try:
            _task_queue.put_nowait(item)
        except queue.Full:
            pass

    return {"uploading": uploading, "waiting": waiting}


def start(num_workers=None):
    global _running, _workers
    if _running:
        return
    _running = True
    cfg = config.get()
    n = num_workers or cfg.get("concurrent_uploads", 3)
    _workers = []
    for i in range(n):
        t = threading.Thread(target=_worker_loop, args=(i,), daemon=True)
        t.start()
        _workers.append(t)
    logger.info(f"Uploader started with {n} workers")


def stop():
    global _running
    _running = False
    logger.info("Uploader stopped")


def _worker_loop(worker_id):
    while _running:
        try:
            _, task = _task_queue.get(timeout=2)
        except queue.Empty:
            continue
        _do_upload(task, worker_id)
        _task_queue.task_done()
        with _in_queue_lock:
            _in_queue_set.discard(task.local_path)


def _do_upload(task, worker_id):
    cfg = config.get()
    local = task.local_path
    remote = task.remote_path
    name = os.path.basename(local)

    if not os.path.exists(local):
        logger.warning(f"[W{worker_id}] File gone before upload: {local}")
        return

    file_size = os.path.getsize(local)

    with _active_lock:
        _active_uploads[local] = {
            "file_size": file_size,
            "transferred": 0,
            "progress": 0,
            "source": task.source,
            "worker_id": worker_id,
        }

    logger.info(f"[W{worker_id}] Uploading: {name} ({_fmt_size(file_size)})")

    conf_path = _write_rclone_config(cfg, worker_id)
    timeout_secs = cfg.get("single_file_timeout_minutes", 60) * 60
    max_retries = cfg.get("retry_count", 3)

    success = False
    for attempt in range(1, max_retries + 1):
        try:
            cmd = [
                "rclone", "copyto",
                "--config", conf_path,
                "--retries", "1",
                "--low-level-retries", "3",
                "--stats", "1s",
                "--stats-one-line",
                "--use-json-log",
                local,
                f"webdav_target:{remote}",
            ]

            if task.source == "sync":
                speed = cfg.get("sync_speed_limit", "10M")
                if speed and speed != "0":
                    cmd += ["--bwlimit", speed]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            start_time = time.time()
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    _parse_json_progress(local, line.strip(), file_size)
                if time.time() - start_time > timeout_secs:
                    proc.kill()
                    raise TimeoutError(f"Timeout after {timeout_secs}s")

            rc = proc.returncode
            if rc == 0:
                success = True
                break
            else:
                logger.warning(
                    f"[W{worker_id}] Attempt {attempt}/{max_retries} failed (rc={rc}): {name}"
                )
                if attempt < max_retries:
                    time.sleep(5 * attempt)

        except TimeoutError as e:
            logger.error(f"[W{worker_id}] {e}: {name}")
            break
        except Exception as e:
            logger.error(f"[W{worker_id}] Attempt {attempt}/{max_retries} error: {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)

    with _active_lock:
        _active_uploads.pop(local, None)

    status = "success" if success else "failed"
    database.record_upload(local, remote, file_size, status)

    if success:
        logger.info(f"[W{worker_id}] Done: {name} ({_fmt_size(file_size)})")
    else:
        logger.error(f"[W{worker_id}] Failed after {max_retries} attempts: {name}")

    try:
        os.remove(conf_path)
    except Exception:
        pass


def _parse_json_progress(local_path, line, total_size):
    try:
        data = json.loads(line)
        stats = data.get("stats", {})
        transferred = stats.get("bytes", 0)
        if total_size > 0 and transferred > 0:
            progress = min(int(transferred / total_size * 100), 99)
            with _active_lock:
                if local_path in _active_uploads:
                    _active_uploads[local_path]["transferred"] = transferred
                    _active_uploads[local_path]["progress"] = progress
    except Exception:
        pass


def _write_rclone_config(cfg, worker_id):
    password = cfg.get("webdav_password", "")
    obscured = _obscure_password(password)
    conf = f"""[webdav_target]
type = webdav
url = {cfg.get('webdav_url', '')}
vendor = other
user = {cfg.get('webdav_username', '')}
pass = {obscured}
"""
    conf_path = f"/tmp/rclone_worker_{worker_id}.conf"
    with open(conf_path, "w") as f:
        f.write(conf)
    os.chmod(conf_path, 0o600)
    return conf_path


def _obscure_password(password):
    if not password:
        return ""
    try:
        result = subprocess.run(
            ["rclone", "obscure", password],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return password


def _fmt_size(b):
    if not b:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
