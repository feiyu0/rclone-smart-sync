import subprocess
import logging
import json
import os
import base64
import tempfile
from typing import List, Dict, Optional, Callable, Tuple
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
            return password
    
    @staticmethod
    def is_password_encrypted(password: str) -> bool:
        """检查密码是否已加密"""
        return password.startswith('XXXX') or password.startswith('BASE64_')
    
    @staticmethod
    def test_connection(webdav_config: dict) -> Tuple[bool, str, Optional[dict]]:
        """测试 WebDAV 连接，返回 (success, message, debug_info)"""
        url = webdav_config.get('url')
        username = webdav_config.get('username', '')
        password = webdav_config.get('password', '')
        
        if not url:
            return False, "URL 不能为空", None
        
        temp_config = None
        
        try:
            # 确保密码是加密格式
            if password and not RcloneClient.is_password_encrypted(password):
                password = RcloneClient.obscure_password(password)
            
            # 创建临时配置文件
            temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False)
            
            # 写入配置文件
            config_content = f"""[webdav_test]
type = webdav
url = {url}
vendor = other
"""
            if username:
                config_content += f"user = {username}\n"
            if password:
                config_content += f"pass = {password}\n"
            
            temp_config.write(config_content)
            temp_config.close()
            
            # 测试命令：列出根目录
            cmd = [
                "rclone", "lsf", "webdav_test:/",
                "--config", temp_config.name,
                "--max-depth", "1",
                "--timeout", "30s",
                "--retries", "1",
                "-v"
            ]
            
            logger.info(f"Testing WebDAV connection to {url}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=35
            )
            
            debug_info = {
                "url": url,
                "username": username,
                "returncode": result.returncode,
                "stdout": result.stdout[:500] if result.stdout else "",
                "stderr": result.stderr[:500] if result.stderr else ""
            }
            
            if result.returncode == 0:
                logger.info("WebDAV connection test successful")
                return True, "连接成功", debug_info
            else:
                error_msg = result.stderr.lower()
                
                # 分析错误类型
                if "401" in error_msg or "unauthorized" in error_msg:
                    return False, "❌ 认证失败\n\n请检查：\n1. 用户名是否正确\n2. 密码是否正确\n3. 某些 WebDAV 服务需要专用密码（如 Alist 的 guest 用户需要开启 WebDAV 权限）", debug_info
                elif "403" in error_msg or "forbidden" in error_msg:
                    return False, "❌ 权限不足\n\n请检查：\n1. 用户是否有访问该目录的权限\n2. 远程目录路径是否正确", debug_info
                elif "404" in error_msg or "not found" in error_msg:
                    return False, "❌ 路径不存在\n\n请检查：\n1. WebDAV URL 是否正确\n2. 远程目录是否存在", debug_info
                elif "connection refused" in error_msg:
                    return False, "❌ 连接被拒绝\n\n请检查：\n1. WebDAV 服务是否正在运行\n2. 端口号是否正确\n3. 防火墙是否允许访问", debug_info
                elif "timeout" in error_msg:
                    return False, "❌ 连接超时\n\n请检查：\n1. 网络连接是否正常\n2. 服务器响应是否缓慢\n3. 尝试增加超时时间", debug_info
                elif "no such host" in error_msg or "dns" in error_msg:
                    return False, "❌ DNS 解析失败\n\n请检查：\n1. URL 中的域名是否正确\n2. DNS 服务器是否可访问", debug_info
                else:
                    return False, f"连接失败: {result.stderr[:200]}", debug_info
                
        except subprocess.TimeoutExpired:
            return False, "❌ 连接超时（35秒）\n\n请检查网络连接或增加超时时间", None
        except Exception as e:
            logger.error(f"Test connection error: {e}")
            return False, f"错误: {str(e)}", None
        finally:
            if temp_config and hasattr(temp_config, 'name') and os.path.exists(temp_config.name):
                try:
                    os.unlink(temp_config.name)
                except:
                    pass
    
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
