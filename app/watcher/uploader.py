import os
import subprocess
from app.config import get_config
from app.watcher.rclone_config import generate_config


def get_remote():
    path = get_config("remote_path", "sync")
    return f"webdav:{path}"


def should_upload(local_path):
    filename = os.path.basename(local_path)
    remote = get_remote()

    cmd = ["rclone", "lsjson", f"{remote}/{filename}"]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0 or result.stdout.strip() == "":
        print(f"[UPLOAD] not exist → {filename}")
        return True

    import json
    remote_info = json.loads(result.stdout)[0]

    remote_size = remote_info["Size"]
    local_size = os.path.getsize(local_path)

    if remote_size != local_size:
        print("[UPLOAD] size diff")
        return True

    print("[SKIP] same file")
    return False


def upload_file(local_path):
    generate_config()  # 👉 每次上传前生成配置

    remote = get_remote()

    print(f"[UPLOAD] {local_path}")

    subprocess.run([
        "rclone", "copy",
        local_path,
        remote
    ])
