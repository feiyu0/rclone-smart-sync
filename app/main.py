from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import logging
import json
import threading
import time
from queue import Queue
from datetime import datetime, date
import os

from app.config_manager import config_manager
from app.database import db
from app.uploader import uploader
from app.watcher import watcher as watcher_instance, MediaHandler
from app.syncer import syncer
from app.scheduler import scheduler_manager
from app.rclone_client import rclone_client
from app.utils import setup_logging, setup_signal_handlers, cleanup_old_logs

# Setup logging
setup_logging(level="INFO", log_dir="/logs", retain_days=7)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# SSE log queue
log_queue = Queue(maxsize=1000)

class LogHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            log_queue.put(log_entry)
        except Exception:
            pass

# Add SSE log handler
log_handler = LogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(log_handler)

# Initialize components
watcher = None
monitor_running = False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    try:
        pending_tasks = len(db.get_pending_tasks('pending'))
        failed_tasks = len(db.get_pending_tasks('failed'))
        
        return jsonify({
            'monitor_running': monitor_running,
            'sync_running': syncer.running,
            'queue_size': uploader.get_queue_size(),
            'running_tasks': uploader.get_running_tasks(),
            'pending_tasks': pending_tasks,
            'failed_tasks': failed_tasks,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Status API error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET'])
def get_config():
    try:
        config = config_manager.config.copy()
        # 隐藏密码（前端显示占位符）
        if 'webdav' in config and 'password' in config['webdav']:
            if config['webdav']['password']:
                config['webdav']['password'] = '********'
            else:
                config['webdav']['password'] = ''
        return jsonify(config)
    except Exception as e:
        logger.error(f"Get config error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['POST'])
def save_config():
    try:
        new_config = request.json
        
        # 处理密码：如果前端传来的是占位符，则不更新密码
        if 'webdav' in new_config and 'password' in new_config['webdav']:
            if new_config['webdav']['password'] == '********':
                # 保持原密码不变
                if 'webdav' in config_manager.config:
                    new_config['webdav']['password'] = config_manager.config['webdav'].get('password', '')
        
        if config_manager.update_config(new_config):
            # Reload scheduler if config changed
            scheduler_manager.reload_job()
            return jsonify({'success': True, 'message': '配置已保存'})
        return jsonify({'success': False, 'error': '保存配置失败'}), 500
    except Exception as e:
        logger.error(f"Save config error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/monitor/start', methods=['POST'])
def start_monitor():
    global monitor_running, watcher
    try:
        from app.watcher import Watcher
        if monitor_running:
            return jsonify({'success': False, 'error': '监控已在运行中'}), 400
        
        watcher = Watcher(uploader.add_task)
        if watcher.start():
            monitor_running = True
            return jsonify({'success': True, 'message': '监控已启动'})
        return jsonify({'success': False, 'error': '启动监控失败'}), 500
    except Exception as e:
        logger.error(f"Start monitor error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/monitor/stop', methods=['POST'])
def stop_monitor():
    global monitor_running
    try:
        if watcher:
            watcher.stop()
        monitor_running = False
        return jsonify({'success': True, 'message': '监控已停止'})
    except Exception as e:
        logger.error(f"Stop monitor error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync/full', methods=['POST'])
def trigger_full_sync():
    try:
        if syncer.running:
            return jsonify({'success': False, 'error': '同步任务已在运行中'}), 400
        
        # Run in background thread
        def run_sync():
            syncer.execute_full_sync(triggered_by='manual')
        
        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()
        
        return jsonify({'success': True, 'task_id': syncer.current_task_id, 'message': '全量同步已开始'})
    except Exception as e:
        logger.error(f"Trigger sync error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync/abort', methods=['POST'])
def abort_sync():
    try:
        if syncer.abort_sync():
            return jsonify({'success': True, 'message': '同步已中止'})
        return jsonify({'success': False, 'error': '没有正在运行的同步任务'}), 400
    except Exception as e:
        logger.error(f"Abort sync error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs/stream')
def stream_logs():
    @stream_with_context
    def event_stream():
        try:
            # Send initial log
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': datetime.now().isoformat()})}\n\n"
            
            while True:
                try:
                    log_entry = log_queue.get(timeout=30)
                    yield f"data: {json.dumps({'type': 'log', 'message': log_entry})}\n\n"
                except:
                    # Send heartbeat
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except Exception as e:
            logger.error(f"Log stream error: {e}")
    
    return Response(event_stream(), mimetype="text/event-stream", headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })

@app.route('/api/test/webdav', methods=['POST'])
def test_webdav():
    """测试 WebDAV 连接"""
    try:
        data = request.json
        url = data.get('url')
        username = data.get('username', '')
        password = data.get('password', '')
        
        # 验证必要字段
        if not url:
            return jsonify({"success": False, "message": "URL 不能为空"})
        
        # 如果密码是占位符，使用已保存的密码
        if password == '********':
            saved_config = config_manager.get_webdav_config()
            password = saved_config.get('password', '')
        
        # 构建测试配置
        test_config = {
            'url': url,
            'username': username,
            'password': password
        }
        
        success, message, debug = rclone_client.test_connection(test_config)
        
        result = {"success": success, "message": message}
        
        # 如果失败且提供了调试信息，添加到返回中
        if not success and debug:
            result["debug"] = debug
            # 记录调试信息到日志
            logger.debug(f"WebDAV test debug: {debug}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Test WebDAV error: {e}")
        return jsonify({'success': False, 'message': f'测试失败: {str(e)}'}), 500

@app.route('/api/test/dir', methods=['POST'])
def test_directory():
    try:
        path = request.json.get('path')
        if not path:
            return jsonify({'success': False, 'message': '未提供路径'}), 400
        
        if not os.path.exists(path):
            return jsonify({'success': False, 'message': f'路径不存在: {path}'}), 400
        
        if not os.path.isdir(path):
            return jsonify({'success': False, 'message': f'不是目录: {path}'}), 400
        
        # Check write permission
        test_file = os.path.join(path, '.write_test')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            writable = True
        except:
            writable = False
        
        return jsonify({
            'success': True,
            'message': '目录可访问',
            'writable': writable
        })
    except Exception as e:
        logger.error(f"Test directory error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/browse/local')
def browse_local():
    try:
        path = request.args.get('path', '/')
        if not os.path.exists(path):
            return jsonify({'error': '路径不存在'}), 404
        
        items = []
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                items.append({
                    'name': item,
                    'path': item_path,
                    'is_dir': os.path.isdir(item_path),
                    'size': os.path.getsize(item_path) if os.path.isfile(item_path) else 0
                })
        except PermissionError:
            return jsonify({'error': '权限被拒绝'}), 403
        
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        return jsonify({
            'current_path': path,
            'parent': os.path.dirname(path) if path != '/' else None,
            'items': items
        })
    except Exception as e:
        logger.error(f"Browse local error: {e}")
        return jsonify({'error': str(e)}), 500

def main():
    try:
        # Start uploader
        upload_config = config_manager.get_upload_config()
        uploader.start(upload_config.get('concurrency', 3))
        
        # Start scheduler
        scheduler_manager.start()
        
        # Start Flask app
        app.run(host='0.0.0.0', port=8080, threaded=True)
    except Exception as e:
        logger.error(f"Main error: {e}")
        raise

if __name__ == '__main__':
    main()
