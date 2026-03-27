import os
import time
import pyinotify

WATCH_ROOT = os.environ.get("WATCH_ROOT", "/data")


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

        # 简单延迟（后面会升级为稳定检测）
        time.sleep(3)

        if not os.path.exists(path):
            return

        size = os.path.getsize(path)

        print(f"[READY] {path} size={size}")


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
