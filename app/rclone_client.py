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
    def is_password_encrypted(password: str) -> bool:
        """检查密码是否已加密"""
        return password.startswith('XXXX') or password.startswith('BASE64_')
    
    def copy_file(self, local_path: str, remote_path: str, callback: Optional[Callable] = None) -> bool:
        try:
            webdav_config = self._get_webdav_config()
            remote_name = f"webdav_{os.getpid()}"
            
            # 获取密码（已经是加密格式，rclone 可以直接使用）
            password = webdav_config.get('password', '')
            
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
            try:
                os.unlink(config_file)
            except:
                pass
            
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
        """测试 WebDAV 连接"""
        try:
            remote_name = f"webdav_test_{os.getpid()}"
            config_file = f"/tmp/rclone_test_{os.getpid()}.conf"
            
            # 获取密码
            password = webdav_config.get('password', '')
            
            # 如果密码是明文且不为空，先加密
            if password and not self.is_password_encrypted(password):
                logger.info("Testing connection with plain password, encrypting first...")
                password = self.obscure_password(password)
            
            # 创建 rclone 配置文件
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
            
            # 测试连接：列出根目录
            cmd = ["rclone", "lsf", f"{remote_name}:", "--config", config_file, "--max-depth=1"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            # 清理临时配置文件
            try:
                os.unlink(config_file)
            except:
                pass
            
            if result.returncode == 0:
                return True, "连接成功"
            else:
                error_msg = result.stderr.strip()
                logger.error(f"Connection test failed: {error_msg}")
                return False, f"连接失败: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, "连接超时"
        except Exception as e:
            logger.error(f"Test connection error: {e}")
            return False, f"连接错误: {str(e)}"
    
    def list_remote_files(self, remote_path: str) -> List[Dict]:
        """列出远程文件"""
        try:
            webdav_config = self._get_webdav_config()
            remote_name = f"webdav_list_{os.getpid()}"
            config_file = f"/tmp/rclone_list_{os.getpid()}.conf"
            
            password = webdav_config.get('password', '')
            
            # 确保密码是加密格式
            if password and not self.is_password_encrypted(password):
                password = self.obscure_password(password)
            
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
            
            try:
                os.unlink(config_file)
            except:
                pass
            
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
