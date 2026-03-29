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
        # Get today's upload count
        today = date.today().strftime('%Y-%m-%d')
        upload_today = 0  # Simplified, could be queried from database
        
        pending_tasks = len(db.get_pending_tasks('pending'))
        failed_tasks = len(db.get_pending_tasks('failed'))
        
        return jsonify({
            'monitor_running': monitor_running,
            'sync_running': syncer.running,
            'queue_size': uploader.get_queue_size(),
            'running_tasks': uploader.get_running_tasks(),
            'pending_tasks': pending_tasks,
            'failed_tasks': failed_tasks,
            'upload_today': upload_today,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Status API error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET'])
def get_config():
    try:
        config = config_manager.config.copy()
        # Hide password
        if 'webdav' in config and 'password' in config['webdav']:
            config['webdav']['password'] = '********'
        return jsonify(config)
    except Exception as e:
        logger.error(f"Get config error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['POST'])
def save_config():
    try:
        new_config = request.json
        if config_manager.update_config(new_config):
            # Reload scheduler if config changed
            scheduler_manager.reload_job()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Failed to save config'}), 500
    except Exception as e:
        logger.error(f"Save config error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/monitor/start', methods=['POST'])
def start_monitor():
    global monitor_running, watcher
    try:
        from app.watcher import Watcher
        if monitor_running:
            return jsonify({'success': False, 'error': 'Monitor already running'}), 400
        
        watcher = Watcher(uploader.add_task)
        if watcher.start():
            monitor_running = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Failed to start monitor'}), 500
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
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Stop monitor error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync/full', methods=['POST'])
def trigger_full_sync():
    try:
        if syncer.running:
            return jsonify({'success': False, 'error': 'Sync already running'}), 400
        
        # Run in background thread
        def run_sync():
            syncer.execute_full_sync(triggered_by='manual')
        
        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()
        
        return jsonify({'success': True, 'task_id': syncer.current_task_id})
    except Exception as e:
        logger.error(f"Trigger sync error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync/abort', methods=['POST'])
def abort_sync():
    try:
        if syncer.abort_sync():
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'No sync running'}), 400
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
    try:
        webdav_config = request.json
        success, message = rclone_client.test_connection(webdav_config)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Test WebDAV error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/test/dir', methods=['POST'])
def test_directory():
    try:
        path = request.json.get('path')
        if not path:
            return jsonify({'success': False, 'message': 'No path provided'}), 400
        
        if not os.path.exists(path):
            return jsonify({'success': False, 'message': f'Path does not exist: {path}'}), 400
        
        if not os.path.isdir(path):
            return jsonify({'success': False, 'message': f'Not a directory: {path}'}), 400
        
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
            'message': 'Directory is accessible',
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
            return jsonify({'error': 'Path does not exist'}), 404
        
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
            return jsonify({'error': 'Permission denied'}), 403
        
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
