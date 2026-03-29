import threading
import queue
import logging
from typing import Dict, Optional, Callable
from datetime import datetime
import time

from app.database import db
from app.rclone_client import rclone_client
from app.config_manager import config_manager

logger = logging.getLogger(__name__)

class Uploader:
    def __init__(self):
        self.task_queue = queue.Queue(maxsize=500)
        self.workers = []
        self.running = False
        self.active_tasks = {}
        self.task_lock = threading.Lock()
        self.progress_callbacks = []
    
    def start(self, concurrency: int = 3):
        try:
            self.running = True
            # Recover pending tasks from database
            pending_tasks = db.get_pending_tasks('pending')
            for task in pending_tasks:
                try:
                    self.task_queue.put_nowait(task)
                    logger.info(f"Recovered pending task: {task['local_path']}")
                except queue.Full:
                    logger.warning(f"Queue full, skipping recovered task: {task['local_path']}")
            
            # Start worker threads
            for i in range(concurrency):
                worker = threading.Thread(target=self._worker, name=f"uploader-{i}", daemon=True)
                worker.start()
                self.workers.append(worker)
            logger.info(f"Uploader started with {concurrency} workers")
        except Exception as e:
            logger.error(f"Failed to start uploader: {e}")
    
    def stop(self):
        try:
            self.running = False
            # Clear queue
            while not self.task_queue.empty():
                try:
                    self.task_queue.get_nowait()
                except queue.Empty:
                    break
            logger.info("Uploader stopped")
        except Exception as e:
            logger.error(f"Error stopping uploader: {e}")
    
    def add_task(self, local_path: str, remote_path: str, file_size: int, mtime: float, source: str) -> bool:
        try:
            # Check if already uploaded
            if db.is_uploaded(local_path, file_size, mtime):
                logger.info(f"File already uploaded, skipping: {local_path}")
                return False
            
            # Check if already in pending queue
            pending = db.get_pending_tasks('pending')
            for task in pending:
                if task['local_path'] == local_path:
                    logger.info(f"Task already pending: {local_path}")
                    return False
            
            # Add to database
            task_id = db.add_pending_task(local_path, remote_path, file_size, mtime, source)
            if task_id > 0:
                task = {
                    'id': task_id,
                    'local_path': local_path,
                    'remote_path': remote_path,
                    'file_size': file_size,
                    'mtime': mtime,
                    'source': source,
                    'retry_count': 0,
                    'status': 'pending'
                }
                self.task_queue.put(task)
                logger.info(f"Added task to queue: {local_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to add task: {e}")
            return False
    
    def register_progress_callback(self, callback: Callable):
        self.progress_callbacks.append(callback)
    
    def _notify_progress(self, task_id: int, progress: str):
        for callback in self.progress_callbacks:
            try:
                callback(task_id, progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    def _worker(self):
        upload_config = config_manager.get_upload_config()
        retry_count_max = upload_config.get('retry_count', 3)
        
        while self.running:
            try:
                task = self.task_queue.get(timeout=1)
                if task is None:
                    continue
                
                with self.task_lock:
                    self.active_tasks[task['id']] = task
                
                # Update status to running
                db.update_pending_task_status(task['id'], 'running')
                
                # Upload file
                def progress_cb(progress):
                    self._notify_progress(task['id'], progress)
                
                success = rclone_client.copy_file(
                    task['local_path'],
                    task['remote_path'],
                    callback=progress_cb
                )
                
                if success:
                    # Add to upload history
                    db.add_upload_history(task['local_path'], task['remote_path'], 
                                         task['file_size'], task['mtime'])
                    # Remove from pending
                    db.delete_pending_task(task['id'])
                    logger.info(f"Successfully uploaded: {task['local_path']}")
                else:
                    # Retry logic
                    new_retry_count = task['retry_count'] + 1
                    if new_retry_count < retry_count_max:
                        db.update_pending_task_status(task['id'], 'pending', new_retry_count)
                        # Re-add to queue
                        task['retry_count'] = new_retry_count
                        self.task_queue.put(task)
                        logger.warning(f"Retry {new_retry_count}/{retry_count_max} for: {task['local_path']}")
                    else:
                        db.update_pending_task_status(task['id'], 'failed', new_retry_count)
                        logger.error(f"Task failed permanently: {task['local_path']}")
                
                with self.task_lock:
                    self.active_tasks.pop(task['id'], None)
                
                self.task_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker error: {e}")
                time.sleep(1)
    
    def get_queue_size(self) -> int:
        return self.task_queue.qsize()
    
    def get_running_tasks(self) -> int:
        with self.task_lock:
            return len(self.active_tasks)

uploader = Uploader()
