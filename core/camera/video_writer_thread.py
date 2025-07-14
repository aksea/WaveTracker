"""
视频写入线程

专门负责视频文件写入的消费者线程，从队列中获取帧数据并写入视频文件。
同时生成对应的帧时间戳CSV文件。
实现生产者-消费者架构中的消费者部分。
"""

import csv
import queue
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from utils.config_manager import get_config_manager
from utils.logger import get_logger
from utils.time_utils import time_manager
from .data_type import WriterState, FrameData, WriterConfig


class VideoWriterThread(QThread):
    """视频写入线程 - 消费者线程"""
    
    # 信号定义
    writer_started = pyqtSignal(int)  # 写入器开始信号
    writer_stopped = pyqtSignal(int, dict)  # 写入器停止信号
    writer_error = pyqtSignal(int, str)  # 写入器错误信号
    frame_written = pyqtSignal(int, int)  # 帧写入信号 (camera_id, frame_count)
    
    def __init__(self):
        """
        初始化视频写入线程
        """
        super().__init__()
        
        self.logger = get_logger("video_writer_thread")

        # 配置管理器
        self.config_manager = get_config_manager()
        
        # 从配置加载参数
        writer_settings = self.config_manager.get_camera_writer_settings()
        queue_size = writer_settings.get('queue_size', 1000)
        
        # 任务队列
        self.write_queue = queue.Queue(maxsize=queue_size)
        
        # 写入器管理
        self.writers: Dict[int, cv2.VideoWriter] = {}
        self.csv_writers: Dict[int, csv.writer] = {}  # CSV写入器
        self.csv_files: Dict[int, object] = {}  # CSV文件句柄
        self.writer_configs: Dict[int, WriterConfig] = {}
        self.writer_states: Dict[int, WriterState] = {}
        self.writer_stats: Dict[int, dict] = {}
        
        # 控制标志
        self.is_running = False
        self.should_stop = False
        
        # 线程锁
        self.writers_lock = threading.Lock()
        
        self.logger.info("视频写入线程初始化完成")
    
    def start_writer(self, config: WriterConfig) -> bool:
        """
        启动写入器
        
        Args:
            config (WriterConfig): 写入器配置
            
        Returns:
            bool: 是否成功启动
        """
        with self.writers_lock:
            camera_id = config.camera_id
            
            # 检查是否已经在写入
            if camera_id in self.writers:
                self.logger.warning(f"摄像头 {camera_id} 已经在录制中")
                return False
            
            try:
                # 确保输出目录存在
                config.output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 创建视频写入器
                fourcc = cv2.VideoWriter_fourcc(*config.fourcc)
                writer = cv2.VideoWriter(
                    str(config.output_path),
                    fourcc,
                    config.fps,
                    (config.width, config.height)
                )
                
                if not writer.isOpened():
                    raise Exception(f"无法创建视频写入器: {config.output_path}")
                
                # 创建对应的CSV时间戳文件
                csv_path = config.output_path.with_suffix('.csv')
                csv_file = open(csv_path, 'w', newline='', encoding='utf-8')
                csv_writer = csv.writer(csv_file)
                csv_writer.writerow(['frame_index', 'timestamp_ms', 'timestamp_formatted'])
                
                # 保存配置和状态
                self.writers[camera_id] = writer
                self.csv_files[camera_id] = csv_file
                self.csv_writers[camera_id] = csv_writer
                self.writer_configs[camera_id] = config
                self.writer_states[camera_id] = WriterState.WRITING
                self.writer_stats[camera_id] = {
                    'start_time': time_manager.get_timestamp_ms(),
                    'frame_count': 0,
                    'dropped_frames': 0,
                    'last_frame_time': None
                }
                
                self.logger.info(f"启动写入器 - 摄像头 {camera_id}: {config.output_path} "
                               f"({config.width}x{config.height}, {config.fps:.1f}fps, {config.fourcc})")
                self.logger.info(f"创建时间戳文件 - 摄像头 {camera_id}: {csv_path}")
                
                self.writer_started.emit(camera_id)
                return True
                
            except Exception as e:
                self.logger.error(f"启动写入器失败 - 摄像头 {camera_id}: {e}")
                self.writer_error.emit(camera_id, str(e))
                return False
    
    def stop_writer(self, camera_id: int) -> bool:
        """
        停止写入器
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            bool: 是否成功停止
        """
        with self.writers_lock:
            if camera_id not in self.writers:
                self.logger.warning(f"摄像头 {camera_id} 没有在录制中")
                return False
            
            # 标记为停止状态
            self.writer_states[camera_id] = WriterState.STOPPING
            
        self.logger.info(f"请求停止写入器 - 摄像头 {camera_id}")
        return True
    
    def add_frame(self, frame_data: FrameData) -> bool:
        """
        添加帧到队列
        
        Args:
            frame_data (FrameData): 帧数据
            
        Returns:
            bool: 是否成功添加
        """
        try:
            # 检查是否有对应的写入器
            with self.writers_lock:
                if frame_data.camera_id not in self.writers:
                    return False
                
                if self.writer_states[frame_data.camera_id] != WriterState.WRITING:
                    return False
            
            # 非阻塞添加到队列
            self.write_queue.put_nowait(frame_data)
            return True
            
        except queue.Full:
            # 队列满了，丢弃帧
            with self.writers_lock:
                if frame_data.camera_id in self.writer_stats:
                    self.writer_stats[frame_data.camera_id]['dropped_frames'] += 1
            
            self.logger.warning(f"帧队列已满，丢弃摄像头 {frame_data.camera_id} 的帧")
            return False
    
    def get_queue_size(self) -> int:
        """
        获取队列大小
        
        Returns:
            int: 当前队列大小
        """
        return self.write_queue.qsize()
    
    def get_writer_stats(self, camera_id: int) -> Optional[dict]:
        """
        获取写入器统计信息
        
        Args:
            camera_id (int): 摄像头ID
            
        Returns:
            Optional[dict]: 统计信息
        """
        with self.writers_lock:
            if camera_id not in self.writer_stats:
                return None
            
            stats = self.writer_stats[camera_id].copy()
            
            # 计算写入时长
            if stats['start_time']:
                current_time = time_manager.get_timestamp_ms()
                stats['duration'] = (current_time - stats['start_time']) / 1000.0
                
                # 计算平均帧率
                if stats['duration'] > 0:
                    stats['average_fps'] = stats['frame_count'] / stats['duration']
                else:
                    stats['average_fps'] = 0
            
            return stats
    
    def run(self):
        """线程主循环"""
        self.logger.info("视频写入线程开始运行")
        
        self.is_running = True
        self.should_stop = False
        
        try:
            while not self.should_stop:
                try:
                    # 从队列获取帧数据，设置超时以便检查停止标志
                    frame_data = self.write_queue.get(timeout=0.1)
                    
                    # 处理帧数据
                    self._process_frame(frame_data)
                    
                    # 标记任务完成
                    self.write_queue.task_done()
                    
                except queue.Empty:
                    # 队列为空，检查是否需要停止写入器
                    self._check_stopping_writers()
                    continue
                
                except Exception as e:
                    self.logger.error(f"处理帧时发生错误: {e}")
                    continue
        
        except Exception as e:
            self.logger.error(f"视频写入线程运行时发生错误: {e}")
        
        finally:
            # 清理所有写入器
            self._cleanup_all_writers()
            self.is_running = False
            self.logger.info("视频写入线程结束运行")
    
    def _process_frame(self, frame_data: FrameData):
        """
        处理单个帧
        
        Args:
            frame_data (FrameData): 帧数据
        """
        camera_id = frame_data.camera_id
        
        with self.writers_lock:
            # 检查写入器是否存在
            if camera_id not in self.writers:
                return
            
            writer = self.writers[camera_id]
            state = self.writer_states[camera_id]
            
            # 如果正在停止，跳过写入
            if state == WriterState.STOPPING:
                return
            
            try:
                # 写入帧
                writer.write(frame_data.frame)
                
                # 更新统计信息
                stats = self.writer_stats[camera_id]
                stats['frame_count'] += 1
                stats['last_frame_time'] = frame_data.timestamp
                
                # 写入时间戳到CSV文件
                if camera_id in self.csv_writers:
                    from utils.time_utils import TimeUtils
                    csv_writer = self.csv_writers[camera_id]
                    timestamp_formatted = TimeUtils.format_timestamp(frame_data.timestamp)
                    csv_writer.writerow([stats['frame_count'], frame_data.timestamp, timestamp_formatted])
                    # 立即刷新CSV文件，确保数据被写入
                    self.csv_files[camera_id].flush()
                
                # 发送写入信号
                self.frame_written.emit(camera_id, stats['frame_count'])
                
            except Exception as e:
                self.logger.error(f"写入帧失败 - 摄像头 {camera_id}: {e}")
                self.writer_states[camera_id] = WriterState.ERROR
                self.writer_error.emit(camera_id, str(e))
    
    def _check_stopping_writers(self):
        """检查需要停止的写入器"""
        with self.writers_lock:
            stopping_writers = []
            
            for camera_id, state in self.writer_states.items():
                if state == WriterState.STOPPING:
                    stopping_writers.append(camera_id)
            
            # 停止写入器
            for camera_id in stopping_writers:
                self._finalize_writer(camera_id)
    
    def _finalize_writer(self, camera_id: int):
        """
        完成写入器的清理工作
        
        Args:
            camera_id (int): 摄像头ID
        """
        try:
            writer = self.writers[camera_id]
            config = self.writer_configs[camera_id]
            stats = self.writer_stats[camera_id]
            
            # 释放写入器
            writer.release()
            
            # 关闭CSV文件
            if camera_id in self.csv_files:
                self.csv_files[camera_id].close()
            
            # 计算最终统计信息
            end_time = time_manager.get_timestamp_ms()
            duration = (end_time - stats['start_time']) / 1000.0
            
            final_stats = {
                'frame_count': stats['frame_count'],
                'dropped_frames': stats['dropped_frames'],
                'duration': duration,
                'average_fps': stats['frame_count'] / duration if duration > 0 else 0,
                'output_path': str(config.output_path),
                'file_size': config.output_path.stat().st_size if config.output_path.exists() else 0
            }
            
            # 清理资源
            del self.writers[camera_id]
            if camera_id in self.csv_files:
                del self.csv_files[camera_id]
            if camera_id in self.csv_writers:
                del self.csv_writers[camera_id]
            del self.writer_configs[camera_id]
            del self.writer_states[camera_id]
            del self.writer_stats[camera_id]
            
            self.logger.info(f"写入器完成 - 摄像头 {camera_id}: "
                           f"帧数 {final_stats['frame_count']}, "
                           f"时长 {final_stats['duration']:.1f}s, "
                           f"平均FPS {final_stats['average_fps']:.1f}, "
                           f"丢帧 {final_stats['dropped_frames']}")
            
            # 发送完成信号
            self.writer_stopped.emit(camera_id, final_stats)
            
        except Exception as e:
            self.logger.error(f"完成写入器时发生错误 - 摄像头 {camera_id}: {e}")
            self.writer_error.emit(camera_id, str(e))
    
    def _cleanup_all_writers(self):
        """清理所有写入器"""
        with self.writers_lock:
            for camera_id in list(self.writers.keys()):
                try:
                    self._finalize_writer(camera_id)
                except Exception as e:
                    self.logger.error(f"清理写入器时发生错误 - 摄像头 {camera_id}: {e}")
    
    def stop_thread(self):
        """停止线程"""
        self.logger.info("请求停止视频写入线程")
        self.should_stop = True
        
        # 停止所有写入器
        with self.writers_lock:
            for camera_id in list(self.writers.keys()):
                self.writer_states[camera_id] = WriterState.STOPPING
    
    def cleanup(self):
        """清理资源"""
        self.logger.info("正在清理视频写入线程资源...")
        
        # 停止线程
        self.stop_thread()
        
        # 等待线程结束
        if self.isRunning():
            self.wait(5000)  # 最多等待5秒
        
        # 清理队列
        try:
            while not self.write_queue.empty():
                self.write_queue.get_nowait()
                self.write_queue.task_done()
        except queue.Empty:
            pass
        
        self.logger.info("视频写入线程资源清理完成") 