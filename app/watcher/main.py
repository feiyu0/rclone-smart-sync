import os
import time
import pyinotify
from threading import Thread

WATCH_ROOT = os.environ.get("WATCH_ROOT", "/data")

# 默认稳定时间（后面会接入WebUI）
from app.config import get_config

def get_stable_seconds():
    return get_config("stable_seconds", 10)

# 正在检测的文件
checking_files = {}


def is_file_stable(path):
    """检测文件是否稳定"""
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
    """后台处理文件"""
    if path in checking_files:
        return

    checking_files[path] = True

    print(f"[CHECK] start checking {path}")

    stable = is_file_stable(path)

    if not stable:
        print(f"[SKIP] not stable {path}")
        checking_files.pop(path, None)
        return

    size = os.path.getsize(path)

    print(f"[READY] {path} size={size}")

    # 🚧 这里后面会接入上传逻辑

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

        # 开线程处理（避免阻塞监听）
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
