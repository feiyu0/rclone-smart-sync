# 修改 api_config_get 和 api_config_save 函数
@app.route("/api/config", methods=["GET"])
def api_config_get():
    cfg = config.get()
    safe = dict(cfg)
    safe["webdav_password"] = "••••••" if cfg.get("webdav_password") else ""
    return jsonify(safe)


@app.route("/api/config", methods=["POST"])
def api_config_save():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400
    if "webdav_password" in data and data["webdav_password"].startswith("•"):
        data.pop("webdav_password")
    
    config.update(data)
    
    if "monitor_enabled" in data:
        if data["monitor_enabled"] and not watcher.is_running():
            watcher.start()
        elif not data["monitor_enabled"] and watcher.is_running():
            watcher.stop()
    
    if "scheduler_enabled" in data or "scheduler_time" in data:
        scheduler.reschedule()
    
    return jsonify({"ok": True})
