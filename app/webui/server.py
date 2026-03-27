from flask import Flask, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

PORT = int(os.environ.get("WEBUI_PORT", 8080))


@app.route("/")
def index():
    return """
    <h1>Rclone Smart Sync</h1>
    <p>服务运行中 ✅</p>
    <p>后续这里会加入完整管理界面</p>
    """


@app.route("/api/status")
def status():
    return jsonify({
        "status": "running"
    })


if __name__ == "__main__":
    print(f"WebUI running on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
