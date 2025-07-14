"""
IMU模块数据类型定义

将所有IMU相关的dataclass和Enum集中在此，便于管理和复用。
"""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any
from bleak import BleakClient


# -------------------
# Enums
# -------------------

class IMUConnectionState(Enum):
    """IMU连接状态枚举 (from imu_manager)"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class WriterState(Enum):
    """写入器状态 (from imu_writer_thread)"""
    IDLE = "idle"
    WRITING = "writing"
    STOPPING = "stopping"
    ERROR = "error"


# ---------------------
# Dataclasses
# ---------------------

@dataclass
class IMUDevice:
    """IMU设备信息 (from imu_manager)"""
    address: str
    name: str
    rssi: Optional[int] = None
    state: IMUConnectionState = IMUConnectionState.DISCONNECTED
    client: Optional[BleakClient] = None
    last_data_time: Optional[int] = None
    error_message: Optional[str] = None
    manual_disconnect: bool = False
    custom_name: Optional[str] = None

    @property
    def display_name(self) -> str:
        """获取显示名称"""
        return self.custom_name or self.name or self.address


@dataclass
class IMUData:
    """IMU数据结构 (from imu_writer_thread)"""
    device_address: str
    timestamp: int
    data: Dict[str, Any]
    data_count: int


@dataclass
class WriterConfig:
    """写入器配置 (from imu_writer_thread)"""
    device_address: str
    output_path: Path

    def __post_init__(self):
        """确保输出路径有正确的扩展名"""
        if not str(self.output_path).endswith('.csv'):
            self.output_path = self.output_path.with_suffix('.csv')
