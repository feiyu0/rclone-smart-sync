import os
import subprocess
from app.config import get_config

# 👉 远程路径（后面会改成WebUI配置）
REMOTE = "webdav:sync"


def should_upload(local_path):
    """
    核心判断逻辑：
    同名文件存在 → 比较大小
    """

    filename = os.path.basename(local_path)

    # 👉 查询远程是否存在
    cmd = [
        "rclone", "lsjson",
        f"{REMOTE}/{filename}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)

        # 👉 不存在 → 直接上传
        if result.returncode != 0 or result.stdout.strip() == "":
            print(f"[UPLOAD] remote not exists → upload {filename}")
            return True

        import json
        remote_info = json.loads(result.stdout)[0]

        remote_size = remote_info["Size"]
        local_size = os.path.getsize(local_path)

        print(f"[CHECK] local={local_size} remote={remote_size}")

        # 👉 策略：只要不一样就上传
        if local_size != remote_size:
            print("[UPLOAD] size different → upload")
            return True

        print("[SKIP] same file")
        return False

    except Exception as e:
        print(f"[ERROR] check remote failed {e}")
        return True  # 出错时保守上传


def upload_file(local_path):
    """
    执行上传
    """

    filename = os.path.basename(local_path)

    cmd = [
        "rclone", "copy",
        local_path,
        REMOTE,
        "--ignore-existing",
        "--progress"
    ]

    print(f"[RCLONE] uploading {filename}")

    subprocess.run(cmd)

    print(f"[DONE] {filename}")
