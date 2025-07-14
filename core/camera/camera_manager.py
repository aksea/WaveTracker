"""
摄像头管理器

负责摄像头设备的扫描、连接、断开和管理。
支持同时管理多个摄像头设备。
"""

import threading
from typing import Dict, List, Optional, Callable, Any

import cv2
import numpy as np

from utils.logger import get_logger
from utils.time_utils import time_manager
from .data_type import CameraDevice, CameraState


class CameraManager:
    """摄像头管理器"""
    
    def __init__(self, max_cameras: int = 3, 
                 device_names: Optional[Dict[int, str]] = None,
                 default_fps: float = 30.0,
                 default_width: int = 1920,
                 default_height: int = 1080):
        """
        初始化摄像头管理器
        
        Args:
            max_cameras (int): 最大支持的摄像头数量
            device_names (Optional[Dict[int, str]]): 摄像头ID到名称的映射
            default_fps (float): 默认帧率
            default_width (int): 默认宽度
            default_height (int): 默认高度
        """
        self.max_cameras = max_cameras
        self.device_names = device_names if device_names is not None else {}
        self.default_fps = default_fps
        self.default_width = default_width
        self.default_height = default_height
        
        self.cameras: Dict[int, CameraDevice] = {}
        self.logger = get_logger("camera_manager")
        
        # 回调函数
        self.on_camera_discovered: Optional[Callable[[CameraDevice], None]] = None
        self.on_camera_connected: Optional[Callable[[int], None]] = None
        self.on_camera_disconnected: Optional[Callable[[int], None]] = None
        self.on_frame_received: Optional[Callable[[int, np.ndarray], None]] = None
        self.on_error: Optional[Callable[[int, str], None]] = None
        
        # 线程锁
        self.lock = threading.Lock()
        
        self.logger.info("摄像头管理器初始化完成")
    
    def scan_cameras(self) -> None:
        """
        扫描可用的摄像头设备，并更新内部设备列表。
        此方法会跳过已连接的设备，并清理无响应的旧设备。
        """
        self.logger.info("开始扫描摄像头设备...")
        found_ids = set()

        # 1. 首先，将所有已连接的设备视为"已找到"，以避免重新检查它们
        with self.lock:
            for cam_id, device in self.cameras.items():
                if device.state in [CameraState.CONNECTED, CameraState.RECORDING]:
                    found_ids.add(cam_id)
                    self.logger.debug(f"跳过已连接的摄像头: {device.display_name} (ID: {cam_id})")

        # 2. 扫描系统，寻找新设备或更新已断开的设备
        for camera_id in range(11):
            if camera_id in found_ids:
                continue

            try:
                cap = cv2.VideoCapture(camera_id)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        found_ids.add(camera_id)
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        camera_name = self._get_camera_name(camera_id)

                        with self.lock:
                            if camera_id not in self.cameras:
                                # 发现全新设备，使用配置中的默认值
                                camera_device = CameraDevice(
                                    id=camera_id, 
                                    name=camera_name,
                                    width=width if width > 0 else self.default_width,
                                    height=height if height > 0 else self.default_height,
                                    fps=fps if fps > 0 else self.default_fps
                                )
                                self.cameras[camera_id] = camera_device
                                self.logger.info(f"发现新摄像头: {camera_device.display_name} (ID: {camera_id})")
                                if self.on_camera_discovered:
                                    self.on_camera_discovered(camera_device)
                            else:
                                # 已存在的设备（之前是断开状态），更新信息
                                device = self.cameras[camera_id]
                                device.name = camera_name
                                device.width = width if width > 0 else self.default_width
                                device.height = height if height > 0 else self.default_height
                                device.fps = fps if fps > 0 else self.default_fps
                                self.logger.info(f"更新已断开的摄像头信息: {device.display_name} (ID: {camera_id})")
                    cap.release()
            except Exception as e:
                self.logger.debug(f"检查摄像头 {camera_id} 时发生错误: {e}")

        # 3. 清理在本次扫描中未被发现的、且处于断开状态的摄像头
        with self.lock:
            all_known_ids = set(self.cameras.keys())
            stale_ids = all_known_ids - found_ids
            
            ids_to_remove = []
            for cam_id in stale_ids:
                if self.cameras[cam_id].state == CameraState.DISCONNECTED:
                    ids_to_remove.append(cam_id)
                    self.logger.info(f"清理未发现的摄像头: {self.cameras[cam_id].display_name} (ID: {cam_id})")

            if ids_to_remove:
                for cam_id in ids_to_remove:
                    del self.cameras[cam_id]

        self.logger.info(f"扫描完成，当前管理器中有 {len(self.cameras)} 个设备记录。")
    
    def _get_camera_name(self, camera_id: int) -> str:
        """
        获取摄像头名称
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            str: 摄像头名称
        """
        return self.device_names.get(camera_id, f"摄像头 {camera_id}")
    
    def connect_camera(self, camera_id: int,
                      width: Optional[int] = None, height: Optional[int] = None,
                      fps: Optional[float] = None) -> bool:
        """
        连接摄像头设备
        
        Args:
            camera_id (int): 摄像头ID
            width (Optional[int]): 视频宽度
            height (Optional[int]): 视频高度
            fps (Optional[float]): 帧率
            
        Returns:
            bool: 连接是否成功
        """
        with self.lock:
            """ 1. 前置检查 """
            # 如果摄像头ID不存在，则为其创建一个临时的设备对象
            if camera_id not in self.cameras:
                self.logger.info(f"摄像头 {camera_id} 未被提前发现，尝试直接连接...")
                camera_device = CameraDevice(
                    id=camera_id,
                    name=self._get_camera_name(camera_id),
                    width=self.default_width,
                    height=self.default_height,
                    fps=self.default_fps
                )
                self.cameras[camera_id] = camera_device
            
            camera = self.cameras[camera_id]
            
            # 检查摄像头是否已经连接
            if camera.state == CameraState.CONNECTED:
                self.logger.debug(f"摄像头 {camera.display_name} 已经连接，跳过重复连接")
                return True
            
            # 检查摄像头是否正在连接
            if camera.state == CameraState.CONNECTING:
                self.logger.warning(f"摄像头 {camera.display_name} 正在连接中")
                return False
            
            # 检查是否超过最大摄像头连接数量限制
            connected_count = sum(1 for c in self.cameras.values() 
                                if c.state in [CameraState.CONNECTED, CameraState.RECORDING])
            if connected_count >= self.max_cameras:
                self.logger.error(f"已达到最大摄像头连接数量限制: {self.max_cameras}")
                return False
            
            """ 2. 设置自定义名称和参数 """
            # 设置摄像头参数，如果没有指定则使用配置中的默认值
            camera.width = width if width is not None else self.default_width
            camera.height = height if height is not None else self.default_height
            camera.fps = fps if fps is not None else self.default_fps
            
            """ 3. 开始连接 """
            camera.state = CameraState.CONNECTING
            camera.error_message = None
            
            try:
                """ 4. 创建VideoCapture对象 """
                capture = cv2.VideoCapture(camera_id)
                
                if not capture.isOpened():
                    raise Exception(f"无法打开摄像头 {camera_id}")
                
                """ 5. 设置摄像头参数 """
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, camera.width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, camera.height)
                capture.set(cv2.CAP_PROP_FPS, camera.fps)
                
                """ 6. 设置缓冲区大小（减少延迟） """
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
                """ 7. 验证设置是否生效 """
                actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = capture.get(cv2.CAP_PROP_FPS)
                
                """ 8. 测试读取一帧 """
                ret, frame = capture.read()
                if not ret or frame is None:
                    raise Exception("无法读取摄像头数据")
                
                """ 9. 更新摄像头信息 """
                camera.capture = capture
                camera.width = actual_width
                camera.height = actual_height
                camera.fps = actual_fps
                camera.state = CameraState.CONNECTED
                camera.frame_timestamps.clear()
                camera.frame_timestamps.append(time_manager.get_timestamp_ms())
                
                self.logger.info(f"摄像头 {camera.display_name} 连接成功 "
                               f"(分辨率: {actual_width}x{actual_height}, FPS: {actual_fps:.1f})")
                
                if self.on_camera_connected:
                    self.on_camera_connected(camera_id)
                
                return True
            
            except Exception as e:
                self.logger.error(f"连接摄像头 {camera.display_name} 失败: {e}")
                camera.state = CameraState.ERROR
                camera.error_message = str(e)
                
                if self.on_error:
                    self.on_error(camera_id, str(e))
                
                return False
    
    def disconnect_camera(self, camera_id: int) -> bool:
        """
        断开摄像头连接
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            bool: 断开是否成功
        """
        with self.lock:
            if camera_id not in self.cameras:
                self.logger.error(f"摄像头 {camera_id} 不在设备列表中")
                return False
            
            camera = self.cameras[camera_id]
            
            try:
                # 释放摄像头资源
                if camera.capture:
                    camera.capture.release()
                    camera.capture = None
                
                camera.state = CameraState.DISCONNECTED
                camera.frame_timestamps.clear()
                
                self.logger.info(f"摄像头 {camera.display_name} 断开连接")
                
                if self.on_camera_disconnected:
                    self.on_camera_disconnected(camera_id)
                
                return True
            
            except Exception as e:
                self.logger.error(f"断开摄像头 {camera.display_name} 连接时发生错误: {e}")
                return False
    
    def capture_frame(self, camera_id: int) -> Optional[Any]:
        """
        捕获摄像头帧。如果读取失败，会自动处理断开连接。
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[Any]: 捕获的帧，如果失败则返回None
        """
        should_disconnect = False
        frame = None

        with self.lock:
            if camera_id not in self.cameras:
                return None
            
            camera = self.cameras[camera_id]
            
            if camera.state != CameraState.CONNECTED or not camera.capture:
                return None
            
            try:
                ret, captured_frame = camera.capture.read()
                
                if ret and captured_frame is not None:
                    camera.frame_timestamps.append(time_manager.get_timestamp_ms())
                    print(camera.measured_fps)
                    frame = captured_frame
                else:
                    self.logger.error(f"摄像头 {camera.display_name} 读取帧失败，设备可能已断开。")
                    should_disconnect = True
            
            except Exception as e:
                self.logger.error(f"捕获摄像头 {camera.display_name} 帧时发生严重错误: {e}")
                should_disconnect = True

        # --- 锁已释放 ---

        if should_disconnect:
            self.disconnect_camera(camera_id)
            return None

        if frame is not None and self.on_frame_received:
            self.on_frame_received(camera_id, frame)
        
        return frame
    
    def get_connected_cameras(self) -> List[CameraDevice]:
        """
        获取已连接的摄像头列表
        
        Returns:
            List[CameraDevice]: 已连接的摄像头列表
        """
        with self.lock:
            return [camera for camera in self.cameras.values() 
                    if camera.state in [CameraState.CONNECTED, CameraState.RECORDING]]
    
    def get_all_cameras(self) -> List[CameraDevice]:
        """
        获取所有已发现的摄像头列表
        
        Returns:
            List[CameraDevice]: 所有已发现的摄像头列表
        """
        with self.lock:
            return list(self.cameras.values())
    
    def get_camera_info(self, camera_id: int) -> Optional[dict]:
        """
        获取摄像头信息
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 摄像头信息字典
        """
        with self.lock:
            if camera_id not in self.cameras:
                return None
            
            camera = self.cameras[camera_id]
            return {
                'id': camera.id,
                'name': camera.name,
                'display_name': camera.display_name,
                'width': camera.width,
                'height': camera.height,
                'fps': camera.fps,
                'resolution': camera.resolution,
                'state': camera.state.value,
                'measured_fps': camera.measured_fps,
                'error_message': camera.error_message
            }
    
    def set_camera_resolution(self, camera_id: int, width: int, height: int) -> bool:
        """
        设置摄像头分辨率
        
        Args:
            camera_id (int): 摄像头ID
            width (int): 宽度
            height (int): 高度
            
        Returns:
            bool: 设置是否成功
        """
        with self.lock:
            if camera_id not in self.cameras:
                return False
            
            camera = self.cameras[camera_id]
            
            if camera.state != CameraState.CONNECTED or not camera.capture:
                return False
            
            try:
                camera.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                camera.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                
                # 验证设置
                actual_width = int(camera.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(camera.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                
                camera.width = actual_width
                camera.height = actual_height
                
                self.logger.info(f"摄像头 {camera.display_name} 分辨率设置为 {actual_width}x{actual_height}")
                return True
            
            except Exception as e:
                self.logger.error(f"设置摄像头 {camera.display_name} 分辨率时发生错误: {e}")
                return False
    
    def set_camera_fps(self, camera_id: int, fps: float) -> bool:
        """
        设置摄像头帧率
        
        Args:
            camera_id (int): 摄像头ID
            fps (float): 帧率
            
        Returns:
            bool: 设置是否成功
        """
        with self.lock:
            if camera_id not in self.cameras:
                return False
            
            camera = self.cameras[camera_id]
            
            if camera.state != CameraState.CONNECTED or not camera.capture:
                return False
            
            try:
                camera.capture.set(cv2.CAP_PROP_FPS, fps)
                
                # 验证设置
                actual_fps = camera.capture.get(cv2.CAP_PROP_FPS)
                camera.fps = actual_fps
                
                self.logger.info(f"摄像头 {camera.display_name} 帧率设置为 {actual_fps:.1f}")
                return True
            
            except Exception as e:
                self.logger.error(f"设置摄像头 {camera.display_name} 帧率时发生错误: {e}")
                return False
    
    def get_camera_properties(self, camera_id: int) -> Optional[dict]:
        """
        获取摄像头属性
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 摄像头属性字典
        """
        with self.lock:
            if camera_id not in self.cameras:
                return None
            
            camera = self.cameras[camera_id]
            
            if camera.state != CameraState.CONNECTED or not camera.capture:
                return None
            
            try:
                properties = {
                    'width': int(camera.capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    'height': int(camera.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    'fps': camera.capture.get(cv2.CAP_PROP_FPS),
                    'brightness': camera.capture.get(cv2.CAP_PROP_BRIGHTNESS),
                    'contrast': camera.capture.get(cv2.CAP_PROP_CONTRAST),
                    'saturation': camera.capture.get(cv2.CAP_PROP_SATURATION),
                    'hue': camera.capture.get(cv2.CAP_PROP_HUE),
                    'gain': camera.capture.get(cv2.CAP_PROP_GAIN),
                    'exposure': camera.capture.get(cv2.CAP_PROP_EXPOSURE),
                    'auto_exposure': camera.capture.get(cv2.CAP_PROP_AUTO_EXPOSURE),
                    'buffer_size': camera.capture.get(cv2.CAP_PROP_BUFFERSIZE),
                }
                
                return properties
            
            except Exception as e:
                self.logger.error(f"获取摄像头 {camera.display_name} 属性时发生错误: {e}")
                return None
    
    def cleanup(self) -> None:
        """清理资源"""
        self.logger.info("正在清理摄像头管理器资源...")
        
        with self.lock:
            # 断开所有摄像头
            for camera_id in list(self.cameras.keys()):
                self.disconnect_camera(camera_id)
            
            self.cameras.clear()
        
        self.logger.info("摄像头管理器资源清理完成") 