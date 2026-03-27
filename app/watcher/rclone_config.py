import os
from app.config import get_config

CONFIG_PATH = "/root/.config/rclone"
CONFIG_FILE = CONFIG_PATH + "/rclone.conf"


def generate_config():
    url = get_config("webdav_url")
    user = get_config("webdav_user")
    password = get_config("webdav_pass")

    if not url:
        print("[RCLONE] WebDAV not configured")
        return

    os.makedirs(CONFIG_PATH, exist_ok=True)

    content = f"""
[webdav]
type = webdav
url = {url}
vendor = other
user = {user}
pass = {password}
"""

    with open(CONFIG_FILE, "w") as f:
        f.write(content)

    print("[RCLONE] config generated")
