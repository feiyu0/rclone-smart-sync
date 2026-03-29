import os
import logging
from typing import List, Dict, Set
from datetime import datetime, timedelta
import threading

from app.database import db
from app.rclone_client import rclone_client
from app.config_manager import config_manager
from app.uploader import uploader
from app.utils import is_video_file, should_ignore, get_file_info

logger = logging.getLogger(__name__)

class Syncer:
    def __init__(self):
        self.running = False
        self.current_task_id = None
        self.lock = threading.Lock()
    
    def scan_local(self, local_path: str, extensions: List[str], ignore_dirs: List[str]) -> List[Dict]:
        try:
            files = []
            for root, dirs, filenames in os.walk(local_path):
                # Filter ignored directories
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                
                for filename in filenames:
                    if is_video_file(filename, extensions):
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, local_path)
                        size, mtime = get_file_info(full_path)
                        if size > 0:
                            files.append({
                                'local_path': full_path,
                                'rel_path': rel_path,
                                'size': size,
                                'mtime': mtime
                            })
            logger.info(f"Scanned {len(files)} local files")
            return files
        except Exception as e:
            logger.error(f"Scan local error: {e}")
            return []
    
    def fetch_remote_snapshot(self, remote_path: str, ttl_hours: int = 24) -> Dict[str, Dict]:
        try:
            # Check if snapshot is still valid
            snapshot = db.get_webdav_snapshot()
            if snapshot:
                # Check snapshot age from first entry
                # For simplicity, we'll always fetch fresh snapshot for full sync
                pass
            
            # Fetch fresh snapshot
            logger.info("Fetching remote file list...")
            remote_files = rclone_client.list_remote_files(remote_path)
            snapshot_dict = {f['path']: {'size': f['size'], 'mtime': f['mtime']} for f in remote_files}
            
            # Update database
            db.update_webdav_snapshot(remote_files)
            
            logger.info(f"Fetched {len(snapshot_dict)} remote files")
            return snapshot_dict
        except Exception as e:
            logger.error(f"Fetch remote snapshot error: {e}")
            return {}
    
    def compare_and_queue(self, local_files: List[Dict], remote_snapshot: Dict[str, Dict], 
                          remote_base: str, upload_config: Dict) -> int:
        try:
            queued_count = 0
            overwrite_policy = upload_config.get('overwrite_policy', 'skip')
            
            for local_file in local_files:
                remote_path = os.path.join(remote_base, local_file['rel_path']).replace('\\', '/')
                
                # Check if needs upload
                needs_upload = False
                
                if remote_path not in remote_snapshot:
                    needs_upload = True
                elif overwrite_policy == 'overwrite':
                    # Check size or mtime difference
                    remote_file = remote_snapshot[remote_path]
                    if remote_file['size'] != local_file['size']:
                        needs_upload = True
                    elif remote_file.get('mtime') != local_file['mtime']:
                        needs_upload = True
                # else: skip if exists
                
                if needs_upload:
                    if uploader.add_task(local_file['local_path'], remote_path, 
                                        local_file['size'], local_file['mtime'], 'fullsync'):
                        queued_count += 1
                        if queued_count % 100 == 0:
                            logger.info(f"Queued {queued_count} files...")
            
            logger.info(f"Queued {queued_count} files for upload")
            return queued_count
        except Exception as e:
            logger.error(f"Compare and queue error: {e}")
            return 0
    
    def execute_full_sync(self, triggered_by: str = 'manual') -> bool:
        with self.lock:
            if self.running:
                logger.warning("Sync already running")
                return False
            self.running = True
        
        try:
            # Create sync task record
            self.current_task_id = db.create_sync_task(triggered_by)
            if self.current_task_id < 0:
                raise Exception("Failed to create sync task")
            
            config = config_manager.get_sync_config()
            monitor_config = config_manager.get_monitor_config()
            webdav_config = config_manager.get_webdav_config()
            upload_config = config_manager.get_upload_config()
            
            local_path = monitor_config.get('local_path')
            extensions = monitor_config.get('extensions', [])
            ignore_dirs = monitor_config.get('ignore_dirs', [])
            remote_base = webdav_config.get('remote_path', '/')
            
            # Step 1: Scan local files
            logger.info("Starting full sync...")
            local_files = self.scan_local(local_path, extensions, ignore_dirs)
            db.update_sync_task(self.current_task_id, total_files=len(local_files))
            
            # Step 2: Fetch remote snapshot
            remote_snapshot = self.fetch_remote_snapshot(remote_base, config.get('snapshot_ttl_hours', 24))
            
            # Step 3: Compare and queue
            queued = self.compare_and_queue(local_files, remote_snapshot, remote_base, upload_config)
            
            # Wait for queue to drain (with timeout)
            wait_timeout = 3600  # 1 hour
            wait_interval = 5
            elapsed = 0
            while uploader.get_queue_size() > 0 and elapsed < wait_timeout:
                import time
                time.sleep(wait_interval)
                elapsed += wait_interval
                logger.info(f"Waiting for upload queue to drain... ({uploader.get_queue_size()} remaining)")
            
            # Get final stats from database
            failed_tasks = db.get_pending_tasks('failed')
            uploaded_count = len(db.get_pending_tasks('done')) if False else queued - len(failed_tasks)  # Simplified
            
            db.update_sync_task(self.current_task_id, status='done', 
                               uploaded_files=queued - len(failed_tasks),
                               failed_files=len(failed_tasks))
            
            logger.info(f"Full sync completed: queued={queued}, failed={len(failed_tasks)}")
            return True
            
        except Exception as e:
            logger.error(f"Full sync error: {e}")
            if self.current_task_id:
                db.update_sync_task(self.current_task_id, status='failed', error_message=str(e))
            return False
        finally:
            self.running = False
            self.current_task_id = None
    
    def abort_sync(self) -> bool:
        with self.lock:
            if not self.running:
                return False
            self.running = False
            if self.current_task_id:
                db.update_sync_task(self.current_task_id, status='cancelled')
            logger.info("Sync aborted")
            return True

syncer = Syncer()
