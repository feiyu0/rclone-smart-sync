import subprocess
import logging
import json
import os
import base64
from typing import List, Dict, Optional, Callable
import threading

logger = logging.getLogger(__name__)

class RcloneClient:
    def __init__(self, timeout_seconds: int = 300):
        self.timeout = timeout_seconds
    
    @staticmethod
    def obscure_password(password: str) -> str:
        """使用 rclone obscure 命令加密密码"""
        try:
            # 如果密码已经是加密格式，直接返回
            if password.startswith('XXXX'):
                return password
            
            # 调用 rclone obscure 命令
            result = subprocess.run(
                ['rclone', 'obscure', password],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                encrypted = result.stdout.strip()
                logger.info(f"Password encrypted successfully")
                return encrypted
            else:
                logger.error(f"Rclone obscure failed: {result.stderr}")
                # 回退到 base64 编码
                fallback = base64.b64encode(password.encode()).decode()
                logger.warning(f"Using base64 fallback for password encryption")
                return f"BASE64_{fallback}"
                
        except FileNotFoundError:
            logger.error("Rclone command not found, using base64 fallback")
            fallback = base64.b64encode(password.encode()).decode()
            return f"BASE64_{fallback}"
        except Exception as e:
            logger.error(f"Password encryption error: {e}")
            # 最后的回退方案
            return password
    
    @staticmethod
    def reveal_password(obscured: str) -> str:
        """解密密码（rclone 本身没有官方解密命令）"""
        try:
            if obscured.startswith('BASE64_'):
                # Base64 解码
                encoded = obscured.replace('BASE64_', '')
                return base64.b64decode(encoded).decode()
            elif obscured.startswith('XXXX'):
                # rclone obscure 加密的密码无法直接解密
                # 返回空字符串，提示用户重新输入
                logger.warning("Rclone obscured password cannot be decrypted, please re-enter")
                return ""
            else:
                # 明文密码直接返回
                return obscured
        except Exception as e:
            logger.error(f"Password decryption error: {e}")
            return ""
    
    def copy_file(self, local_path: str, remote_path: str, callback: Optional[Callable] = None) -> bool:
        try:
            webdav_config = self._get_webdav_config()
            remote_name = f"webdav_{os.getpid()}"
            
            # 获取密码（如果是加密的，需要解密）
            password = webdav_config.get('password', '')
            if password.startswith('XXXX') or password.startswith('BASE64_'):
                # 密码已加密，rclone 可以直接使用加密格式
                # 不需要解密，rclone 原生支持
                pass
            
            # Build rclone config
            config_data = f"""
[{remote_name}]
type = webdav
url = {webdav_config['url']}
vendor = other
user = {webdav_config['username']}
pass = {password}
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
            
            # 处理密码
            password = webdav_config.get('password', '')
            
            config_data = f"""
[{remote_name}]
type = webdav
url = {webdav_config['url']}
vendor = other
user = {webdav_config['username']}
pass = {password}
"""
            with open(config_file, 'w') as f:
                f.write(config_data)
            
            cmd = ["rclone", "lsf", f"{remote_name}:", "--config", config_file, "--max-depth=1"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            os.unlink(config_file)
            
            if result.returncode == 0:
                return True, "连接成功"
            else:
                return False, f"连接失败: {result.stderr}"
        except Exception as e:
            return False, f"连接错误: {str(e)}"
    
    def list_remote_files(self, remote_path: str) -> List[Dict]:
        try:
            webdav_config = self._get_webdav_config()
            remote_name = f"webdav_list_{os.getpid()}"
            config_file = f"/tmp/rclone_list_{os.getpid()}.conf"
            
            password = webdav_config.get('password', '')
            
            config_data = f"""
[{remote_name}]
type = webdav
url = {webdav_config['url']}
vendor = other
user = {webdav_config['username']}
pass = {password}
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

rclone_client = RcloneClient()
