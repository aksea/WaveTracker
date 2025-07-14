"""
IMU数据写入线程

专门负责IMU数据文件写入的消费者线程，从队列中获取数据并写入CSV文件。
实现生产者-消费者架构中的消费者部分。
"""

import threading
import queue
import time
import csv
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from PyQt5.QtCore import QThread, pyqtSignal

from utils.logger import get_logger
from utils.time_utils import time_manager, TimeUtils
from utils.config_manager import get_config_manager
from .data_type import WriterState, IMUData, WriterConfig


class IMUWriterThread(QThread):
    """IMU数据写入线程 - 消费者线程"""
    
    # 信号定义
    writer_started = pyqtSignal(str)  # 写入器开始信号
    writer_stopped = pyqtSignal(str, dict)  # 写入器停止信号
    writer_error = pyqtSignal(str, str)  # 写入器错误信号
    data_written = pyqtSignal(str, int)  # 数据写入信号 (device_address, data_count)
    
    def __init__(self):
        """
        初始化IMU数据写入线程。

        从配置文件中加载性能设置，例如队列大小。
        """
        super().__init__()
        
        self.logger = get_logger("imu_writer_thread")
        
        # 配置管理器
        self.config_manager = get_config_manager()
        
        # 从配置加载参数
        writer_settings = self.config_manager.get_imu_writer_settings()
        queue_size = writer_settings.get('queue_size', 1000)
        
        # 任务队列
        self.data_queue = queue.Queue(maxsize=queue_size)
        
        # 写入器管理
        self.writers: Dict[str, Any] = {}  # 文件写入器
        self.writer_configs: Dict[str, WriterConfig] = {}
        self.writer_states: Dict[str, WriterState] = {}
        self.writer_stats: Dict[str, dict] = {}
        
        # 控制标志
        self.is_running = False
        self.should_stop = False
        
        # 线程锁
        self.writers_lock = threading.Lock()
        
        self.logger.info("IMU数据写入线程初始化完成")
    
    def start_writer(self, config: WriterConfig) -> bool:
        """
        启动写入器
        
        Args:
            config (WriterConfig): 写入器配置
            
        Returns:
            bool: 是否成功启动
        """
        with self.writers_lock:
            device_address = config.device_address
            
            # 检查是否已经在写入
            if device_address in self.writers:
                self.logger.warning(f"设备 {device_address} 已经在录制中")
                return False
            
            try:
                # 确保输出目录存在
                config.output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 创建CSV文件写入器
                csv_file = open(config.output_path, 'w', newline='', encoding='utf-8')
                csv_writer = csv.writer(csv_file)
                
                # 写入CSV头部
                header = ['system_timestamp', 'device_timestamp',
                          'linear_accel_x', 'linear_accel_y', 'linear_accel_z',
                          'accel_with_gravity_x', 'accel_with_gravity_y', 'accel_with_gravity_z',
                          'gyro_x', 'gyro_y', 'gyro_z',
                          'angle_roll', 'angle_pitch', 'angle_yaw']
                csv_writer.writerow(header)
                csv_file.flush()
                
                # 保存配置和状态
                self.writers[device_address] = {
                    'file': csv_file,
                    'writer': csv_writer
                }
                from datetime import datetime
                self.writer_configs[device_address] = config
                self.writer_states[device_address] = WriterState.WRITING
                # 获取当前系统时间戳（毫秒）
                start_time_ms = time_manager.get_timestamp_ms()
                self.writer_stats[device_address] = {
                    'start_time': start_time_ms,
                    'data_count': 0,
                    'dropped_data': 0,
                    'last_data_time': None
                }
                
                self.logger.info(f"启动写入器 - 设备 {device_address}: {config.output_path}")
                
                self.writer_started.emit(device_address)
                return True
                
            except Exception as e:
                self.logger.error(f"启动写入器失败 - 设备 {device_address}: {e}")
                self.writer_error.emit(device_address, str(e))
                return False
    
    def stop_writer(self, device_address: str) -> bool:
        """
        停止写入器
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            bool: 是否成功停止
        """
        with self.writers_lock:
            if device_address not in self.writers:
                self.logger.warning(f"设备 {device_address} 没有在录制中")
                return False
            
            # 标记为停止状态
            self.writer_states[device_address] = WriterState.STOPPING
            
        self.logger.info(f"请求停止写入器 - 设备 {device_address}")
        return True
    
    def add_data(self, imu_data: IMUData) -> bool:
        """
        添加数据到队列
        
        Args:
            imu_data (IMUData): IMU数据
            
        Returns:
            bool: 是否成功添加
        """
        try:
            # 检查是否有对应的写入器
            with self.writers_lock:
                if imu_data.device_address not in self.writers:
                    return False
                
                if self.writer_states[imu_data.device_address] != WriterState.WRITING:
                    return False
            
            # 非阻塞添加到队列
            self.data_queue.put_nowait(imu_data)
            return True
            
        except queue.Full:
            # 队列满了，丢弃数据
            with self.writers_lock:
                if imu_data.device_address in self.writer_stats:
                    self.writer_stats[imu_data.device_address]['dropped_data'] += 1
            
            self.logger.warning(f"数据队列已满，丢弃设备 {imu_data.device_address} 的数据")
            return False
    
    def get_queue_size(self) -> int:
        """
        获取队列大小
        
        Returns:
            int: 当前队列大小
        """
        return self.data_queue.qsize()
    
    def get_writer_stats(self, device_address: str) -> Optional[dict]:
        """
        获取写入器统计信息
        
        Args:
            device_address (str): 设备地址
            
        Returns:
            Optional[dict]: 统计信息
        """
        with self.writers_lock:
            if device_address not in self.writer_stats:
                return None
            
            stats = self.writer_stats[device_address].copy()
            
            # 计算写入时长
            if stats['start_time']:
                current_time = time_manager.get_timestamp_ms()
                stats['duration'] = (current_time - stats['start_time']) / 1000.0
                
                # 计算平均数据率
                if stats['duration'] > 0:
                    stats['average_rate'] = stats['data_count'] / stats['duration']
                else:
                    stats['average_rate'] = 0
            
            return stats
    
    def run(self):
        """线程主循环"""
        self.logger.info("IMU数据写入线程开始运行")
        
        self.is_running = True
        self.should_stop = False
        
        try:
            while not self.should_stop:
                try:
                    # 从队列获取数据，设置超时以便检查停止标志
                    imu_data = self.data_queue.get(timeout=0.1)
                    
                    # 处理数据
                    self._process_data(imu_data)
                    
                    # 标记任务完成
                    self.data_queue.task_done()
                    
                except queue.Empty:
                    # 队列为空，检查是否需要停止写入器
                    self._check_stopping_writers()
                    continue
                
                except Exception as e:
                    self.logger.error(f"处理数据时发生错误: {e}")
                    continue
        
        except Exception as e:
            self.logger.error(f"IMU数据写入线程运行时发生错误: {e}")
        
        finally:
            # 清理所有写入器
            self._cleanup_all_writers()
            self.is_running = False
            self.logger.info("IMU数据写入线程结束运行")
    
    def _process_data(self, imu_data: IMUData):
        """
        处理单个数据
        
        Args:
            imu_data (IMUData): IMU数据
        """
        device_address = imu_data.device_address
        
        with self.writers_lock:
            # 检查写入器是否存在
            if device_address not in self.writers:
                return
            
            writer_info = self.writers[device_address]
            state = self.writer_states[device_address]
            
            # 如果正在停止，跳过写入
            if state == WriterState.STOPPING:
                return
            
            try:
                # 提取数据
                data = imu_data.data
                timestamp = data.get('timestamp', 0)
                linear_accel = data.get('linear_accel', {})
                accel_with_gravity = data.get('accel_with_gravity', {})
                gyro = data.get('gyro', {})
                angle = data.get('angle', {})

                # 格式化系统时间戳
                formatted_sys_time = TimeUtils.format_timestamp(imu_data.timestamp)
                
                # 写入CSV行
                row = [
                    formatted_sys_time,
                    timestamp,
                    linear_accel.get('x', 0),
                    linear_accel.get('y', 0),
                    linear_accel.get('z', 0),
                    accel_with_gravity.get('x', 0),
                    accel_with_gravity.get('y', 0),
                    accel_with_gravity.get('z', 0),
                    gyro.get('x', 0),
                    gyro.get('y', 0),
                    gyro.get('z', 0),
                    angle.get('roll', 0),
                    angle.get('pitch', 0),
                    angle.get('yaw', 0)
                ]
                
                writer_info['writer'].writerow(row)
                writer_info['file'].flush()
                
                # 更新统计信息
                stats = self.writer_stats[device_address]
                stats['data_count'] += 1
                stats['last_data_time'] = imu_data.timestamp
                
                # 发送写入信号
                self.data_written.emit(device_address, stats['data_count'])
                
            except Exception as e:
                self.logger.error(f"写入数据失败 - 设备 {device_address}: {e}")
                self.writer_states[device_address] = WriterState.ERROR
                self.writer_error.emit(device_address, str(e))
    
    def _check_stopping_writers(self):
        """检查需要停止的写入器"""
        with self.writers_lock:
            stopping_writers = []
            
            for device_address, state in self.writer_states.items():
                if state == WriterState.STOPPING:
                    stopping_writers.append(device_address)
            
            # 停止写入器
            for device_address in stopping_writers:
                self._finalize_writer(device_address)
    
    def _finalize_writer(self, device_address: str):
        """
        完成写入器的清理工作
        
        Args:
            device_address (str): 设备地址
        """
        try:
            writer_info = self.writers[device_address]
            config = self.writer_configs[device_address]
            stats = self.writer_stats[device_address]
            
            # 关闭文件
            writer_info['file'].close()
            
            # 计算最终统计信息
            end_time = time_manager.get_timestamp_ms()
            duration = (end_time - stats['start_time']) / 1000.0
            
            final_stats = {
                'data_count': stats['data_count'],
                'dropped_data': stats['dropped_data'],
                'duration': duration,
                'average_rate': stats['data_count'] / duration if duration > 0 else 0,
                'output_path': str(config.output_path),
                'file_size': config.output_path.stat().st_size if config.output_path.exists() else 0
            }
            
            # 清理资源
            del self.writers[device_address]
            del self.writer_configs[device_address]
            del self.writer_states[device_address]
            del self.writer_stats[device_address]
            
            self.logger.info(f"写入器完成 - 设备 {device_address}: "
                           f"数据量 {final_stats['data_count']}, "
                           f"时长 {final_stats['duration']:.1f}s, "
                           f"平均速率 {final_stats['average_rate']:.1f}/s, "
                           f"丢失数据 {final_stats['dropped_data']}")
            
            # 发送完成信号
            self.writer_stopped.emit(device_address, final_stats)
            
        except Exception as e:
            self.logger.error(f"完成写入器时发生错误 - 设备 {device_address}: {e}")
            self.writer_error.emit(device_address, str(e))
    
    def _cleanup_all_writers(self):
        """清理所有写入器"""
        with self.writers_lock:
            for device_address in list(self.writers.keys()):
                try:
                    self._finalize_writer(device_address)
                except Exception as e:
                    self.logger.error(f"清理写入器时发生错误 - 设备 {device_address}: {e}")
    
    def stop_thread(self):
        """停止线程"""
        self.logger.info("请求停止IMU数据写入线程")
        self.should_stop = True
        
        # 停止所有写入器
        with self.writers_lock:
            for device_address in list(self.writers.keys()):
                self.writer_states[device_address] = WriterState.STOPPING
    
    def cleanup(self):
        """清理资源"""
        self.logger.info("正在清理IMU数据写入线程资源...")
        
        # 停止线程
        self.stop_thread()
        
        # 等待线程结束
        if self.isRunning():
            self.wait(5000)  # 最多等待5秒
        
        # 清理队列
        try:
            while not self.data_queue.empty():
                self.data_queue.get_nowait()
                self.data_queue.task_done()
        except queue.Empty:
            pass
        
        self.logger.info("IMU数据写入线程资源清理完成") 