"""
文件路径管理工具

提供统一的文件路径管理和目录创建功能，确保数据存储结构的一致性。
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Union
from .time_utils import TimeUtils

# 定义项目根目录 (相对于此文件的位置)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PathUtils:
    """文件路径管理工具类"""
    
    def __init__(self, base_data_dir: Union[str, Path] = "data"):
        """
        初始化路径管理器
        
        Args:
            base_data_dir (Union[str, Path]): 基础数据目录。
                                            可以是绝对路径，或相对于项目根目录的相对路径。
        """
        base_path = Path(base_data_dir)
        if base_path.is_absolute():
            self.base_data_dir = base_path
        else:
            self.base_data_dir = PROJECT_ROOT / base_path
        
        self.ensure_dir_exists(self.base_data_dir)
    
    def ensure_dir_exists(self, path: Union[str, Path]) -> Path:
        """
        确保目录存在，如果不存在则创建
        
        Args:
            path (Union[str, Path]): 目录路径
            
        Returns:
            Path: 路径对象
        """
        path_obj = Path(path)
        path_obj.mkdir(parents=True, exist_ok=True)
        return path_obj
    
    def create_session_dir(self, session_id: Optional[str] = None) -> Path:
        """
        创建会话目录
        
        Args:
            session_id (Optional[str]): 会话ID，如果为None则自动生成
            
        Returns:
            Path: 会话目录路径
        """
        if session_id is None:
            session_id = f"record_{TimeUtils.get_filename_timestamp()}"
        
        session_dir = self.base_data_dir / session_id
        self.ensure_dir_exists(session_dir)
        
        # 创建子目录
        self.ensure_dir_exists(session_dir / "imu")
        self.ensure_dir_exists(session_dir / "video")
        
        return session_dir
    
    def get_imu_file_path(self, session_dir: Path, imu_id: str) -> Path:
        """
        获取IMU数据文件路径
        
        Args:
            session_dir (Path): 会话目录
            imu_id (str): IMU设备ID
            
        Returns:
            Path: IMU数据文件路径
        """
        return session_dir / "imu" / f"{imu_id}.csv"
    
    def get_video_file_path(self, session_dir: Path, camera_id: str) -> Path:
        """
        获取视频文件路径
        
        Args:
            session_dir (Path): 会话目录
            camera_id (str): 摄像头ID
            
        Returns:
            Path: 视频文件路径
        """
        return session_dir / "video" / f"{camera_id}.avi"
    
    def get_meta_file_path(self, session_dir: Path) -> Path:
        """
        获取元数据文件路径
        
        Args:
            session_dir (Path): 会话目录
            
        Returns:
            Path: 元数据文件路径
        """
        return session_dir / "meta.json"
    
    def get_log_file_path(self, session_dir: Path) -> Path:
        """
        获取日志文件路径
        
        Args:
            session_dir (Path): 会话目录
            
        Returns:
            Path: 日志文件路径
        """
        return session_dir / "log.txt"
    
    def save_session_meta(self, session_dir: Path, meta_data: Dict) -> None:
        """
        保存会话元数据
        
        Args:
            session_dir (Path): 会话目录
            meta_data (Dict): 元数据字典
        """
        meta_file = self.get_meta_file_path(session_dir)
        
        # 添加默认元数据
        default_meta = {
            "session_id": session_dir.name,
            "created_at": TimeUtils.format_timestamp(TimeUtils.get_timestamp_ms()),
            "version": "1.0.0"
        }
        
        # 合并元数据
        final_meta = {**default_meta, **meta_data}
        
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(final_meta, f, indent=2, ensure_ascii=False)
    
    def load_session_meta(self, session_dir: Path) -> Optional[Dict]:
        """
        加载会话元数据
        
        Args:
            session_dir (Path): 会话目录
            
        Returns:
            Optional[Dict]: 元数据字典，如果文件不存在则返回None
        """
        meta_file = self.get_meta_file_path(session_dir)
        
        if not meta_file.exists():
            return None
        
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def list_sessions(self) -> List[str]:
        """
        列出所有会话目录
        
        Returns:
            List[str]: 会话ID列表
        """
        if not self.base_data_dir.exists():
            return []
        
        sessions = []
        for item in self.base_data_dir.iterdir():
            if item.is_dir() and item.name.startswith(('record_', 'session_')):
                sessions.append(item.name)
        
        return sorted(sessions, reverse=True)  # 按时间倒序排列
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """
        获取会话信息
        
        Args:
            session_id (str): 会话ID
            
        Returns:
            Optional[Dict]: 会话信息字典
        """
        session_dir = self.base_data_dir / session_id
        if not session_dir.exists():
            return None
        
        info = {
            "session_id": session_id,
            "path": str(session_dir),
            "created_at": None,
            "imu_files": [],
            "video_files": [],
            "has_meta": False,
            "has_log": False
        }
        
        # 检查元数据
        meta_data = self.load_session_meta(session_dir)
        if meta_data:
            info["has_meta"] = True
            info["created_at"] = meta_data.get("created_at")
            info["meta_data"] = meta_data
        
        # 检查日志文件
        log_file = self.get_log_file_path(session_dir)
        info["has_log"] = log_file.exists()
        
        # 列出IMU文件
        imu_dir = session_dir / "imu"
        if imu_dir.exists():
            info["imu_files"] = [f.name for f in imu_dir.glob("*.csv")]
        
        # 列出视频文件
        video_dir = session_dir / "video"
        if video_dir.exists():
            info["video_files"] = [f.name for f in video_dir.glob("*.avi")]
        
        return info
    
    def cleanup_empty_sessions(self) -> int:
        """
        清理空的会话目录
        
        Returns:
            int: 清理的目录数量
        """
        cleaned_count = 0
        
        for session_id in self.list_sessions():
            session_dir = self.base_data_dir / session_id
            
            # 检查是否为空目录
            if self._is_empty_session(session_dir):
                try:
                    # 删除空目录
                    for subdir in session_dir.iterdir():
                        if subdir.is_dir():
                            subdir.rmdir()
                    session_dir.rmdir()
                    cleaned_count += 1
                except OSError:
                    # 如果删除失败，跳过
                    continue
        
        return cleaned_count
    
    def _is_empty_session(self, session_dir: Path) -> bool:
        """
        检查会话目录是否为空
        
        Args:
            session_dir (Path): 会话目录
            
        Returns:
            bool: 是否为空目录
        """
        if not session_dir.exists():
            return True
        
        # 检查是否有实际的数据文件
        imu_dir = session_dir / "imu"
        video_dir = session_dir / "video"
        
        has_imu_data = imu_dir.exists() and any(f.stat().st_size > 0 for f in imu_dir.glob("*.csv"))
        has_video_data = video_dir.exists() and any(f.stat().st_size > 0 for f in video_dir.glob("*.avi"))
        
        return not (has_imu_data or has_video_data)


# 全局路径管理器实例
path_manager = PathUtils()


def get_default_data_dir() -> Path:
    """
    获取默认数据目录
    
    Returns:
        Path: 默认数据目录路径
    """
    return path_manager.base_data_dir


def create_session_directory(session_id: Optional[str] = None) -> Path:
    """
    创建会话目录的便捷函数
    
    Args:
        session_id (Optional[str]): 会话ID
        
    Returns:
        Path: 会话目录路径
    """
    return path_manager.create_session_dir(session_id) 