"""
IMU设备管理器

负责蓝牙IMU设备的扫描、连接、重连和管理。
支持同时管理多个IMU设备。
"""

import asyncio
from typing import Dict, List, Optional, Callable
from datetime import datetime
from bleak import BleakClient, BleakScanner
from utils.logger import get_logger
from utils.time_utils import time_manager
from .imu_protocol import IMUProtocol
from .data_type import IMUDevice, IMUConnectionState


class IMUManager:
    """IMU设备管理器"""
    
    def __init__(self, max_devices: int, reconnect_attempts: int, reconnect_delay: float, device_custom_names: Dict[str, str]):
        """
        初始化IMU管理器
        
        Args:
            max_devices (int): 最大支持的设备数量
            reconnect_attempts (int): 重连尝试次数
            reconnect_delay (float): 重连延迟时间（秒）
            device_custom_names (Dict[str, str]): 设备自定义名称映射
        """
        self.max_devices = max_devices
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.device_custom_names = device_custom_names.copy()
        
        self.devices: Dict[str, IMUDevice] = {}
        self.logger = get_logger("imu_manager")
        
        # 创建协议处理器
        self.protocol = IMUProtocol()
        
        # 回调函数
        self.on_device_discovered: Optional[Callable[[IMUDevice], None]] = None
        self.on_device_connected: Optional[Callable[[str], None]] = None
        self.on_device_disconnected: Optional[Callable[[str], None]] = None
        self.on_data_received: Optional[Callable[[str, dict], None]] = None
        self.on_error: Optional[Callable[[str, str], None]] = None
        
        # 扫描状态
        self.is_scanning = False
        self.scan_task: Optional[asyncio.Task] = None
        
        # 连接管理
        self.connection_tasks: Dict[str, asyncio.Task] = {}
        self.reconnect_tasks: Dict[str, asyncio.Task] = {}
        
        self.logger.info(f"IMU管理器初始化完成，最大设备数: {max_devices}")
    
    async def start_scan(self, duration: float, name_filter: Optional[List[str]] = None) -> None:
        """
        开始扫描IMU设备
        
        Args:
            duration (float): 扫描持续时间（秒）
            name_filter (Optional[List[str]]): 设备名称过滤列表，只保留名称中包含这些关键词的设备
        """
        if self.is_scanning:
            self.logger.warning("正在扫描中，忽略重复扫描请求")
            return
        
        self.is_scanning = True
        self.logger.info(f"开始扫描IMU设备，持续时间: {duration}秒")
        
        # 清空设备列表
        self.devices.clear()

        try:
            # 扫描设备
            devices = await BleakScanner.discover(timeout=duration)
            for device in devices:
                # 应用名称过滤器
                if name_filter:
                    device_name = (device.name or "").lower()
                    if not any(keyword.lower() in device_name for keyword in name_filter):
                        continue
                
                # 安全获取RSSI
                rssi = getattr(device, 'rssi', None)
                
                # 获取自定义名称
                custom_name = self.device_custom_names.get(device.address, None)
                
                imu_device = IMUDevice(
                    address=device.address,
                    name=device.name or "Unknown",
                    rssi=rssi,
                    custom_name=custom_name
                )
                
                # 添加到设备列表
                if device.address not in self.devices:
                    self.devices[device.address] = imu_device
                    self.logger.info(f"发现蓝牙设备: {imu_device.display_name} ({device.address})")
                    
                    # 通知设备发现
                    if self.on_device_discovered:
                        self.on_device_discovered(imu_device)
                else:
                    # 更新RSSI
                    self.devices[device.address].rssi = rssi
        
        except Exception as e:
            self.logger.error(f"扫描设备时发生错误: {e}")
            if self.on_error:
                self.on_error("scan", str(e))
        
        finally:
            self.is_scanning = False
            self.logger.info("扫描完成")
    
    async def connect_device(self, address: str) -> bool:
        """
        连接IMU设备
        
        Args:
            address (str): 设备MAC地址
            
        Returns:
            bool: 连接是否成功
        """
        # 检查设备是否在设备列表中
        if address not in self.devices:
            self.logger.error(f"设备 {address} 不在设备列表中")
            return False
        
        # 获取设备
        device = self.devices[address]
        
        """ 1. 前置检查 """
        # 检查设备是否已经连接
        if device.state == IMUConnectionState.CONNECTED:
            self.logger.warning(f"设备 {device.display_name} 已经连接")
            return True
        
        # 检查设备是否正在连接
        if device.state == IMUConnectionState.CONNECTING:
            self.logger.warning(f"设备 {device.display_name} 正在连接中")
            return False
        
        # 检查是否超过最大设备数量
        connected_count = sum(1 for d in self.devices.values() 
                            if d.state == IMUConnectionState.CONNECTED)
        if connected_count >= self.max_devices:
            self.logger.error(f"已达到最大设备连接数量限制: {self.max_devices}")
            return False
        
        """ 2. 清除主动断开标志 """
        # 清除主动断开标志，在意外断开时，可重新连接
        device.manual_disconnect = False
        
        """ 3. 开始连接 """
        device.state = IMUConnectionState.CONNECTING
        device.error_message = None
        
        try:
            """ 4. 创建连接任务 """
            connection_task = asyncio.create_task(
                self._connect_device_task(device)
            )
            self.connection_tasks[address] = connection_task
            
            result = await connection_task
            return result
        
        except Exception as e:
            self.logger.error(f"连接设备 {device.display_name} 时发生错误: {e}")
            device.state = IMUConnectionState.ERROR
            device.error_message = str(e)
            
            if self.on_error:
                self.on_error(address, str(e))
            
            return False
        
        finally:
            # 清理连接任务
            if address in self.connection_tasks:
                del self.connection_tasks[address]
    
    async def _connect_device_task(self, device: IMUDevice) -> bool:
        """
        连接设备的异步任务
        
        Args:
            device (IMUDevice): IMU设备
            
        Returns:
            bool: 连接是否成功
        """
        try:
            self.logger.info(f"正在连接设备: {device.display_name}")
            
            # 创建BLE客户端
            ble_device = await BleakScanner.find_device_by_address(device.address)
            if not ble_device:
                raise Exception(f"无法找到设备 {device.address}")
            
            # 断开连接回调
            def disconnected_callback(client):
                self.logger.warning(f"设备 {device.display_name} 断开连接")
                device.state = IMUConnectionState.DISCONNECTED
                device.client = None
                
                if self.on_device_disconnected:
                    self.on_device_disconnected(device.address)
                
                # 只有在非主动断开时才启动重连任务
                if not device.manual_disconnect and device.address not in self.reconnect_tasks:
                    self.logger.info(f"设备 {device.display_name} 意外断开，启动重连任务")
                    self.reconnect_tasks[device.address] = asyncio.create_task(
                        self._reconnect_device_task(device)
                    )
                elif device.manual_disconnect:
                    self.logger.info(f"设备 {device.display_name} 主动断开，不启动重连")
            
            # 创建客户端并连接
            client = BleakClient(ble_device, disconnected_callback=disconnected_callback)
            await client.connect()
            
            # 设置设备状态
            device.client = client
            device.state = IMUConnectionState.CONNECTED
            device.last_data_time = time_manager.get_timestamp_ms()
            
            # 配置IMU设备
            await self._configure_imu_device(device)
            
            # 启动数据通知
            await client.start_notify(
                self.protocol.NOTIFICATION_CHARACTERISTIC,
                lambda char, data: self._handle_data_notification(device.address, data)
            )
            
            self.logger.info(f"设备 {device.display_name} 连接成功")
            
            if self.on_device_connected:
                self.on_device_connected(device.address)
            
            return True
        
        except Exception as e:
            self.logger.error(f"连接设备 {device.display_name} 失败: {e}")
            device.state = IMUConnectionState.ERROR
            device.error_message = str(e)
            raise
    
    async def _configure_imu_device(self, device: IMUDevice) -> None:
        """
        配置IMU设备
        
        Args:
            device (IMUDevice): IMU设备
        """
        if not device.client:
            return
        
        try:
            # 使用协议处理器创建配置序列
            commands = self.protocol.create_configuration_sequence()
            
            # 逐个发送配置命令
            for i, command in enumerate(commands):
                await device.client.write_gatt_char(self.protocol.WRITE_CHARACTERISTIC, command)
                if i < len(commands) - 1:  # 最后一个命令不需要等待
                    await asyncio.sleep(0.2)
            
            self.logger.info(f"设备 {device.display_name} 配置完成")
        
        except Exception as e:
            self.logger.error(f"配置设备 {device.display_name} 失败: {e}")
            raise
    
    def _handle_data_notification(self, address: str, data: bytearray) -> None:
        """
        处理数据通知
        
        Args:
            address (str): 设备地址
            data (bytearray): 接收到的数据
        """
        if address not in self.devices:
            return
        
        device = self.devices[address]
        device.last_data_time = time_manager.get_timestamp_ms()
        
        try:
            # 使用协议处理器解析IMU数据
            parsed_data = self.protocol.parse_imu_data(data)
            
            if parsed_data and self.on_data_received:
                self.on_data_received(address, parsed_data)
        
        except Exception as e:
            self.logger.error(f"解析设备 {device.display_name} 数据时发生错误: {e}")
    
    async def disconnect_device(self, address: str) -> bool:
        """
        断开设备连接
        
        Args:
            address (str): 设备地址
            
        Returns:
            bool: 断开是否成功
        """
        if address not in self.devices:
            self.logger.error(f"设备 {address} 不在设备列表中")
            return False
        
        device = self.devices[address]
        
        try:
            # 设置主动断开标志
            device.manual_disconnect = True
            
            # 停止重连任务
            if address in self.reconnect_tasks:
                self.reconnect_tasks[address].cancel()
                del self.reconnect_tasks[address]
                self.logger.info(f"已取消设备 {device.display_name} 的重连任务")
            
            # 断开连接
            if device.client and device.client.is_connected:
                await device.client.disconnect()
            
            device.state = IMUConnectionState.DISCONNECTED
            device.client = None
            
            self.logger.info(f"设备 {device.display_name} 主动断开连接")
            return True
        
        except Exception as e:
            self.logger.error(f"断开设备 {device.display_name} 连接时发生错误: {e}")
            return False
    
    async def _reconnect_device_task(self, device: IMUDevice) -> None:
        """
        重连设备任务
        
        Args:
            device (IMUDevice): IMU设备
        """
        max_retries = self.reconnect_attempts
        retry_delay = self.reconnect_delay
        
        for attempt in range(max_retries):
            try:
                # 检查是否被主动断开
                if device.manual_disconnect:
                    self.logger.info(f"设备 {device.display_name} 已被主动断开，停止重连")
                    break
                
                await asyncio.sleep(retry_delay)
                
                self.logger.info(f"尝试重连设备 {device.display_name} (第 {attempt + 1}/{max_retries} 次)")
                
                success = await self.connect_device(device.address)
                if success:
                    self.logger.info(f"设备 {device.display_name} 重连成功")
                    break
                
            except Exception as e:
                self.logger.error(f"重连设备 {device.display_name} 失败: {e}")
        
        else:
            self.logger.error(f"设备 {device.display_name} 重连失败，已达到最大重试次数")
        
        # 清理重连任务
        if device.address in self.reconnect_tasks:
            del self.reconnect_tasks[device.address]
    
    def get_connected_devices(self) -> List[IMUDevice]:
        """
        获取已连接的设备列表
        
        Returns:
            List[IMUDevice]: 已连接的设备列表
        """
        return [device for device in self.devices.values() 
                if device.state == IMUConnectionState.CONNECTED]
    
    def get_all_devices(self) -> List[IMUDevice]:
        """
        获取所有已发现的设备列表
        
        Returns:
            List[IMUDevice]: 所有已发现的设备列表
        """
        return list(self.devices.values())
    
    def get_device_info(self, address: str) -> Optional[dict]:
        """
        获取设备信息
        
        Args:
            address (str): 设备地址
            
        Returns:
            Optional[dict]: 设备信息字典
        """
        if address not in self.devices:
            return None
        
        device = self.devices[address]
        return {
            'address': device.address,
            'name': device.name,
            'custom_name': device.custom_name,
            'display_name': device.display_name,
            'state': device.state.value,
            'rssi': device.rssi,
            'last_data_time': device.last_data_time,
            'error_message': device.error_message,
            'manual_disconnect': device.manual_disconnect
        }
    
    async def cleanup(self) -> None:
        """清理资源"""
        self.logger.info("正在清理IMU管理器资源...")
        
        # 停止扫描
        if self.scan_task:
            self.scan_task.cancel()
        
        # 断开所有设备
        for address in list(self.devices.keys()):
            await self.disconnect_device(address)
        
        # 取消所有任务
        for task in self.connection_tasks.values():
            task.cancel()
        
        for task in self.reconnect_tasks.values():
            task.cancel()
        
        self.logger.info("IMU管理器资源清理完成") 