from flask import Flask, jsonify, request
from flask_cors import CORS
import os

from app.config import get_config, set_config, init_db

app = Flask(__name__)
CORS(app)

init_db()

PORT = int(os.environ.get("WEBUI_PORT", 8080))


@app.route("/")
def index():
    return """
    <h1>Rclone Smart Sync</h1>

    <h3>WebDAV 配置</h3>
    URL: <input id="url" style="width:300px"><br>
    用户名: <input id="user"><br>
    密码: <input id="pass" type="password"><br>
    远程路径: <input id="path" value="sync"><br><br>

    <h3>稳定时间（秒）</h3>
    <input id="sec" type="number" value="10"/><br><br>

    <button onclick="save()">保存配置</button>

    <script>
    async function load(){
        let res = await fetch('/api/config')
        let data = await res.json()

        document.getElementById('url').value = data.webdav_url || ""
        document.getElementById('user').value = data.webdav_user || ""
        document.getElementById('pass').value = data.webdav_pass || ""
        document.getElementById('path').value = data.remote_path || "sync"
        document.getElementById('sec').value = data.stable_seconds || 10
    }

    async function save(){
        let data = {
            webdav_url: document.getElementById('url').value,
            webdav_user: document.getElementById('user').value,
            webdav_pass: document.getElementById('pass').value,
            remote_path: document.getElementById('path').value,
            stable_seconds: document.getElementById('sec').value
        }

        await fetch('/api/config', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(data)
        })

        alert('已保存')
    }

    load()
    </script>
    """


@app.route("/api/config", methods=["GET"])
def get_all_config_api():
    return jsonify({
        "webdav_url": get_config("webdav_url", ""),
        "webdav_user": get_config("webdav_user", ""),
        "webdav_pass": get_config("webdav_pass", ""),
        "remote_path": get_config("remote_path", "sync"),
        "stable_seconds": get_config("stable_seconds", 10)
    })


@app.route("/api/config", methods=["POST"])
def set_config_api():
    data = request.json

    for key in ["webdav_url", "webdav_user", "webdav_pass", "remote_path", "stable_seconds"]:
        if key in data:
            set_config(key, data[key])

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print(f"WebUI running on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
