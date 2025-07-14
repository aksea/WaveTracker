"""
IMU录制协调器

管理IMU数据采集线程（生产者）和数据写入线程（消费者）之间的协调。
实现完整的生产者-消费者架构。
"""

from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal

from utils.logger import get_logger
from utils.time_utils import time_manager
from .imu_reader_thread import IMUReaderThread
from .imu_writer_thread import IMUWriterThread
from .data_type import IMUData, WriterConfig


class IMURecorder(QObject):
    """IMU录制协调器"""
    
    # 信号定义 - 转发来自子线程的信号
    device_discovered = pyqtSignal(object)      # 设备发现信号
    device_connected = pyqtSignal(str)        # 设备连接信号
    device_disconnected = pyqtSignal(str)     # 设备断开信号
    data_received = pyqtSignal(str, dict)     # 数据接收信号
    recording_started = pyqtSignal(str)       # 录制开始信号
    recording_stopped = pyqtSignal(str, dict) # 录制停止信号
    error_occurred = pyqtSignal(str, str)     # 错误信号
    scan_finished = pyqtSignal()              # 扫描完成信号
    
    def __init__(self):
        """
        初始化IMU录制协调器
        """
        super().__init__()
        
        self.logger = get_logger("imu_recorder")
        
        # 创建生产者线程（IMU数据采集）
        self.imu_reader_thread = IMUReaderThread()
        
        # 创建消费者线程（数据写入）
        self.imu_writer_thread = IMUWriterThread()
        
        # 录制状态管理
        self.recording_devices: Dict[str, WriterConfig] = {}
        self.data_counters: Dict[str, int] = {}  # 每个设备的数据计数器
        
        # 设置信号连接
        self._setup_signals()
        
        self.logger.info("IMU录制协调器初始化完成")
    
    def _setup_signals(self):
        """设置信号连接"""
        # 转发IMU线程的信号
        self.imu_reader_thread.device_discovered.connect(self.device_discovered.emit)
        self.imu_reader_thread.device_connected.connect(self.device_connected.emit)
        self.imu_reader_thread.device_disconnected.connect(self.device_disconnected.emit)
        self.imu_reader_thread.data_received.connect(self._on_data_received)
        self.imu_reader_thread.error_occurred.connect(self.error_occurred.emit)
        self.imu_reader_thread.scan_finished.connect(self.scan_finished.emit)
        
        # 转发写入线程的信号
        self.imu_writer_thread.writer_started.connect(self.recording_started.emit)
        self.imu_writer_thread.writer_stopped.connect(self.recording_stopped.emit)
        self.imu_writer_thread.writer_error.connect(self.error_occurred.emit)
    
    def _on_data_received(self, device_address: str, data: dict):
        """
        处理接收到的数据
        
        Args:
            device_address (str): 设备地址
            data (dict): 数据
        """
        # 转发数据接收信号
        self.data_received.emit(device_address, data)
        
        # 如果设备正在录制，将数据发送到写入线程
        if device_address in self.recording_devices:
            # 更新数据计数器
            if device_address not in self.data_counters:
                self.data_counters[device_address] = 0
            self.data_counters[device_address] += 1
            
            # 创建IMU数据对象
            imu_data = IMUData(
                device_address=device_address,
                timestamp=time_manager.get_timestamp_ms(),  # 始终使用系统时间戳
                data=data,
                data_count=self.data_counters[device_address]
            )
            
            # 发送到写入线程
            if not self.imu_writer_thread.add_data(imu_data):
                self.logger.warning(f"无法添加数据到写入队列 - 设备 {device_address}")
    
    def start(self):
        """启动协调器"""
        self.logger.info("启动IMU录制协调器")
        
        # 启动写入线程
        if not self.imu_writer_thread.isRunning():
            self.imu_writer_thread.start()
        
        # 启动IMU线程
        if not self.imu_reader_thread.isRunning():
            self.imu_reader_thread.start()
    
    def stop(self):
        """停止协调器"""
        self.logger.info("停止IMU录制协调器")
        
        # 停止所有录制
        for device_address in list(self.recording_devices.keys()):
            self.stop_recording(device_address)
        
        # 停止线程
        self.imu_reader_thread.stop_thread()
        self.imu_writer_thread.stop_thread()
    
    def cleanup(self):
        """清理资源"""
        self.logger.info("清理IMU录制协调器资源")
        
        # 停止协调器
        self.stop()
        
        # 清理线程
        self.imu_reader_thread.cleanup()
        self.imu_writer_thread.cleanup()
    
    # 设备管理方法
    def start_scan(self, duration: float = 10.0, name_filter: Optional[List[str]] = None):
        """
        开始扫描设备
        
        Args:
            duration (float): 扫描持续时间
            name_filter (Optional[List[str]]): 设备名称过滤列表
        """
        self.imu_reader_thread.start_scan(duration, name_filter)
    
    def connect_device(self, device_address: str):
        """
        连接设备
        
        Args:
            device_address (str): 设备地址
        """
        self.imu_reader_thread.connect_device(device_address)
    
    def disconnect_device(self, device_address: str):
        """
        断开设备
        
        Args:
            device_address (str): 设备地址
        """
        # 如果正在录制，先停止录制
        if device_address in self.recording_devices:
            self.stop_recording(device_address)
        
        self.imu_reader_thread.disconnect_device(device_address)
    
    def disconnect_all_devices(self):
        """断开所有设备"""
        # 停止所有录制
        for device_address in list(self.recording_devices.keys()):
            self.stop_recording(device_address)
        
        self.imu_reader_thread.disconnect_all_devices()
    
    # 录制管理方法
    def start_recording(self, device_address: str, output_path: Path) -> bool:
        """
        开始录制
        
        Args:
            device_address (str): 设备地址
            output_path (Path): 输出文件路径
            
        Returns:
            bool: 是否成功开始录制
        """
        # 检查设备是否连接
        device_info = self.imu_reader_thread.get_device_info(device_address)
        if not device_info:
            self.logger.error(f"设备 {device_address} 未连接")
            return False
        
        # 检查是否已经在录制
        if device_address in self.recording_devices:
            self.logger.warning(f"设备 {device_address} 已经在录制中")
            return False
        
        # 创建写入器配置
        config = WriterConfig(
            device_address=device_address,
            output_path=output_path
        )
        
        # 启动写入器
        if self.imu_writer_thread.start_writer(config):
            self.recording_devices[device_address] = config
            self.data_counters[device_address] = 0
            self.logger.info(f"开始录制设备 {device_address}: {output_path}")
            return True
        else:
            self.logger.error(f"启动录制失败 - 设备 {device_address}")
            return False
    
    def stop_recording(self, device_address: str) -> bool:
        """
        停止录制
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            bool: 是否成功停止录制
        """
        if device_address not in self.recording_devices:
            self.logger.warning(f"设备 {device_address} 没有在录制中")
            return False
        
        # 停止写入器
        if self.imu_writer_thread.stop_writer(device_address):
            del self.recording_devices[device_address]
            if device_address in self.data_counters:
                del self.data_counters[device_address]
            self.logger.info(f"停止录制设备 {device_address}")
            return True
        else:
            self.logger.error(f"停止录制失败 - 设备 {device_address}")
            return False
    
    def is_recording(self, device_address: str) -> bool:
        """
        检查是否正在录制
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            bool: 是否正在录制
        """
        return device_address in self.recording_devices
    
    # 信息查询方法
    def get_connected_devices(self) -> List[dict]:
        """
        获取已连接设备列表
        
        Returns:
            List[dict]: 设备信息列表
        """
        return self.imu_reader_thread.get_connected_devices()
    
    def get_device_info(self, device_address: str) -> Optional[dict]:
        """
        获取设备信息
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            Optional[dict]: 设备信息
        """
        return self.imu_reader_thread.get_device_info(device_address)
    
    def get_latest_data(self, device_address: str) -> Optional[dict]:
        """
        获取设备最新数据
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            Optional[dict]: 最新数据
        """
        return self.imu_reader_thread.get_latest_data(device_address)
    
    def get_all_data(self, device_address: str) -> List[dict]:
        """
        获取设备所有数据
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            List[dict]: 所有数据
        """
        return self.imu_reader_thread.get_all_data(device_address)
    
    def get_recording_stats(self, device_address: str) -> Optional[dict]:
        """
        获取录制统计信息
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            Optional[dict]: 录制统计信息
        """
        return self.imu_writer_thread.get_writer_stats(device_address)
    
    def get_queue_size(self) -> int:
        """
        获取写入队列大小
        
        Returns:
            int: 当前队列大小
        """
        return self.imu_writer_thread.get_queue_size()
    
    def clear_device_data(self, device_address: str):
        """
        清除设备数据缓冲区
        
        Args:
            device_address (str): 设备地址
        """
        self.imu_reader_thread.clear_data(device_address)
    
    def clear_all_data(self):
        """清除所有设备数据缓冲区"""
        self.imu_reader_thread.clear_data()