"""
摄像头数据采集线程

在独立线程中运行摄像头管理器，处理视频帧采集和录制。
"""

import threading
from queue import Queue, Empty
from typing import Optional, Dict, List, Callable

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from utils.logger import get_logger
from utils.time_utils import time_manager
from utils.config_manager import get_config_manager
from .camera_manager import CameraManager, CameraDevice


class CameraFrameBuffer:
    """摄像头帧缓冲区"""
    
    def __init__(self, max_size: int = 10):
        """
        初始化帧缓冲区
        
        Args:
            max_size (int): 最大缓冲区大小
        """
        self.max_size = max_size
        self.buffer: Dict[int, List[dict]] = {}
        self.lock = threading.Lock()
    
    def add_frame(self, camera_id: int, frame: np.ndarray, timestamp: int) -> None:
        """
        添加帧到缓冲区
        
        Args:
            camera_id (int): 摄像头ID
            frame (np.ndarray): 视频帧
            timestamp (int): 时间戳
        """
        with self.lock:
            if camera_id not in self.buffer:
                self.buffer[camera_id] = []
            
            frame_data = {
                'frame': frame.copy(),
                'timestamp': timestamp,
                'camera_id': camera_id
            }
            
            self.buffer[camera_id].append(frame_data)
            
            # 限制缓冲区大小
            if len(self.buffer[camera_id]) > self.max_size:
                self.buffer[camera_id].pop(0)
    
    def get_latest_frame(self, camera_id: int) -> Optional[dict]:
        """
        获取最新帧
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 最新帧数据
        """
        with self.lock:
            if camera_id not in self.buffer or not self.buffer[camera_id]:
                return None
            
            return self.buffer[camera_id][-1]
    
    def clear_buffer(self, camera_id: Optional[int] = None) -> None:
        """
        清除缓冲区
        
        Args:
            camera_id (Optional[int]): 摄像头ID，如果为None则清除所有
        """
        with self.lock:
            if camera_id is None:
                self.buffer.clear()
            elif camera_id in self.buffer:
                self.buffer[camera_id].clear()


class CameraReaderThread(QThread):
    """摄像头数据采集线程 - 生产者线程"""
    
    # 信号定义
    camera_discovered = pyqtSignal(dict)      # 摄像头发现信号
    camera_connected = pyqtSignal(int)        # 摄像头连接信号
    camera_disconnected = pyqtSignal(int)     # 摄像头断开信号
    frame_received = pyqtSignal(int, object)  # 帧接收信号
    error_occurred = pyqtSignal(int, str)     # 错误信号
    
    def __init__(self):
        """
        初始化摄像头线程
        """
        super().__init__()
        
        self.logger = get_logger("camera_thread")
        
        # 配置管理器
        self.config_manager = get_config_manager()
        
        # 从配置加载参数
        connection_settings = self.config_manager.get_camera_connection_settings()
        self.buffer_size = connection_settings.get('buffer_size', 10)
        
        # 摄像头管理器和帧缓冲区
        self.camera_manager: Optional[CameraManager] = None
        self.frame_buffer = CameraFrameBuffer(self.buffer_size)
        
        # 帧处理回调（用于发送帧到视频写入线程）
        self.frame_callback: Optional[Callable[[int, np.ndarray, int], None]] = None
        self.frame_counter: Dict[int, int] = {}  # 每个摄像头的帧计数器
        
        # 命令队列
        self.command_queue = Queue()
        
        # 运行状态
        self.is_running = False
        self.capture_active = False
        
        self.logger.info("摄像头线程初始化完成")
    
    def run(self) -> None:
        """线程主函数"""
        self.logger.info("摄像头线程开始运行")
        
        self.is_running = True
        
        try:
            # 加载摄像头配置
            connection_settings = self.config_manager.get_camera_connection_settings()
            device_names = self.config_manager.get('camera.device_names', {})
            default_resolution = connection_settings.get('default_resolution', {})
            
            # 初始化摄像头管理器
            self.camera_manager = CameraManager(
                max_cameras=connection_settings.get('max_devices', 3),
                device_names=device_names,
                default_fps=connection_settings.get('default_fps', 30.0),
                default_width=default_resolution.get('width', 1920),
                default_height=default_resolution.get('height', 1080)
            )
            
            self._setup_callbacks()

            while self.is_running:
                # 处理命令队列
                self._process_commands()
                
                # 如果激活了采集，捕获所有摄像头的帧
                if self.capture_active:
                    self._capture_frames()
                    # 短暂休眠，避免CPU空转100%，同时足够灵敏以捕获高帧率
                    self.msleep(5)
                else:
                    # 未激活采集时，可以更长时间休眠
                    self.msleep(20)
        
        except Exception as e:
            self.logger.error(f"摄像头线程运行时发生错误: {e}")
            self.error_occurred.emit(-1, str(e))
        
        finally:
            self.logger.info("摄像头线程结束运行")
            
    def _setup_callbacks(self) -> None:
        """设置回调函数"""
        if self.camera_manager:
            self.camera_manager.on_camera_discovered = self._on_camera_discovered
            self.camera_manager.on_camera_connected = self._on_camera_connected
            self.camera_manager.on_camera_disconnected = self._on_camera_disconnected
            self.camera_manager.on_frame_received = self._on_frame_received
            self.camera_manager.on_error = self._on_error
    
    def _on_camera_discovered(self, camera: CameraDevice) -> None:
        """摄像头发现回调"""
        camera_info = {
            'id': camera.id,
            'name': camera.name,
            'display_name': camera.display_name,
            'width': camera.width,
            'height': camera.height,
            'fps': camera.fps,
            'state': camera.state.value
        }
        self.camera_discovered.emit(camera_info)
    
    def _on_camera_connected(self, camera_id: int) -> None:
        """摄像头连接回调"""
        self.camera_connected.emit(camera_id)
    
    def _on_camera_disconnected(self, camera_id: int) -> None:
        """摄像头断开回调"""
        self.camera_disconnected.emit(camera_id)
    
    def _on_frame_received(self, camera_id: int, frame: np.ndarray) -> None:
        """帧接收回调"""
        timestamp = time_manager.get_timestamp_ms()
        
        # 添加到缓冲区
        self.frame_buffer.add_frame(camera_id, frame, timestamp)
        
        # 更新帧计数器
        if camera_id not in self.frame_counter:
            self.frame_counter[camera_id] = 0
        self.frame_counter[camera_id] += 1
        
        # 如果设置了帧处理回调，调用它（用于发送帧到视频写入线程）
        if self.frame_callback:
            self.frame_callback(camera_id, frame, timestamp)
        
        # 发送信号
        self.frame_received.emit(camera_id, frame)
    
    def _on_error(self, camera_id: int, error: str) -> None:
        """错误回调"""
        self.error_occurred.emit(camera_id, error)
    
    def _process_commands(self) -> None:
        """处理命令队列"""
        if not self.camera_manager:
            self.logger.warning("摄像头管理器尚未初始化，无法处理命令。")
            return

        try:
            while True:
                command = self.command_queue.get_nowait()
                self._execute_command(command)
        
        except Empty:
            pass
    
    def _execute_command(self, command: dict) -> None:
        """
        执行命令
        
        Args:
            command (dict): 命令字典
        """
        if not self.camera_manager:
            self.logger.warning("摄像头管理器尚未初始化，无法执行命令。")
            return
        cmd_type = command.get('type')
        if cmd_type == 'scan':
            self.camera_manager.scan_cameras()
        elif cmd_type == 'connect':
            self.camera_manager.connect_camera(
                command['id'],
                command.get('width'),
                command.get('height'),
                command.get('fps')
            )
        elif cmd_type == 'disconnect':
            self.camera_manager.disconnect_camera(command['camera_id'])
        elif cmd_type == 'start_capture':
            self.capture_active = True
            self.logger.info("开始帧捕获")
        elif cmd_type == 'stop_capture':
            self.capture_active = False
            self.logger.info("停止帧捕获")
        elif cmd_type == 'set_resolution':
            camera_id = command.get('camera_id')
            width = command.get('width')
            height = command.get('height')
            if camera_id is not None and width and height:
                self.camera_manager.set_camera_resolution(camera_id, width, height)
        elif cmd_type == 'set_fps':
            camera_id = command.get('camera_id')
            fps = command.get('fps')
            if camera_id is not None and fps:
                self.camera_manager.set_camera_fps(camera_id, fps)
        elif cmd_type == 'stop':
            self.is_running = False
        else:
            self.logger.warning(f"未知命令类型: {cmd_type}")
    
    def _capture_frames(self) -> None:
        """捕获所有摄像头的帧"""
        if not self.camera_manager:
            return
            
        connected_cameras = self.camera_manager.get_connected_cameras()
        
        # 捕获所有连接的摄像头帧
        for camera in connected_cameras:
            try:
                # 捕获帧
                self.camera_manager.capture_frame(camera.id)
            except Exception as e:
                self.logger.error(f"捕获摄像头 {camera.display_name} 帧时发生错误: {e}")
    
    # 公共接口方法
    def scan_cameras(self) -> None:
        """扫描摄像头"""
        self.command_queue.put({'type': 'scan'})
    
    def connect_camera(self, camera_id: int,
                      width: Optional[int] = None, height: Optional[int] = None,
                      fps: Optional[float] = None) -> None:
        """
        连接摄像头
        
        Args:
            camera_id (int): 摄像头ID
            width (Optional[int]): 宽度
            height (Optional[int]): 高度
            fps (Optional[float]): 帧率
        """
        self.command_queue.put({
            'type': 'connect',
            'id': camera_id,
            'width': width,
            'height': height,
            'fps': fps
        })
    
    def disconnect_camera(self, camera_id: int) -> None:
        """
        断开摄像头连接
        
        Args:
            camera_id (int): 摄像头ID
        """
        command = {
            'type': 'disconnect',
            'camera_id': camera_id
        }
        self.command_queue.put(command)
    
    def start_capture(self) -> None:
        """开始采集"""
        command = {'type': 'start_capture'}
        self.command_queue.put(command)
    
    def stop_capture(self) -> None:
        """停止采集"""
        command = {'type': 'stop_capture'}
        self.command_queue.put(command)
    

    
    def set_camera_resolution(self, camera_id: int, width: int, height: int) -> None:
        """
        设置摄像头分辨率
        
        Args:
            camera_id (int): 摄像头ID
            width (int): 宽度
            height (int): 高度
        """
        command = {
            'type': 'set_resolution',
            'camera_id': camera_id,
            'width': width,
            'height': height
        }
        self.command_queue.put(command)
    
    def set_camera_fps(self, camera_id: int, fps: float) -> None:
        """
        设置摄像头帧率
        
        Args:
            camera_id (int): 摄像头ID
            fps (float): 帧率
        """
        command = {
            'type': 'set_fps',
            'camera_id': camera_id,
            'fps': fps
        }
        self.command_queue.put(command)
    
    def stop_thread(self) -> None:
        """停止线程"""
        command = {'type': 'stop'}
        self.command_queue.put(command)
    
    def get_latest_frame(self, camera_id: int) -> Optional[dict]:
        """
        获取最新帧
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 最新帧数据
        """
        return self.frame_buffer.get_latest_frame(camera_id)
    
    def get_connected_cameras(self) -> List[dict]:
        """
        获取已连接摄像头列表
        
        Returns:
            List[dict]: 摄像头信息列表
        """
        if not self.camera_manager:
            return []
            
        cameras = []
        for camera in self.camera_manager.get_connected_cameras():
            cameras.append({
                'id': camera.id,
                'name': camera.name,
                'display_name': camera.display_name,
                'width': camera.width,
                'height': camera.height,
                'fps': camera.fps,
                'state': camera.state.value,
                'last_frame_time': getattr(camera, 'last_frame_time', 0)
            })
        
        return cameras
    
    def get_camera_info(self, camera_id: int) -> Optional[dict]:
        """
        获取摄像头信息
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 摄像头信息
        """
        if not self.camera_manager:
            return None
        return self.camera_manager.get_camera_info(camera_id)
    
    def set_frame_callback(self, callback: Optional[Callable[[int, np.ndarray, int], None]]) -> None:
        """
        设置帧处理回调函数
        
        Args:
            callback: 帧处理回调函数，参数为 (camera_id, frame, timestamp)
        """
        self.frame_callback = callback
    
    def cleanup(self) -> None:
        """清理资源"""
        self.logger.info("正在清理摄像头线程资源...")
        
        # 停止线程
        self.stop_thread()
        
        # 等待线程结束
        if self.isRunning(): # PyQt方法，不是 self.is_running
            self.wait(5000)  # 最多等待5秒
        
        # 清理帧计数器
        self.frame_counter.clear()
        
        # 清理摄像头管理器
        if self.camera_manager:
            self.camera_manager.cleanup()
        
        # 清理帧缓冲区
        self.frame_buffer.clear_buffer()
        
        self.logger.info("摄像头线程资源清理完成")
    
    def get_all_cameras(self) -> List[Dict]:
        """
        获取所有已发现的摄像头设备信息列表
        
        Returns:
            List[Dict]: 包含所有摄像头信息的字典列表
        """
        if not self.camera_manager:
            return []
        devices = self.camera_manager.get_all_cameras()
        return [
            {
                'id': dev.id,
                'name': dev.name,
                'display_name': dev.display_name,
                'width': dev.width,
                'height': dev.height,
                'fps': dev.fps,
                'state': dev.state.value,
            } for dev in devices
        ] 