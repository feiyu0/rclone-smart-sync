import os
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable, List, Optional

from app.utils import is_video_file, should_ignore, get_file_info
from app.config_manager import config_manager
from app.database import db

logger = logging.getLogger(__name__)

class MediaHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable, extensions: List[str], ignore_dirs: List[str], remote_base: str):
        self.callback = callback
        self.extensions = extensions
        self.ignore_dirs = ignore_dirs
        self.remote_base = remote_base
    
    def on_closed(self, event):
        try:
            if event.is_directory:
                return
            
            src_path = event.src_path
            logger.debug(f"File closed: {src_path}")
            
            # Check if video file
            if not is_video_file(src_path, self.extensions):
                return
            
            # Check ignore dirs
            if should_ignore(src_path, self.ignore_dirs):
                logger.info(f"Ignoring file in ignored directory: {src_path}")
                return
            
            # Wait a bit for file to be fully written
            import time
            time.sleep(0.5)
            
            # Get file info
            file_size, mtime = get_file_info(src_path)
            if file_size == 0:
                logger.warning(f"File size is 0, skipping: {src_path}")
                return
            
            # Check if already uploaded
            if db.is_uploaded(src_path, file_size, mtime):
                logger.info(f"File already uploaded, skipping: {src_path}")
                return
            
            # Build remote path
            monitor_config = config_manager.get_monitor_config()
            local_base = monitor_config.get('local_path', '')
            rel_path = os.path.relpath(src_path, local_base)
            remote_path = os.path.join(self.remote_base, rel_path).replace('\\', '/')
            
            # Add to queue
            self.callback(src_path, remote_path, file_size, mtime, 'realtime')
            
        except Exception as e:
            logger.error(f"Error in on_closed handler: {e}")

class Watcher:
    def __init__(self, callback: Callable):
        self.observer = None
        self.callback = callback
        self.running = False
    
    def start(self) -> bool:
        try:
            if self.running:
                logger.warning("Watcher already running")
                return False
            
            monitor_config = config_manager.get_monitor_config()
            local_path = monitor_config.get('local_path')
            
            if not local_path or not os.path.exists(local_path):
                logger.error(f"Monitor path does not exist: {local_path}")
                return False
            
            extensions = monitor_config.get('extensions', [])
            ignore_dirs = monitor_config.get('ignore_dirs', [])
            webdav_config = config_manager.get_webdav_config()
            remote_base = webdav_config.get('remote_path', '/')
            
            event_handler = MediaHandler(self.callback, extensions, ignore_dirs, remote_base)
            self.observer = Observer()
            self.observer.schedule(event_handler, local_path, recursive=True)
            self.observer.start()
            self.running = True
            
            logger.info(f"Watcher started on {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start watcher: {e}")
            return False
    
    def stop(self):
        try:
            if self.observer:
                self.observer.stop()
                self.observer.join()
                self.running = False
                logger.info("Watcher stopped")
        except Exception as e:
            logger.error(f"Error stopping watcher: {e}")

watcher = None  # Will be initialized in main.py
