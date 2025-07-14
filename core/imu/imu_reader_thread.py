"""
IMU数据采集线程

在独立线程中运行IMU管理器，处理异步蓝牙通信。
"""

import asyncio
import threading
from queue import Queue, Empty
from typing import Optional, Dict, List

from PyQt5.QtCore import QThread, pyqtSignal

from utils.logger import get_logger
from utils.config_manager import get_config_manager
from .imu_manager import IMUManager
from .data_type import IMUDevice


class IMUDataBuffer:
    """IMU数据缓冲区"""
    
    def __init__(self, max_size: int = 200):
        """
        初始化数据缓冲区
        
        Args:
            max_size (int): 最大缓冲区大小
        """
        self.max_size = max_size
        self.buffer: Dict[str, List[dict]] = {}
        self.lock = threading.Lock()
    
    def add_data(self, device_address: str, data: dict) -> None:
        """
        添加数据到缓冲区
        
        Args:
            device_address (str): 设备地址
            data (dict): 数据字典
        """
        with self.lock:
            if device_address not in self.buffer:
                self.buffer[device_address] = []
            
            self.buffer[device_address].append(data)
            
            # 限制缓冲区大小
            if len(self.buffer[device_address]) > self.max_size:
                self.buffer[device_address].pop(0)
    
    def get_latest_data(self, device_address: str) -> Optional[dict]:
        """
        获取最新数据
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            Optional[dict]: 最新数据
        """
        with self.lock:
            if device_address not in self.buffer or not self.buffer[device_address]:
                return None
            
            return self.buffer[device_address][-1]
    
    def get_all_data(self, device_address: str) -> List[dict]:
        """
        获取所有数据
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            List[dict]: 所有数据
        """
        with self.lock:
            if device_address not in self.buffer:
                return []
            
            return self.buffer[device_address].copy()
    
    def clear_data(self, device_address: Optional[str] = None) -> None:
        """
        清除数据
        
        Args:
            device_address (Optional[str]): 设备地址，如果为None则清除所有数据
        """
        with self.lock:
            if device_address is None:
                self.buffer.clear()
            elif device_address in self.buffer:
                self.buffer[device_address].clear()


class IMUReaderThread(QThread):
    """IMU数据采集线程"""
    
    # 信号定义
    device_discovered = pyqtSignal(object)      # 设备发现信号
    device_connected = pyqtSignal(str)        # 设备连接信号
    device_disconnected = pyqtSignal(str)     # 设备断开信号
    data_received = pyqtSignal(str, dict)     # 数据接收信号
    error_occurred = pyqtSignal(str, str)     # 错误信号
    scan_finished = pyqtSignal()              # 扫描完成信号
    
    def __init__(self):
        """
        初始化IMU线程
        """
        super().__init__()
        
        self.logger = get_logger("imu_thread")
        
        # 配置管理器
        self.config_manager = get_config_manager()
        
        # 从配置加载参数
        connection_settings = self.config_manager.get_imu_connection_settings()
        self.buffer_size = connection_settings.get('buffer_size', 200)
        
        # IMU管理器和数据缓冲区
        self.imu_manager: Optional[IMUManager] = None
        self.data_buffer = IMUDataBuffer(self.buffer_size)
        
        # 事件循环
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        
        # 命令队列
        self.command_queue = Queue()
        
        # 运行状态
        self.is_running = False
        
        self.logger.info("IMU线程初始化完成")
    
    def run(self) -> None:
        """线程主函数"""
        self.logger.info("IMU线程开始运行")
        
        # 创建新的事件循环
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            # 加载IMU配置
            connection_settings = self.config_manager.get_imu_connection_settings()
            max_devices = connection_settings.get('max_devices', 3)
            reconnect_attempts = connection_settings.get('reconnect_attempts', 5)
            reconnect_delay = connection_settings.get('reconnect_delay', 5.0)
            device_names = self.config_manager.get('imu.device_names', {})
            
            # 初始化IMU管理器
            self.imu_manager = IMUManager(
                max_devices=max_devices,
                reconnect_attempts=reconnect_attempts,
                reconnect_delay=reconnect_delay,
                device_custom_names=device_names
            )
            
            self._setup_callbacks()
            
            self.is_running = True
            
            # 运行事件循环
            self.loop.run_until_complete(self._main_loop())
        
        except Exception as e:
            self.logger.error(f"IMU线程运行时发生错误: {e}")
            self.error_occurred.emit("thread", str(e))
        
        finally:
            self.logger.info("IMU线程结束运行")
    
    def _setup_callbacks(self) -> None:
        """设置回调函数"""
        if not self.imu_manager:
            return
        
        self.imu_manager.on_device_discovered = self._on_device_discovered
        self.imu_manager.on_device_connected = self._on_device_connected
        self.imu_manager.on_device_disconnected = self._on_device_disconnected
        self.imu_manager.on_data_received = self._on_data_received
        self.imu_manager.on_error = self._on_error
    
    def _on_device_discovered(self, device: IMUDevice) -> None:
        """设备发现回调"""
        self.device_discovered.emit(device)
    
    def _on_device_connected(self, address: str) -> None:
        """设备连接回调"""
        self.device_connected.emit(address)
    
    def _on_device_disconnected(self, address: str) -> None:
        """设备断开回调"""
        self.device_disconnected.emit(address)
    
    def _on_data_received(self, address: str, data: dict) -> None:
        """数据接收回调"""
        # 添加到缓冲区
        self.data_buffer.add_data(address, data)
        
        # 发送信号
        self.data_received.emit(address, data)
    
    def _on_error(self, context: str, error: str) -> None:
        """错误回调"""
        self.error_occurred.emit(context, error)
    
    async def _main_loop(self) -> None:
        """主事件循环"""
        while self.is_running:
            try:
                # 处理命令队列
                await self._process_commands()
                
                # 短暂等待
                await asyncio.sleep(0.1)
            
            except Exception as e:
                self.logger.error(f"主循环发生错误: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_commands(self) -> None:
        """处理命令队列"""
        try:
            while True:
                command = self.command_queue.get_nowait()
                await self._execute_command(command)
        
        except Empty:
            pass
    
    async def _execute_command(self, command: dict) -> None:
        """
        执行命令
        
        Args:
            command (dict): 命令字典
        """
        if not self.imu_manager:
            return
        
        try:
            cmd_type = command.get('type')
            
            if cmd_type == 'scan':
                duration = command.get('duration', 10.0)
                name_filter = command.get('name_filter')
                await self.imu_manager.start_scan(duration, name_filter=name_filter)
                self.scan_finished.emit()
            
            elif cmd_type == 'connect':
                address = command.get('address')
                if address:
                    await self.imu_manager.connect_device(address)
            
            elif cmd_type == 'disconnect':
                address = command.get('address')
                if address:
                    await self.imu_manager.disconnect_device(address)
            
            elif cmd_type == 'disconnect_all':
                for device in self.imu_manager.get_connected_devices():
                    await self.imu_manager.disconnect_device(device.address)
            
            elif cmd_type == 'stop':
                self.is_running = False
        
        except Exception as e:
            self.logger.error(f"执行命令 {cmd_type} 时发生错误: {e}")
            self.error_occurred.emit(cmd_type, str(e))
    
    def start_scan(self, duration: float = 10.0, name_filter: Optional[List[str]] = None) -> None:
        """
        开始扫描设备
        
        Args:
            duration (float): 扫描持续时间
            name_filter (Optional[List[str]]): 设备名称过滤列表
        """
        command = {
            'type': 'scan',
            'duration': duration,
            'name_filter': name_filter
        }
        self.command_queue.put(command)
    
    def connect_device(self, address: str) -> None:
        """
        连接设备
        
        Args:
            address (str): 设备地址
        """
        command = {
            'type': 'connect',
            'address': address,
        }
        self.command_queue.put(command)
    
    def disconnect_device(self, address: str) -> None:
        """
        断开设备连接
        
        Args:
            address (str): 设备地址
        """
        command = {
            'type': 'disconnect',
            'address': address
        }
        self.command_queue.put(command)
    
    def disconnect_all_devices(self) -> None:
        """断开所有设备连接"""
        command = {
            'type': 'disconnect_all'
        }
        self.command_queue.put(command)
    
    def stop_thread(self) -> None:
        """停止线程"""
        command = {
            'type': 'stop'
        }
        self.command_queue.put(command)
    
    def get_connected_devices(self) -> List[dict]:
        """
        获取已连接设备列表
        
        Returns:
            List[dict]: 设备信息列表
        """
        if not self.imu_manager:
            return []
        
        devices = []
        for device in self.imu_manager.get_connected_devices():
            devices.append({
                'address': device.address,
                'name': device.name,
                'custom_name': device.custom_name,
                'display_name': device.display_name,
                'state': device.state.value,
                'rssi': device.rssi,
                'last_data_time': device.last_data_time
            })
        
        return devices
    
    def get_device_info(self, address: str) -> Optional[dict]:
        """
        获取设备信息
        
        Args:
            address (str): 设备地址
            
        Returns:
            Optional[dict]: 设备信息
        """
        if not self.imu_manager:
            return None
        
        return self.imu_manager.get_device_info(address)
    
    def get_latest_data(self, address: str) -> Optional[dict]:
        """
        获取设备最新数据
        
        Args:
            address (str): 设备地址
            
        Returns:
            Optional[dict]: 最新数据
        """
        return self.data_buffer.get_latest_data(address)
    
    def get_all_data(self, address: str) -> List[dict]:
        """
        获取设备所有数据
        
        Args:
            address (str): 设备地址
            
        Returns:
            List[dict]: 所有数据
        """
        return self.data_buffer.get_all_data(address)
    
    def clear_data(self, address: Optional[str] = None) -> None:
        """
        清除数据缓冲区
        
        Args:
            address (Optional[str]): 设备地址，如果为None则清除所有数据
        """
        self.data_buffer.clear_data(address)
    
    def cleanup(self) -> None:
        """清理资源"""
        self.logger.info("正在清理IMU线程资源...")
        
        # 停止线程
        self.stop_thread()
        
        # 等待线程结束
        if self.isRunning():
            self.wait(5000)  # 最多等待5秒
        
        # 确保事件循环已停止
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        # 清理数据缓冲区
        self.data_buffer.clear_data()
        
        self.logger.info("IMU线程资源清理完成") 