"""
日志配置工具

提供统一的日志配置和管理功能，支持控制台输出和文件记录。
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Union
from .time_utils import format_current_time


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""
    
    # 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',    # 红色
        'CRITICAL': '\033[35m', # 紫色
        'RESET': '\033[0m'      # 重置
    }
    
    def format(self, record):
        """
        格式化日志记录
        
        Args:
            record: 日志记录对象
            
        Returns:
            str: 格式化后的日志字符串
        """
        # 获取颜色
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        # 格式化消息
        record.levelname = f"{color}{record.levelname}{reset}"
        
        return super().format(record)


class LoggerManager:
    """日志管理器"""
    
    def __init__(self):
        """初始化日志管理器"""
        self.loggers = {}
        self.file_handlers = {}
        self.console_handler = None
        self._setup_console_handler()
    
    def _setup_console_handler(self):
        """设置控制台处理器"""
        self.console_handler = logging.StreamHandler(sys.stdout)
        self.console_handler.setLevel(logging.INFO)
        
        # 设置彩色格式
        formatter = ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.console_handler.setFormatter(formatter)
    
    def get_logger(self, name: str, level: int = logging.INFO) -> logging.Logger:
        """
        获取或创建日志记录器
        
        Args:
            name (str): 日志记录器名称
            level (int): 日志级别
            
        Returns:
            logging.Logger: 日志记录器实例
        """
        if name in self.loggers:
            return self.loggers[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        # 清除默认处理器
        logger.handlers.clear()
        
        # 添加控制台处理器
        logger.addHandler(self.console_handler)
        
        # 防止重复记录
        logger.propagate = False
        
        self.loggers[name] = logger
        return logger
    
    def add_file_handler(self, logger_name: str, file_path: Union[str, Path], 
                        level: int = logging.DEBUG) -> None:
        """
        为指定的日志记录器添加文件处理器
        
        Args:
            logger_name (str): 日志记录器名称
            file_path (Union[str, Path]): 日志文件路径
            level (int): 文件日志级别
        """
        if logger_name not in self.loggers:
            self.get_logger(logger_name)
        
        logger = self.loggers[logger_name]
        
        # 创建文件处理器
        file_handler = logging.FileHandler(file_path, encoding='utf-8')
        file_handler.setLevel(level)
        
        # 设置文件格式（不需要颜色）
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        self.file_handlers[logger_name] = file_handler
    
    def remove_file_handler(self, logger_name: str) -> None:
        """
        移除指定日志记录器的文件处理器
        
        Args:
            logger_name (str): 日志记录器名称
        """
        if logger_name in self.file_handlers:
            logger = self.loggers[logger_name]
            file_handler = self.file_handlers[logger_name]
            
            logger.removeHandler(file_handler)
            file_handler.close()
            
            del self.file_handlers[logger_name]
    
    def set_console_level(self, level: int) -> None:
        """
        设置控制台日志级别
        
        Args:
            level (int): 日志级别
        """
        self.console_handler.setLevel(level)
    
    def close_all_handlers(self) -> None:
        """关闭所有文件处理器"""
        for logger_name in list(self.file_handlers.keys()):
            self.remove_file_handler(logger_name)


# 全局日志管理器实例
logger_manager = LoggerManager()


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    获取日志记录器的便捷函数
    
    Args:
        name (str): 日志记录器名称
        level (int): 日志级别
        
    Returns:
        logging.Logger: 日志记录器实例
    """
    return logger_manager.get_logger(name, level)


def setup_session_logging(session_dir: Path, logger_name: str = "session") -> logging.Logger:
    """
    为会话设置日志记录
    
    Args:
        session_dir (Path): 会话目录
        logger_name (str): 日志记录器名称
        
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = get_logger(logger_name)
    log_file = session_dir / "log.txt"
    
    # 添加文件处理器
    logger_manager.add_file_handler(logger_name, log_file)
    
    # 记录会话开始
    logger.info(f"会话开始: {session_dir.name}")
    logger.info(f"日志文件: {log_file}")
    
    return logger


def log_system_info(logger: logging.Logger) -> None:
    """
    记录系统信息
    
    Args:
        logger (logging.Logger): 日志记录器
    """
    import platform
    import sys
    
    logger.info("=== 系统信息 ===")
    logger.info(f"操作系统: {platform.system()} {platform.release()}")
    logger.info(f"Python版本: {sys.version}")
    logger.info(f"启动时间: {format_current_time()}")
    logger.info("===============")


def log_device_info(logger: logging.Logger, device_type: str, device_info: dict) -> None:
    """
    记录设备信息
    
    Args:
        logger (logging.Logger): 日志记录器
        device_type (str): 设备类型
        device_info (dict): 设备信息字典
    """
    logger.info(f"=== {device_type}设备信息 ===")
    for key, value in device_info.items():
        logger.info(f"{key}: {value}")
    logger.info("=" * (len(device_type) + 8))


def setup_logging(log_level: int = logging.INFO) -> None:
    """
    设置全局日志配置
    
    Args:
        log_level (int): 日志级别
    """
    # 设置控制台日志级别
    logger_manager.set_console_level(log_level)
    
    # 设置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)


def log_error_with_traceback(logger: logging.Logger, error: Exception, context: str = "") -> None:
    """
    记录错误和堆栈信息
    
    Args:
        logger (logging.Logger): 日志记录器
        error (Exception): 异常对象
        context (str): 错误上下文
    """
    import traceback
    
    error_msg = f"错误发生"
    if context:
        error_msg += f" - {context}"
    
    logger.error(error_msg)
    logger.error(f"错误类型: {type(error).__name__}")
    logger.error(f"错误消息: {str(error)}")
    logger.error("堆栈信息:")
    
    # 记录堆栈信息
    for line in traceback.format_exception(type(error), error, error.__traceback__):
        logger.error(line.rstrip())


# 预定义的日志记录器
main_logger = get_logger("main")
imu_logger = get_logger("imu")
camera_logger = get_logger("camera")
gui_logger = get_logger("gui")
data_logger = get_logger("data") 