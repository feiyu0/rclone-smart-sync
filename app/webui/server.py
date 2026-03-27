from flask import Flask, jsonify, request
from flask_cors import CORS
import os

# 👉 引入配置模块（已修复）
from app.config import get_config, set_config, init_db

app = Flask(__name__)
CORS(app)

# 👉 初始化数据库（关键修复点）
init_db()

PORT = int(os.environ.get("WEBUI_PORT", 8080))


@app.route("/")
def index():
    return """
    <h1>Rclone Smart Sync</h1>

    <p>服务运行中 ✅</p>

    <h3>稳定时间设置（秒）</h3>
    <input id="sec" type="number" value="10"/>
    <button onclick="save()">保存</button>

    <script>
    async function load(){
        let res = await fetch('/api/config')
        let data = await res.json()
        document.getElementById('sec').value = data.stable_seconds
    }

    async function save(){
        let v = document.getElementById('sec').value
        await fetch('/api/config', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({stable_seconds: v})
        })
        alert('已保存')
    }

    load()
    </script>
    """


@app.route("/api/status")
def status():
    return jsonify({
        "status": "running"
    })


@app.route("/api/config", methods=["GET"])
def get_all_config_api():
    return jsonify({
        "stable_seconds": get_config("stable_seconds", 10)
    })


@app.route("/api/config", methods=["POST"])
def set_config_api():
    data = request.json

    if "stable_seconds" in data:
        set_config("stable_seconds", int(data["stable_seconds"]))

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print(f"WebUI running on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
