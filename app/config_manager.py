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
            
            # 加密密码（仅当密码是明文且非空时）
            if 'webdav' in config and 'password' in config['webdav']:
                password = config['webdav']['password']
                # 如果密码不是加密格式且不为空，则加密
                if password and not self._is_password_encrypted(password):
                    from app.rclone_client import rclone_client
                    encrypted = rclone_client.obscure_password(password)
                    config['webdav']['password'] = encrypted
                    logger.info("Password encrypted before saving")
            
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            self.config = config
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def _is_password_encrypted(self, password: str) -> bool:
        """检查密码是否已加密"""
        return password.startswith('XXXX') or password.startswith('BASE64_')
    
    def validate_config(self) -> List[str]:
        missing = []
        try:
            if not self.config.get('webdav', {}).get('url'):
                missing.append('webdav.url')
            if not self.config.get('monitor', {}).get('local_path'):
                missing.append('monitor.local_path')
            if not os.path.exists(self.config.get('monitor', {}).get('local_path', '')):
                missing.append('monitor.local_path (路径不存在)')
        except Exception as e:
            logger.error(f"Config validation error: {e}")
            missing.append(f"验证错误: {str(e)}")
        return missing
    
    def get_webdav_config(self) -> Dict:
        """获取 WebDAV 配置（密码保持加密状态）"""
        return self.config.get('webdav', DEFAULT_CONFIG['webdav']).copy()
    
    def get_webdav_password_encrypted(self) -> str:
        """获取加密后的密码"""
        return self.config.get('webdav', {}).get('password', '')
    
    def get_monitor_config(self) -> Dict:
        return self.config.get('monitor', DEFAULT_CONFIG['monitor']).copy()
    
    def get_upload_config(self) -> Dict:
        return self.config.get('upload', DEFAULT_CONFIG['upload']).copy()
    
    def get_sync_config(self) -> Dict:
        return self.config.get('sync', DEFAULT_CONFIG['sync']).copy()
    
    def update_config(self, updates: Dict) -> bool:
        try:
            # 处理密码加密
            if 'webdav' in updates and 'password' in updates['webdav']:
                password = updates['webdav']['password']
                # 如果密码是占位符，跳过
                if password == '********':
                    # 保持原密码
                    if 'webdav' in self.config:
                        updates['webdav']['password'] = self.config['webdav'].get('password', '')
                elif password and not self._is_password_encrypted(password):
                    # 明文密码，需要加密
                    from app.rclone_client import rclone_client
                    updates['webdav']['password'] = rclone_client.obscure_password(password)
                    logger.info("Password encrypted during config update")
                # 如果已经是加密格式，保持不变
            
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
