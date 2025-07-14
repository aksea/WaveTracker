"""
摄像头录制协调器

管理摄像头捕获线程（生产者）和视频写入线程（消费者）之间的协调。
实现完整的生产者-消费者架构。
"""

from pathlib import Path
from typing import Optional, Dict

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from utils.config_manager import get_config_manager
from utils.logger import get_logger
from .camera_reader_thread import CameraReaderThread
from .video_writer_thread import VideoWriterThread, FrameData, WriterConfig


class CameraRecorder(QObject):
    """摄像头录制协调器"""
    
    # 信号定义 - 转发来自子线程的信号
    camera_discovered = pyqtSignal(dict)      # 摄像头发现信号
    camera_connected = pyqtSignal(int)        # 摄像头连接信号
    camera_disconnected = pyqtSignal(int)     # 摄像头断开信号
    frame_received = pyqtSignal(int, object)  # 帧接收信号
    recording_started = pyqtSignal(int)       # 录制开始信号
    recording_stopped = pyqtSignal(int, dict) # 录制停止信号
    error_occurred = pyqtSignal(int, str)     # 错误信号
    
    def __init__(self):
        """
        初始化摄像头录制协调器
        """
        super().__init__()
        
        self.logger = get_logger("camera_recorder")
        
        # 初始化配置管理器
        self.config_manager = get_config_manager()
        
        # 创建生产者线程（摄像头捕获）
        self.camera_reader_thread = CameraReaderThread()
        
        # 创建消费者线程（视频写入）
        self.video_writer_thread = VideoWriterThread()
        
        # 录制状态管理
        self.recording_cameras: Dict[int, WriterConfig] = {}
        
        # 设置信号连接
        self._setup_signals()
        
        # 设置帧处理回调
        self.camera_reader_thread.set_frame_callback(self._on_frame_for_recording)
        
        self.logger.info("摄像头录制协调器初始化完成")
    
    def _setup_signals(self):
        """设置信号连接"""
        # 转发摄像头线程的信号
        self.camera_reader_thread.camera_discovered.connect(self.camera_discovered.emit)
        self.camera_reader_thread.camera_connected.connect(self.camera_connected.emit)
        self.camera_reader_thread.camera_disconnected.connect(self.camera_disconnected.emit)
        self.camera_reader_thread.frame_received.connect(self.frame_received.emit)
        self.camera_reader_thread.error_occurred.connect(self.error_occurred.emit)
        
        # 转发视频写入线程的信号
        self.video_writer_thread.writer_started.connect(self.recording_started.emit)
        self.video_writer_thread.writer_stopped.connect(self.recording_stopped.emit)
        self.video_writer_thread.writer_error.connect(self.error_occurred.emit)
    
    def _on_frame_for_recording(self, camera_id: int, frame: np.ndarray, timestamp: int):
        """
        处理用于录制的帧
        
        Args:
            camera_id (int): 摄像头ID
            frame (np.ndarray): 帧数据
            timestamp (int): 时间戳
        """
        # 只处理正在录制的摄像头
        if camera_id not in self.recording_cameras:
            return
        
        # 获取帧计数器
        frame_number = self.camera_reader_thread.frame_counter.get(camera_id, 0)
        
        # 创建帧数据
        frame_data = FrameData(
            camera_id=camera_id,
            frame=frame,
            timestamp=timestamp,
            frame_number=frame_number
        )
        
        # 发送到视频写入线程
        if not self.video_writer_thread.add_frame(frame_data):
            self.logger.warning(f"无法添加帧到写入队列 - 摄像头 {camera_id}")
    
    def start(self):
        """启动协调器"""
        self.logger.info("启动摄像头录制协调器")
        
        # 启动视频写入线程
        if not self.video_writer_thread.isRunning():
            self.video_writer_thread.start()
        
        # 启动摄像头线程
        if not self.camera_reader_thread.isRunning():
            self.camera_reader_thread.start()
    
    def stop(self):
        """停止协调器"""
        self.logger.info("停止摄像头录制协调器")
        
        # 停止所有录制
        for camera_id in list(self.recording_cameras.keys()):
            self.stop_recording(camera_id)
        
        # 停止线程
        self.camera_reader_thread.stop_thread()
        self.video_writer_thread.stop_thread()
    
    def cleanup(self):
        """清理资源"""
        self.logger.info("清理摄像头录制协调器资源")
        
        # 停止协调器
        self.stop()
        
        # 清理线程
        self.camera_reader_thread.cleanup()
        self.video_writer_thread.cleanup()
    
    # 摄像头管理方法
    def scan_cameras(self):
        """扫描摄像头"""
        self.camera_reader_thread.scan_cameras()
    
    def connect_camera(self, camera_id: int, width: Optional[int] = None, 
                      height: Optional[int] = None, fps: Optional[float] = None):
        """
        连接摄像头
        
        Args:
            camera_id (int): 摄像头ID
            width (Optional[int]): 宽度
            height (Optional[int]): 高度
            fps (Optional[float]): 帧率
        """
        self.camera_reader_thread.connect_camera(camera_id, width, height, fps)
    
    def disconnect_camera(self, camera_id: int):
        """
        断开摄像头
        
        Args:
            camera_id (int): 摄像头ID
        """
        # 如果正在录制，先停止录制
        if camera_id in self.recording_cameras:
            self.stop_recording(camera_id)
        
        self.camera_reader_thread.disconnect_camera(camera_id)
    
    def start_capture(self):
        """开始捕获"""
        self.camera_reader_thread.start_capture()
    
    def stop_capture(self):
        """停止捕获"""
        self.camera_reader_thread.stop_capture()
    
    # 录制管理方法
    def start_recording(self, camera_id: int, output_path: Path, fourcc: str = 'MP4V') -> bool:
        """
        开始录制
        
        Args:
            camera_id (int): 摄像头ID
            output_path (Path): 输出文件路径
            fourcc (str): 视频编码器
            
        Returns:
            bool: 是否成功开始录制
        """
        # 检查摄像头是否连接
        camera_info = self.camera_reader_thread.get_camera_info(camera_id)
        if not camera_info:
            self.logger.error(f"摄像头 {camera_id} 未连接")
            return False
        
        # 检查是否已经在录制
        if camera_id in self.recording_cameras:
            self.logger.warning(f"摄像头 {camera_id} 已经在录制中")
            return False
        
        # 创建写入器配置
        config = WriterConfig(
            camera_id=camera_id,
            output_path=output_path,
            width=camera_info['width'],
            height=camera_info['height'],
            fps=camera_info['fps'],
            fourcc=fourcc
        )
        
        # 启动写入器
        if self.video_writer_thread.start_writer(config):
            self.recording_cameras[camera_id] = config
            self.logger.info(f"开始录制摄像头 {camera_id}: {output_path}")
            return True
        else:
            self.logger.error(f"启动录制失败 - 摄像头 {camera_id}")
            return False
    
    def stop_recording(self, camera_id: int) -> bool:
        """
        停止录制
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            bool: 是否成功停止录制
        """
        if camera_id not in self.recording_cameras:
            self.logger.warning(f"摄像头 {camera_id} 没有在录制中")
            return False
        
        # 停止写入器
        if self.video_writer_thread.stop_writer(camera_id):
            del self.recording_cameras[camera_id]
            self.logger.info(f"停止录制摄像头 {camera_id}")
            return True
        else:
            self.logger.error(f"停止录制失败 - 摄像头 {camera_id}")
            return False
    
    def is_recording(self, camera_id: int) -> bool:
        """
        检查是否正在录制
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            bool: 是否正在录制
        """
        return camera_id in self.recording_cameras
    
    def get_all_camera_info(self) -> list:
        """
        获取所有已发现摄像头的信息列表
        
        Returns:
            list: 包含所有摄像头信息字典的列表
        """
        if self.camera_reader_thread:
            return self.camera_reader_thread.get_all_cameras()
        return []

    def get_connected_cameras(self) -> list:
        """获取已连接摄像头列表"""
        return self.camera_reader_thread.get_connected_cameras()
    
    def get_camera_info(self, camera_id: int) -> Optional[dict]:
        """
        获取摄像头信息
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 摄像头信息
        """
        return self.camera_reader_thread.get_camera_info(camera_id)
    
    def get_latest_frame(self, camera_id: int) -> Optional[dict]:
        """
        获取最新帧
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 最新帧数据
        """
        return self.camera_reader_thread.get_latest_frame(camera_id)
    
    def get_recording_stats(self, camera_id: int) -> Optional[dict]:
        """
        获取录制统计信息
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 录制统计信息
        """
        return self.video_writer_thread.get_writer_stats(camera_id)
    
    def get_queue_size(self) -> int:
        """
        获取写入队列大小
        
        Returns:
            int: 当前队列大小
        """
        return self.video_writer_thread.get_queue_size()
    
    # 设置方法
    def set_camera_resolution(self, camera_id: int, width: int, height: int):
        """
        设置摄像头分辨率
        
        Args:
            camera_id (int): 摄像头ID
            width (int): 宽度
            height (int): 高度
        """
        self.camera_reader_thread.set_camera_resolution(camera_id, width, height)
    
    def set_camera_fps(self, camera_id: int, fps: float):
        """
        设置摄像头帧率
        
        Args:
            camera_id (int): 摄像头ID
            fps (float): 帧率
        """
        self.camera_reader_thread.set_camera_fps(camera_id, fps) 