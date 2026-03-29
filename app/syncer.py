import os
import logging
import threading
import requests
from xml.etree import ElementTree
from urllib.parse import urlparse, unquote
from datetime import datetime
from app import config, database, uploader

logger = logging.getLogger(__name__)

_running = False
_lock = threading.Lock()
_abort_flag = threading.Event()
_current_task = {}


def is_running():
    with _lock:
        return _running


def abort():
    _abort_flag.set()
    logger.info("Sync abort requested")


def run(triggered_by="manual"):
    global _running
    with _lock:
        if _running:
            logger.warning("Sync already running, skip")
            return
        _running = True
        _abort_flag.clear()

    task_id = database.create_sync_task(triggered_by)

    try:
        _do_sync(task_id, triggered_by)
    except Exception as e:
        logger.error(f"Sync error: {e}")
        database.update_sync_task(task_id, status="failed",
                                  finished_at=_now())
    finally:
        with _lock:
            _running = False


def run_in_thread(triggered_by="manual"):
    t = threading.Thread(target=run, args=(triggered_by,), daemon=True)
    t.start()
    return t


def _do_sync(task_id, triggered_by):
    cfg = config.get()
    watch_dir = cfg.get("local_watch_dir", "/data")
    remote_dir = cfg.get("webdav_remote_dir", "/").rstrip("/")
    extensions = set(cfg.get("video_extensions", []))
    ignore_dirs = set(cfg.get("ignore_dirs", []))
    overwrite_policy = cfg.get("overwrite_policy", "skip_if_same_size")
    ttl_hours = cfg.get("webdav_snapshot_ttl_hours", 23)

    logger.info(f"[Sync {task_id}] Starting — triggered by: {triggered_by}")

    # Step 1: scan local
    logger.info(f"[Sync {task_id}] Step 1: scanning local directory")
    local_files = _scan_local(watch_dir, extensions, ignore_dirs)
    logger.info(f"[Sync {task_id}] Found {len(local_files)} local video files")

    if _abort_flag.is_set():
        database.update_sync_task(task_id, status="aborted", finished_at=_now())
        logger.info(f"[Sync {task_id}] Aborted after step 1")
        return

    # Step 2: WebDAV snapshot
    age = database.get_snapshot_age_hours()
    if age is None or age > ttl_hours:
        logger.info(f"[Sync {task_id}] Step 2: refreshing WebDAV snapshot")
        try:
            snapshot = _fetch_webdav_snapshot(cfg, remote_dir)
            database.clear_snapshot()
            for path, size in snapshot.items():
                database.upsert_snapshot(path, size)
            logger.info(f"[Sync {task_id}] WebDAV snapshot: {len(snapshot)} files cached")
        except Exception as e:
            logger.error(f"[Sync {task_id}] WebDAV snapshot failed: {e}")
            snapshot = database.get_snapshot_paths()
            logger.warning(f"[Sync {task_id}] Using cached snapshot ({len(snapshot)} files)")
    else:
        snapshot = database.get_snapshot_paths()
        logger.info(
            f"[Sync {task_id}] Step 2: using cached snapshot "
            f"({len(snapshot)} files, {age:.1f}h old)"
        )

    if _abort_flag.is_set():
        database.update_sync_task(task_id, status="aborted", finished_at=_now())
        logger.info(f"[Sync {task_id}] Aborted after step 2")
        return

    # Step 3: diff
    logger.info(f"[Sync {task_id}] Step 3: comparing local vs remote")
    to_upload = []
    skipped = 0

    for local_path, local_size in local_files.items():
        rel = os.path.relpath(local_path, watch_dir).replace("\\", "/")
        remote_path = f"{remote_dir}/{rel}"

        if remote_path not in snapshot:
            to_upload.append((local_path, remote_path, local_size))
            continue

        remote_size = snapshot[remote_path]

        if overwrite_policy == "always":
            to_upload.append((local_path, remote_path, local_size))
        elif overwrite_policy == "skip_if_same_size" and local_size == remote_size:
            skipped += 1
        else:
            to_upload.append((local_path, remote_path, local_size))

    logger.info(
        f"[Sync {task_id}] Need to upload: {len(to_upload)}, skip: {skipped}"
    )
    database.update_sync_task(task_id, total=len(to_upload), skipped=skipped)

    if _abort_flag.is_set():
        database.update_sync_task(task_id, status="aborted", finished_at=_now())
        logger.info(f"[Sync {task_id}] Aborted after step 3")
        return

    # Step 4: enqueue
    logger.info(f"[Sync {task_id}] Step 4: enqueuing uploads")
    enqueued = 0
    for local_path, remote_path, file_size in to_upload:
        if _abort_flag.is_set():
            break
        ok = uploader.enqueue(
            local_path=local_path,
            remote_path=remote_path,
            file_size=file_size,
            priority=20,
            source="sync",
        )
        if ok:
            enqueued += 1

    database.update_sync_task(
        task_id, status="done",
        done=enqueued, finished_at=_now()
    )
    logger.info(f"[Sync {task_id}] Done — enqueued {enqueued} files")


def _scan_local(watch_dir, extensions, ignore_dirs):
    result = {}
    for root, dirs, files in os.walk(watch_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in extensions:
                full = os.path.join(root, fname)
                try:
                    result[full] = os.path.getsize(full)
                except OSError:
                    pass
    return result


def _fetch_webdav_snapshot(cfg, remote_dir):
    url = cfg.get("webdav_url", "").rstrip("/")
    username = cfg.get("webdav_username", "")
    password = cfg.get("webdav_password", "")
    auth = (username, password) if username else None
    target_url = f"{url}{remote_dir}/"
    result = {}
    _propfind_recursive(target_url, auth, result, depth=0)
    return result


def _propfind_recursive(url, auth, result, depth):
    if depth > 15:
        return
    try:
        resp = requests.request(
            "PROPFIND", url,
            auth=auth,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            data=(
                '<?xml version="1.0"?>'
                '<D:propfind xmlns:D="DAV:">'
                '<D:prop><D:getcontentlength/><D:resourcetype/></D:prop>'
                '</D:propfind>'
            ),
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"PROPFIND failed: {url} — {e}")
        return

    try:
        root_el = ElementTree.fromstring(resp.content)
    except Exception as e:
        logger.error(f"XML parse failed: {e}")
        return

    ns = {"D": "DAV:"}
    parsed = urlparse(url)
    base_path = parsed.path.rstrip("/")

    for response in root_el.findall("D:response", ns):
        href_el = response.find("D:href", ns)
        if href_el is None:
            continue
        href_path = unquote(href_el.text).rstrip("/")

        if href_path == base_path:
            continue

        propstat = response.find("D:propstat", ns)
        if propstat is None:
            continue
        prop = propstat.find("D:prop", ns)
        if prop is None:
            continue

        resourcetype = prop.find("D:resourcetype", ns)
        is_dir = (
            resourcetype is not None
            and resourcetype.find("D:collection", ns) is not None
        )

        if is_dir:
            child_url = f"{parsed.scheme}://{parsed.netloc}{href_path}/"
            _propfind_recursive(child_url, auth, result, depth + 1)
        else:
            size_el = prop.find("D:getcontentlength", ns)
            size = int(size_el.text) if size_el is not None and size_el.text else 0
            result[href_path] = size


def _now():
    return datetime.now().isoformat()
