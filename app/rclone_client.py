import subprocess
import logging
import json
import os
from typing import List, Dict, Optional, Callable
import threading

logger = logging.getLogger(__name__)

class RcloneClient:
    def __init__(self, timeout_seconds: int = 300):
        self.timeout = timeout_seconds
    
    def copy_file(self, local_path: str, remote_path: str, callback: Optional[Callable] = None) -> bool:
        try:
            webdav_config = self._get_webdav_config()
            remote_name = f"webdav_{os.getpid()}"
            
            # Build rclone config
            config_data = f"""
[{remote_name}]
type = webdav
url = {webdav_config['url']}
vendor = other
user = {webdav_config['username']}
pass = {self._obfuscate_password(webdav_config['password'])}
"""
            config_file = f"/tmp/rclone_config_{os.getpid()}.conf"
            with open(config_file, 'w') as f:
                f.write(config_data)
            
            remote_full = f"{remote_name}:{remote_path}"
            cmd = ["rclone", "copy", local_path, remote_full, "--config", config_file, 
                   "--progress", "--stats-one-line", "-v"]
            
            logger.info(f"Running rclone copy: {local_path} -> {remote_path}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Read output in real-time
            for line in iter(process.stdout.readline, ''):
                if callback:
                    callback(line.strip())
                logger.debug(f"rclone: {line.strip()}")
            
            process.wait(timeout=self.timeout)
            
            # Cleanup
            os.unlink(config_file)
            
            if process.returncode == 0:
                logger.info(f"Successfully copied: {local_path}")
                return True
            else:
                error = process.stderr.read()
                logger.error(f"rclone failed with code {process.returncode}: {error}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"rclone timeout after {self.timeout}s for {local_path}")
            return False
        except Exception as e:
            logger.error(f"rclone copy error: {e}")
            return False
    
    def test_connection(self, webdav_config: Dict) -> tuple[bool, str]:
        try:
            remote_name = f"webdav_test_{os.getpid()}"
            config_file = f"/tmp/rclone_test_{os.getpid()}.conf"
            
            config_data = f"""
[{remote_name}]
type = webdav
url = {webdav_config['url']}
vendor = other
user = {webdav_config['username']}
pass = {self._obfuscate_password(webdav_config['password'])}
"""
            with open(config_file, 'w') as f:
                f.write(config_data)
            
            cmd = ["rclone", "lsf", f"{remote_name}:", "--config", config_file, "--max-depth=1"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            os.unlink(config_file)
            
            if result.returncode == 0:
                return True, "Connection successful"
            else:
                return False, f"Connection failed: {result.stderr}"
        except Exception as e:
            return False, f"Connection error: {str(e)}"
    
    def list_remote_files(self, remote_path: str) -> List[Dict]:
        try:
            webdav_config = self._get_webdav_config()
            remote_name = f"webdav_list_{os.getpid()}"
            config_file = f"/tmp/rclone_list_{os.getpid()}.conf"
            
            config_data = f"""
[{remote_name}]
type = webdav
url = {webdav_config['url']}
vendor = other
user = {webdav_config['username']}
pass = {self._obfuscate_password(webdav_config['password'])}
"""
            with open(config_file, 'w') as f:
                f.write(config_data)
            
            remote_full = f"{remote_name}:{remote_path}"
            cmd = ["rclone", "lsjson", remote_full, "--config", config_file, "--recursive"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            os.unlink(config_file)
            
            if result.returncode == 0:
                files = json.loads(result.stdout)
                return [{"path": f["Path"], "size": f["Size"], "mtime": f["ModTime"]} for f in files if not f["IsDir"]]
            else:
                logger.error(f"Failed to list remote files: {result.stderr}")
                return []
        except Exception as e:
            logger.error(f"List remote files error: {e}")
            return []
    
    def _get_webdav_config(self) -> Dict:
        from app.config_manager import config_manager
        return config_manager.get_webdav_config()
    
    def _obfuscate_password(self, password: str) -> str:
        # rclone obfuscation is not standard, just return as-is for now
        return password

rclone_client = RcloneClient()
