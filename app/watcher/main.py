import os
import time
import pyinotify
from threading import Thread

from app.config import get_config

WATCH_ROOT = os.environ.get("WATCH_ROOT", "/data")

checking_files = {}


def get_stable_seconds():
    return int(get_config("stable_seconds", 10))


def is_file_stable(path):
    try:
        last_size = -1
        stable_count = 0
        stable_seconds = get_stable_seconds()

        while stable_count < stable_seconds:
            if not os.path.exists(path):
                return False

            size = os.path.getsize(path)

            if size == last_size:
                stable_count += 1
            else:
                stable_count = 0
                last_size = size

            time.sleep(1)

        return True

    except Exception as e:
        print(f"[ERROR] stable check failed: {path} {e}")
        return False


def process_file(path):
    if path in checking_files:
        return

    checking_files[path] = True

    print(f"[CHECK] {path}")

    stable = is_file_stable(path)

    if not stable:
        print(f"[SKIP] unstable {path}")
        checking_files.pop(path, None)
        return

    try:
        # 👉 延迟导入（关键修复点！！！）
        from app.watcher.uploader import should_upload, upload_file

        if should_upload(path):
            upload_file(path)

    except Exception as e:
        print(f"[ERROR] upload failed: {e}")

    checking_files.pop(path, None)


class EventHandler(pyinotify.ProcessEvent):

    def process_IN_CREATE(self, event):
        self.handle(event)

    def process_IN_MOVED_TO(self, event):
        self.handle(event)

    def process_IN_MODIFY(self, event):
        self.handle(event)

    def handle(self, event):
        path = event.pathname

        if os.path.isdir(path):
            return

        print(f"[EVENT] {path}")

        Thread(target=process_file, args=(path,)).start()


def main():
    print("Watcher started...")
    print(f"Watching: {WATCH_ROOT}")

    wm = pyinotify.WatchManager()
    handler = EventHandler()

    notifier = pyinotify.Notifier(wm, handler)

    wm.add_watch(WATCH_ROOT, pyinotify.ALL_EVENTS, rec=True)

    notifier.loop()


if __name__ == "__main__":
    main()
