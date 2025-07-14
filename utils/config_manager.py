"""
配置管理器

负责读取和管理项目配置文件。
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from utils.logger import get_logger


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_path (Optional[str]): 配置文件路径，如果为None则使用默认路径
        """
        self.logger = get_logger("config_manager")
        
        # 确定配置文件路径
        if config_path is None:
            # 默认配置文件路径
            project_root = Path(__file__).parent.parent
            self.config_path = project_root / "config" / "config.yaml"
        else:
            self.config_path = Path(config_path)
        
        self.config_data: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self) -> bool:
        """
        加载配置文件
        
        Returns:
            bool: 是否成功加载
        """
        try:
            if not self.config_path.exists():
                self.logger.warning(f"配置文件不存在: {self.config_path}")
                self._create_default_config()
                return False
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f) or {}
            
            self.logger.info(f"成功加载配置文件: {self.config_path}")
            return True
        
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            self.config_data = {}
            return False
    
    def save_config(self) -> bool:
        """
        保存配置文件
        
        Returns:
            bool: 是否成功保存
        """
        try:
            # 确保配置目录存在
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, 
                         allow_unicode=True, indent=2)
            
            self.logger.info(f"成功保存配置文件: {self.config_path}")
            return True
        
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")
            return False
    
    def _create_default_config(self):
        """创建默认配置"""
        self.config_data = {
            'imu': {
                'device_names': {},
                'scan': {
                    'duration': 10.0,
                    'name_filter': ["im948"]
                },
                'connection': {
                    'max_devices': 3,
                    'reconnect_attempts': 5,
                    'reconnect_delay': 5.0,
                    'buffer_size': 200
                },
                'writer': {
                    'queue_size': 1000
                }
            },
            'camera': {
                'device_names': {},
                'connection': {
                    'max_devices': 3,
                    'default_fps': 30.0,
                    'default_resolution': {'width': 1920, 'height': 1080},
                    'buffer_size': 10
                },
                'writer': {
                    'queue_size': 1000
                }
            },
            'multiprocess': {
                'processes': {
                    'imu_count': 1,
                    'camera_count': 1
                },
                'management': {
                    'startup_timeout': 10.0,
                    'shutdown_timeout': 5.0,
                    'monitor_interval': 1.0
                }
            },
            'logging': {
                'level': 'INFO',
                'file_path': str(Path.cwd() / "logs")
            },
            'app': {
                'ui': {
                    'theme': 'light',
                    'language': 'zh_CN'
                },
                'performance': {
                    'buffer_size': 1000,
                    'queue_size': 1000
                }
            }
        }
        
        # 保存默认配置
        self.save_config()
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key_path (str): 配置键路径，使用点号分隔，如 "imu.data_path"
            default (Any): 默认值
            
        Returns:
            Any: 配置值
        """
        try:
            keys = key_path.split('.')
            value = self.config_data
            
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default
            
            return value
        
        except Exception:
            return default
    
    def set(self, key_path: str, value: Any) -> bool:
        """
        设置配置值
        
        Args:
            key_path (str): 配置键路径，使用点号分隔
            value (Any): 配置值
            
        Returns:
            bool: 是否成功设置
        """
        try:
            keys = key_path.split('.')
            current = self.config_data
            
            # 导航到最后一级的父节点
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            
            # 设置值
            current[keys[-1]] = value
            return True
        
        except Exception as e:
            self.logger.error(f"设置配置值失败: {e}")
            return False
    
    # IMU相关配置方法
    def get_imu_device_name(self, address: str) -> Optional[str]:
        """
        获取IMU设备的自定义名称
        
        Args:
            address (str): 设备地址
            
        Returns:
            Optional[str]: 自定义名称
        """
        device_names = self.get('imu.device_names', {})
        return device_names.get(address, None)
    
    def set_imu_device_name(self, address: str, name: str) -> bool:
        """
        设置IMU设备的自定义名称
        
        Args:
            address (str): 设备地址
            name (str): 自定义名称
            
        Returns:
            bool: 是否成功设置
        """
        device_names = self.get('imu.device_names', {})
        device_names[address] = name
        return self.set('imu.device_names', device_names)
    
    def get_imu_scan_settings(self) -> Dict[str, Any]:
        """
        获取IMU扫描设置
        
        Returns:
            Dict[str, Any]: 扫描设置
        """
        return self.get('imu.scan', {
            'duration': 10.0,
            'name_filter': ["im948"]
        })
    
    def get_imu_connection_settings(self) -> Dict[str, Any]:
        """
        获取IMU连接设置
        
        Returns:
            Dict[str, Any]: 连接设置
        """
        return self.get('imu.connection', {
            'max_devices': 3,
            'reconnect_attempts': 5,
            'reconnect_delay': 5.0
        })
    
    # 摄像头相关配置方法
    def get_camera_connection_settings(self) -> Dict[str, Any]:
        """
        获取摄像头连接设置
        
        Returns:
            Dict[str, Any]: 摄像头连接设置字典
        """
        return self.get('camera.connection', {
            'max_devices': 3,
            'default_fps': 30.0,
            'default_resolution': {'width': 1920, 'height': 1080}
        })

    def get_camera_default_fps(self) -> float:
        """
        获取摄像头默认帧率
        
        Returns:
            float: 默认帧率
        """
        return self.get('camera.connection.default_fps', 30.0)
    
    def get_camera_default_resolution(self) -> Dict[str, int]:
        """
        获取摄像头默认分辨率
        
        Returns:
            Dict[str, int]: 默认分辨率
        """
        return self.get('camera.connection.default_resolution', {'width': 1920, 'height': 1080})
    
    def get_camera_writer_settings(self) -> Dict[str, Any]:
        """
        获取摄像头写入线程设置
        
        Returns:
            Dict[str, Any]: 摄像头写入线程设置字典
        """
        return self.get('camera.writer', {'queue_size': 1000})

    def get_imu_writer_settings(self) -> Dict[str, Any]:
        """
        获取IMU写入线程设置
        
        Returns:
            Dict[str, Any]: IMU写入线程设置字典
        """
        return self.get('imu.writer', {'queue_size': 1000})
    
    # 多进程配置相关方法
    def get_multiprocess_config(self) -> Dict[str, Any]:
        """
        获取多进程配置
        
        Returns:
            Dict[str, Any]: 多进程配置字典
        """
        return self.get('multiprocess', {
            'processes': {'imu_count': 1, 'camera_count': 1},
            'management': {
                'startup_timeout': 10.0,
                'shutdown_timeout': 5.0,
                'monitor_interval': 1.0
            }
        })
    
    def get_process_counts(self) -> Dict[str, int]:
        """
        获取进程数量配置
        
        Returns:
            Dict[str, int]: 进程数量字典
        """
        return self.get('multiprocess.processes', {'imu_count': 1, 'camera_count': 1})
    
    def set_process_counts(self, imu_count: int, camera_count: int) -> bool:
        """
        设置进程数量配置
        
        Args:
            imu_count (int): IMU进程数量
            camera_count (int): 摄像头进程数量
            
        Returns:
            bool: 是否成功设置
        """
        success = True
        success &= self.set('multiprocess.processes.imu_count', imu_count)
        success &= self.set('multiprocess.processes.camera_count', camera_count)
        
        if success:
            success &= self.save_config()
        
        return success
    
    def get_multiprocess_management_settings(self) -> Dict[str, float]:
        """
        获取多进程管理设置
        
        Returns:
            Dict[str, float]: 多进程管理设置字典
        """
        return self.get('multiprocess.management', {
            'startup_timeout': 10.0,
            'shutdown_timeout': 5.0,
            'monitor_interval': 1.0
        })


# 全局配置管理器实例
_config_manager = None

def get_config_manager() -> ConfigManager:
    """
    获取全局配置管理器实例
    
    Returns:
        ConfigManager: 配置管理器实例
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager 