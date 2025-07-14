"""
摄像头设备管理模块

该模块负责：
- USB摄像头和Continuity Camera的检测和初始化
- 多路摄像头的并发视频采集
- 视频流的处理和编码
""" 
from .camera_reader_thread import CameraReaderThread
from .camera_recorder import CameraRecorder
from .camera_manager import CameraManager
from .video_writer_thread import VideoWriterThread

__all__ = [
    "CameraReaderThread",
    "CameraRecorder",
    "CameraManager",
    "VideoWriterThread"
]
