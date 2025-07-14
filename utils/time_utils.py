"""
时间戳管理工具

提供统一的时间戳格式和转换功能，确保系统中所有时间戳的一致性。
"""

import time
from datetime import datetime
from typing import Union


class TimeUtils:
    """时间戳管理工具类"""
    
    @staticmethod
    def get_timestamp_ms() -> int:
        """
        获取当前时间戳（毫秒）
        
        Returns:
            int: 当前时间戳（毫秒）
        """
        return int(time.time() * 1000)
    
    @staticmethod
    def get_timestamp_us() -> int:
        """
        获取当前时间戳（微秒）
        
        Returns:
            int: 当前时间戳（微秒）
        """
        return int(time.time() * 1000000)
    
    @staticmethod
    def timestamp_to_datetime(timestamp_ms: int) -> datetime:
        """
        将毫秒时间戳转换为datetime对象
        
        Args:
            timestamp_ms (int): 毫秒时间戳
            
        Returns:
            datetime: 对应的datetime对象
        """
        return datetime.fromtimestamp(timestamp_ms / 1000.0)
    
    @staticmethod
    def datetime_to_timestamp(dt: datetime) -> int:
        """
        将datetime对象转换为毫秒时间戳
        
        Args:
            dt (datetime): datetime对象
            
        Returns:
            int: 对应的毫秒时间戳
        """
        return int(dt.timestamp() * 1000)
    
    @staticmethod
    def format_timestamp(timestamp_ms: int, format_str: str = "%Y-%m-%d %H:%M:%S.%f") -> str:
        """
        格式化时间戳为字符串
        
        Args:
            timestamp_ms (int): 毫秒时间戳
            format_str (str): 格式字符串
            
        Returns:
            str: 格式化后的时间字符串
        """
        dt = TimeUtils.timestamp_to_datetime(timestamp_ms)
        return dt.strftime(format_str)[:-3]  # 去掉微秒的后三位，保留毫秒
    
    @staticmethod
    def get_filename_timestamp() -> str:
        """
        获取适合用作文件名的时间戳字符串
        
        Returns:
            str: 格式为 YYYYMMDD_HHMMSS 的时间戳字符串
        """
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    @staticmethod
    def get_session_id() -> str:
        """
        获取会话ID，用于标识一次采集会话
        
        Returns:
            str: 会话ID字符串
        """
        return f"session_{TimeUtils.get_filename_timestamp()}"
    
    @staticmethod
    def sync_timestamps(*timestamps: int) -> dict:
        """
        同步多个时间戳，计算相对时间偏移
        
        Args:
            *timestamps: 多个时间戳
            
        Returns:
            dict: 包含基准时间戳和相对偏移的字典
        """
        if not timestamps:
            return {}
        
        base_timestamp = min(timestamps)
        return {
            'base_timestamp': base_timestamp,
            'offsets': [ts - base_timestamp for ts in timestamps]
        }


# 全局时间戳管理器实例
time_manager = TimeUtils()


def get_current_timestamp() -> int:
    """
    获取当前时间戳的便捷函数
    
    Returns:
        int: 当前毫秒时间戳
    """
    return time_manager.get_timestamp_ms()


def format_timestamp(timestamp_ms: int, format_str: str = "%Y-%m-%d %H:%M:%S.%f") -> str:
    """
    格式化时间戳为字符串的便捷函数
    
    Args:
        timestamp_ms (int): 毫秒时间戳
        format_str (str): 格式字符串
        
    Returns:
        str: 格式化后的时间字符串
    """
    return time_manager.format_timestamp(timestamp_ms, format_str)


def format_current_time(format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化当前时间的便捷函数
    
    Args:
        format_str (str): 格式字符串
        
    Returns:
        str: 格式化后的当前时间字符串
    """
    return datetime.now().strftime(format_str) 