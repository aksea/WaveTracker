"""
摄像头模块数据类型定义

将所有摄像头相关的dataclass和Enum集中在此，便于管理和复用。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple
import cv2
from pathlib import Path
import numpy as np
from collections import deque


# -------------------
# Enums
# -------------------

class CameraState(Enum):
    """摄像头状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECORDING = "recording"
    ERROR = "error"


class WriterState(Enum):
    """写入器状态"""
    IDLE = "idle"
    WRITING = "writing"
    STOPPING = "stopping"
    ERROR = "error"


# ---------------------
# Dataclasses
# ---------------------

@dataclass
class CameraDevice:
    """摄像头设备信息"""
    id: int
    name: str
    width: int = 640
    height: int = 480
    fps: float = 30.0
    state: CameraState = CameraState.DISCONNECTED
    capture: Optional[cv2.VideoCapture] = None
    error_message: Optional[str] = None
    frame_timestamps: deque = field(default_factory=lambda: deque(maxlen=30), repr=False)

    @property
    def measured_fps(self) -> float:
        """根据最近的帧时间戳计算并返回实测的帧率。

        Returns:
            float: 实测的FPS，如果时间戳不足则返回0.0。
        """
        if len(self.frame_timestamps) < 2:
            return 0.0

        # 时间戳单位是毫秒
        time_diff_ms = self.frame_timestamps[-1] - self.frame_timestamps[0]
        if time_diff_ms <= 0:
            return 0.0

        time_diff_s = time_diff_ms / 1000.0
        # 帧数是时间戳数量减1
        num_frames = len(self.frame_timestamps) - 1
        if num_frames <= 0:
            return 0.0

        return num_frames / time_diff_s

    @property
    def display_name(self) -> str:
        """获取显示名称"""
        return self.name or f"Camera {self.id}"
    
    @property
    def resolution(self) -> Tuple[int, int]:
        """获取分辨率"""
        return (self.width, self.height)


@dataclass
class FrameData:
    """帧数据结构"""
    camera_id: int
    frame: np.ndarray
    timestamp: int
    frame_number: int


@dataclass
class WriterConfig:
    """写入器配置"""
    camera_id: int
    output_path: Path
    width: int
    height: int
    fps: float
    fourcc: str = 'MP4V'
    
    def __post_init__(self):
        """确保输出路径有正确的扩展名"""
        if self.fourcc == 'MP4V' and not str(self.output_path).endswith('.mp4'):
            self.output_path = self.output_path.with_suffix('.mp4') 