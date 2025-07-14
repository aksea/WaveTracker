"""
进程管理器

负责管理多个子进程的启动、停止、监控和通信。
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Optional, List, Any, Callable
from dataclasses import dataclass
from enum import Enum

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from utils.config_manager import get_config_manager
from utils.logger import get_logger


class ProcessStatus(Enum):
    """进程状态枚举"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ProcessInfo:
    """进程信息"""
    process_id: str
    process_type: str  # 'imu' or 'camera'
    instance_id: int
    status: ProcessStatus
    process: Optional[subprocess.Popen] = None
    start_time: Optional[float] = None
    error_message: Optional[str] = None


class ProcessManager:
    """进程管理器"""
    
    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        """
        初始化进程管理器
        
        Args:
            log_callback (Optional[Callable[[str], None]]): 日志回调函数
        """
        self.logger = get_logger("process_manager")
        self.config_manager = get_config_manager()
        self.log_callback = log_callback
        
        # 进程信息字典
        self.processes: Dict[str, ProcessInfo] = {}
        
        # 获取配置
        self.management_settings = self.config_manager.get_multiprocess_management_settings()
        
        # 脚本路径
        self.script_dir = Path(__file__).parent.parent.parent / "application"
        self.imu_script = self.script_dir / "gui_imu_subprocess.py"
        self.camera_script = self.script_dir / "gui_camera_subprocess.py"
        
        # 延迟初始化日志，避免在UI未完全初始化时调用
        self.logger.info("进程管理器已初始化")
    
    def log_message(self, message: str):
        """记录日志消息"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def load_process_config(self):
        """从配置文件加载进程配置"""
        try:
            process_counts = self.config_manager.get_process_counts()
            imu_count = process_counts.get('imu_count', 1)
            camera_count = process_counts.get('camera_count', 1)
            
            # 清空现有进程信息
            self.processes.clear()
            
            # 创建IMU进程信息
            for i in range(imu_count):
                process_id = f"imu_{i+1}"
                self.processes[process_id] = ProcessInfo(
                    process_id=process_id,
                    process_type="imu",
                    instance_id=i+1,
                    status=ProcessStatus.STOPPED
                )
            
            # 创建摄像头进程信息
            for i in range(camera_count):
                process_id = f"camera_{i+1}"
                self.processes[process_id] = ProcessInfo(
                    process_id=process_id,
                    process_type="camera",
                    instance_id=i+1,
                    status=ProcessStatus.STOPPED
                )
            
            self.log_message(f"进程配置已加载: IMU={imu_count}, Camera={camera_count}")
            return True
            
        except Exception as e:
            self.log_message(f"加载进程配置失败: {e}")
            return False
    
    def save_process_config(self, imu_count: int, camera_count: int) -> bool:
        """保存进程配置"""
        try:
            success = self.config_manager.set_process_counts(imu_count, camera_count)
            if success:
                self.log_message("进程配置已保存")
                return True
            else:
                self.log_message("保存进程配置失败")
                return False
        except Exception as e:
            self.log_message(f"保存进程配置失败: {e}")
            return False
    
    def get_process_list(self) -> List[ProcessInfo]:
        """获取进程列表"""
        return list(self.processes.values())
    
    def get_process_info(self, process_id: str) -> Optional[ProcessInfo]:
        """获取进程信息"""
        return self.processes.get(process_id)
    
    def start_process(self, process_id: str) -> bool:
        """启动单个进程"""
        if process_id not in self.processes:
            self.log_message(f"未找到进程: {process_id}")
            return False
        
        process_info = self.processes[process_id]
        
        # 检查进程状态
        if process_info.status != ProcessStatus.STOPPED:
            self.log_message(f"进程 {process_id} 已在运行或正在启动")
            return False
        
        try:
            # 更新状态
            process_info.status = ProcessStatus.STARTING
            process_info.error_message = None
            
            # 确定脚本路径
            if process_info.process_type == "imu":
                script_path = self.imu_script
            else:  # camera
                script_path = self.camera_script
            
            # 启动进程
            cmd = [sys.executable, str(script_path), process_id]
            process_info.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            process_info.start_time = time.time()
            process_info.status = ProcessStatus.RUNNING
            
            self.log_message(f"进程 {process_id} 启动成功")
            return True
            
        except Exception as e:
            process_info.status = ProcessStatus.ERROR
            process_info.error_message = str(e)
            self.log_message(f"启动进程 {process_id} 失败: {e}")
            return False
    
    def stop_process(self, process_id: str) -> bool:
        """停止单个进程"""
        if process_id not in self.processes:
            self.log_message(f"未找到进程: {process_id}")
            return False
        
        process_info = self.processes[process_id]
        
        if process_info.status != ProcessStatus.RUNNING:
            self.log_message(f"进程 {process_id} 未在运行")
            return False
        
        try:
            process_info.status = ProcessStatus.STOPPING
            
            # 发送停止命令
            if process_info.process and process_info.process.stdin:
                self.send_command(process_id, "stop")
            
            # 等待进程结束
            timeout = self.management_settings.get('shutdown_timeout', 5.0)
            if process_info.process:
                try:
                    process_info.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # 强制终止
                    process_info.process.terminate()
                    process_info.process.wait(timeout=2.0)
            
            process_info.status = ProcessStatus.STOPPED
            process_info.process = None
            process_info.start_time = None
            
            self.log_message(f"进程 {process_id} 已停止")
            return True
            
        except Exception as e:
            process_info.status = ProcessStatus.ERROR
            process_info.error_message = str(e)
            self.log_message(f"停止进程 {process_id} 失败: {e}")
            return False
    
    def start_all_processes(self) -> bool:
        """启动所有进程"""
        success = True
        for process_id in self.processes:
            if not self.start_process(process_id):
                success = False
        
        if success:
            self.log_message("所有进程启动成功")
        else:
            self.log_message("部分进程启动失败")
        
        return success
    
    def stop_all_processes(self) -> bool:
        """停止所有进程"""
        success = True
        for process_id in self.processes:
            if not self.stop_process(process_id):
                success = False
        
        if success:
            self.log_message("所有进程已停止")
        else:
            self.log_message("部分进程停止失败")
        
        return success
    
    def send_command(self, process_id: str, command: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """向进程发送命令"""
        if process_id not in self.processes:
            self.log_message(f"未找到进程: {process_id}")
            return False
        
        process_info = self.processes[process_id]
        
        if process_info.status != ProcessStatus.RUNNING or not process_info.process:
            self.log_message(f"进程 {process_id} 未在运行")
            return False
        
        try:
            # 构造命令消息
            message = {
                "command": command,
                "data": data or {}
            }
            
            # 发送命令
            if process_info.process.stdin:
                process_info.process.stdin.write(json.dumps(message) + "\n")
                process_info.process.stdin.flush()
            
            return True
            
        except Exception as e:
            self.log_message(f"向进程 {process_id} 发送命令失败: {e}")
            return False
    
    def send_command_to_all(self, command: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """向所有运行中的进程发送命令"""
        success_count = 0
        total_running = 0
        
        for process_id, process_info in self.processes.items():
            if process_info.status == ProcessStatus.RUNNING:
                total_running += 1
                if self.send_command(process_id, command, data):
                    success_count += 1
        
        # 如果没有运行中的进程，返回False
        if total_running == 0:
            self.log_message("没有运行中的进程")
            return False
        
        # 如果至少有一个进程成功接收命令，返回True
        success = success_count > 0
        if success:
            self.log_message(f"命令已发送到 {success_count}/{total_running} 个进程")
        else:
            self.log_message(f"命令发送失败，0/{total_running} 个进程接收")
        
        return success
    
    def sync_volunteer_name(self, volunteer_name: str) -> bool:
        """同步志愿者姓名到所有进程"""
        return self.send_command_to_all("sync_volunteer_name", {"volunteer_name": volunteer_name})
    
    def start_recording(self) -> bool:
        """开始录制"""
        return self.send_command_to_all("start_recording")
    
    def stop_recording(self) -> bool:
        """停止录制"""
        return self.send_command_to_all("stop_recording")
    
    def monitor_processes(self):
        """监控进程状态"""
        for process_id, process_info in self.processes.items():
            if process_info.status == ProcessStatus.RUNNING and process_info.process:
                # 检查进程是否还在运行
                poll_result = process_info.process.poll()
                if poll_result is not None:
                    # 进程已结束
                    process_info.status = ProcessStatus.STOPPED
                    process_info.process = None
                    process_info.start_time = None
                    
                    if poll_result != 0:
                        process_info.status = ProcessStatus.ERROR
                        process_info.error_message = f"进程异常退出，退出码: {poll_result}"
                        self.log_message(f"进程 {process_id} 异常退出，退出码: {poll_result}")
                    else:
                        self.log_message(f"进程 {process_id} 正常退出")
    
    def get_process_status_summary(self) -> Dict[str, int]:
        """获取进程状态摘要"""
        summary = {
            "total": len(self.processes),
            "running": 0,
            "stopped": 0,
            "error": 0,
            "starting": 0,
            "stopping": 0
        }
        
        for process_info in self.processes.values():
            if process_info.status == ProcessStatus.RUNNING:
                summary["running"] += 1
            elif process_info.status == ProcessStatus.STOPPED:
                summary["stopped"] += 1
            elif process_info.status == ProcessStatus.ERROR:
                summary["error"] += 1
            elif process_info.status == ProcessStatus.STARTING:
                summary["starting"] += 1
            elif process_info.status == ProcessStatus.STOPPING:
                summary["stopping"] += 1
        
        return summary
    
    def cleanup(self):
        """清理资源"""
        self.log_message("正在清理进程管理器...")
        self.stop_all_processes()
        self.log_message("进程管理器已清理") 