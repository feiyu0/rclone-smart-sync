import json
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "webdav": {
        "url": "",
        "username": "",
        "password": "",
        "remote_path": "/"
    },
    "monitor": {
        "local_path": "",
        "extensions": ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "ts", "m2ts", "3gp", "ogv", "rmvb", "vob", "iso"],
        "ignore_dirs": ["@eaDir", "@Recycle", "tmp", "metadata", ".DS_Store", "Thumbs.db"]
    },
    "upload": {
        "concurrency": 3,
        "overwrite_policy": "skip",
        "retry_count": 3,
        "timeout_seconds": 300
    },
    "sync": {
        "schedule_enabled": False,
        "schedule_cron": "0 3 * * *",
        "bwlimit": "",
        "snapshot_ttl_hours": 24
    },
    "log": {
        "level": "INFO",
        "retain_days": 7
    }
}

class ConfigManager:
    def __init__(self, config_path: str = "/config/config.json"):
        self.config_path = config_path
        self.config = None
        self.load_config()
    
    def load_config(self) -> Dict:
        try:
            if not os.path.exists(self.config_path):
                self.save_config(DEFAULT_CONFIG.copy())
                logger.info(f"Created default config at {self.config_path}")
            
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
                # Merge with defaults for missing keys
                self.config = self._merge_config(DEFAULT_CONFIG, self.config)
            return self.config
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self.config = DEFAULT_CONFIG.copy()
            return self.config
    
    def _merge_config(self, default: Dict, user: Dict) -> Dict:
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result
    
    def save_config(self, config: Dict = None) -> bool:
        try:
            if config is None:
                config = self.config
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            self.config = config
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def validate_config(self) -> List[str]:
        missing = []
        try:
            if not self.config.get('webdav', {}).get('url'):
                missing.append('webdav.url')
            if not self.config.get('monitor', {}).get('local_path'):
                missing.append('monitor.local_path')
            if not os.path.exists(self.config.get('monitor', {}).get('local_path', '')):
                missing.append('monitor.local_path (path does not exist)')
        except Exception as e:
            logger.error(f"Config validation error: {e}")
            missing.append(f"validation error: {str(e)}")
        return missing
    
    def get_webdav_config(self) -> Dict:
        return self.config.get('webdav', DEFAULT_CONFIG['webdav']).copy()
    
    def get_monitor_config(self) -> Dict:
        return self.config.get('monitor', DEFAULT_CONFIG['monitor']).copy()
    
    def get_upload_config(self) -> Dict:
        return self.config.get('upload', DEFAULT_CONFIG['upload']).copy()
    
    def get_sync_config(self) -> Dict:
        return self.config.get('sync', DEFAULT_CONFIG['sync']).copy()
    
    def update_config(self, updates: Dict) -> bool:
        try:
            for section, values in updates.items():
                if section in self.config and isinstance(values, dict):
                    self.config[section].update(values)
                elif section in self.config:
                    self.config[section] = values
                else:
                    self.config[section] = values
            return self.save_config()
        except Exception as e:
            logger.error(f"Failed to update config: {e}")
            return False

config_manager = ConfigManager()
