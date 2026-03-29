import logging
import signal
import sys
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Tuple, List
import pathlib

def setup_logging(level: str = "INFO", log_dir: str = "/logs", retain_days: int = 7):
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "sync.log")
        
        logger = logging.getLogger()
        logger.setLevel(getattr(logging, level.upper()))
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # File handler with rotation
        file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(console_handler)
        
        logging.info(f"Logging configured: level={level}, log_dir={log_dir}")
    except Exception as e:
        print(f"Failed to setup logging: {e}")
        sys.exit(1)

class GracefulKiller:
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        signal.signal(signal.SIGINT, self.exit_gracefully)
    
    def exit_gracefully(self, signum, frame):
        logging.info(f"Received signal {signum}, shutting down gracefully...")
        self.kill_now = True

def setup_signal_handlers():
    return GracefulKiller()

def is_video_file(filename: str, extensions: List[str]) -> bool:
    try:
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        return ext in extensions
    except Exception:
        return False

def should_ignore(path: str, ignore_dirs: List[str]) -> bool:
    try:
        path_parts = pathlib.Path(path).parts
        for ignore in ignore_dirs:
            if ignore in path_parts:
                return True
        return False
    except Exception:
        return False

def get_file_info(path: str) -> Tuple[int, float]:
    try:
        stat = os.stat(path)
        return stat.st_size, stat.st_mtime
    except Exception as e:
        logging.error(f"Failed to get file info for {path}: {e}")
        return 0, 0

def format_size(size_bytes: int) -> str:
    try:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    except Exception:
        return "0 B"

def safe_path_join(base: str, *paths) -> str:
    try:
        base_path = pathlib.Path(base).resolve()
        full_path = base_path.joinpath(*paths).resolve()
        if base_path not in full_path.parents and full_path != base_path:
            raise ValueError(f"Path traversal detected: {full_path}")
        return str(full_path)
    except Exception as e:
        logging.error(f"Path join error: {e}")
        return base

def cleanup_old_logs(log_dir: str = "/logs", retain_days: int = 7):
    try:
        now = datetime.now().timestamp()
        for filename in os.listdir(log_dir):
            filepath = os.path.join(log_dir, filename)
            if os.path.isfile(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > retain_days * 86400:
                    os.remove(filepath)
                    logging.info(f"Removed old log: {filename}")
    except Exception as e:
        logging.error(f"Failed to cleanup logs: {e}")
