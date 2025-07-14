#!/usr/bin/env python3
"""
摄像头功能测试GUI (生产者-消费者架构版本)

基于core.camera.camera_recorder，提供一个完整的GUI界面，用于测试和演示：
- 摄像头扫描、连接、断开
- 实时视频流显示
- 视频录制功能（使用生产者-消费者架构）
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional
from collections import deque

import numpy as np

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QPushButton, QLabel, QTextEdit,
                             QGroupBox, QComboBox, QListWidget,
                             QListWidgetItem, QLineEdit, QFormLayout)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QImage, QPixmap, QFont
import cv2

from core.camera.camera_recorder import CameraRecorder
from utils.config_manager import get_config_manager


class CameraTestGUI(QMainWindow):
    """摄像头测试GUI主窗口（生产者-消费者架构版本）"""
    
    def __init__(self):
        super().__init__()
        self.camera_recorder: Optional[CameraRecorder] = None
        self.discovered_devices: Dict[int, dict] = {}
        self.connected_devices: Dict[int, dict] = {}
        self.current_display_camera: Optional[int] = None
        self.is_recording: Dict[int, bool] = {}
        self.frame_timestamps: Dict[int, deque] = {} # 用于计算实际帧率
        self.display_size_cache = QSize(0, 0) # 缓存显示尺寸以优化
        
        # 初始化配置管理器
        self.config_manager = get_config_manager()
        
        # 志愿者信息
        self.volunteer_name = ""
        
        self.init_ui()
        self.start_camera_recorder()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("摄像头功能测试 (生产者-消费者架构)")
        self.setGeometry(100, 100, 1400, 900)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        
        # 左侧控制面板
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel, 1)
        
        # 右侧显示区域
        display_area = self.create_display_area()
        main_layout.addWidget(display_area, 3)

    def create_display_area(self) -> QWidget:
        """创建右侧显示区域"""
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        # 顶部栏：设备选择 + 录制状态
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addWidget(QLabel("显示设备:"))
        self.device_selector = QComboBox()
        self.device_selector.addItem("请选择设备", None)
        self.device_selector.currentIndexChanged.connect(self.on_device_selection_changed)
        top_bar_layout.addWidget(self.device_selector)
        top_bar_layout.addStretch()
        
        self.fps_label = QLabel("FPS: --")
        top_bar_layout.addWidget(self.fps_label)
        
        # 添加队列大小显示
        self.queue_label = QLabel("队列: --")
        top_bar_layout.addWidget(self.queue_label)
        
        self.recording_status_label = QLabel("● 未录制")
        self.recording_status_label.setStyleSheet("color: gray; font-weight: bold;")
        top_bar_layout.addWidget(self.recording_status_label)
        
        layout.addLayout(top_bar_layout)

        # 视频显示区域
        self.video_display_label = QLabel("未选择摄像头")
        self.video_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_display_label.setMinimumSize(640, 480)
        self.video_display_label.setStyleSheet("background-color: black; color: white;")
        layout.addWidget(self.video_display_label, 1) # 占据更多空间

        return widget
    
    def create_control_panel(self) -> QWidget:
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)
        
        # 扫描组
        scan_group = QGroupBox("1. 扫描与连接")
        scan_layout = QVBoxLayout()
        scan_group.setLayout(scan_layout)
        
        # 志愿者姓名输入
        volunteer_layout = QHBoxLayout()
        volunteer_layout.addWidget(QLabel("志愿者姓名:"))
        self.volunteer_input = QLineEdit()
        self.volunteer_input.setPlaceholderText("请输入志愿者姓名")
        self.volunteer_input.textChanged.connect(self.on_volunteer_name_changed)
        volunteer_layout.addWidget(self.volunteer_input)
        scan_layout.addLayout(volunteer_layout)
        
        self.scan_button = QPushButton("扫描摄像头")
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_button.setEnabled(False)  # 需要输入志愿者姓名才能扫描
        scan_layout.addWidget(self.scan_button)
        layout.addWidget(scan_group)
        
        # 设备管理组
        device_group = QGroupBox("2. 设备管理")
        device_layout = QVBoxLayout()
        device_group.setLayout(device_layout)
        
        device_layout.addWidget(QLabel("发现的设备:"))
        self.discovered_list = QListWidget()
        self.discovered_list.setMaximumHeight(150)
        device_layout.addWidget(self.discovered_list)
        
        connect_layout = QHBoxLayout()
        self.connect_button = QPushButton("连接选中")
        self.connect_button.clicked.connect(self.connect_selected_device)
        connect_layout.addWidget(self.connect_button)
        self.connect_all_button = QPushButton("连接所有")
        self.connect_all_button.clicked.connect(self.connect_all_devices)
        connect_layout.addWidget(self.connect_all_button)
        device_layout.addLayout(connect_layout)
        
        device_layout.addWidget(QLabel("已连接设备:"))
        self.connected_list = QListWidget()
        self.connected_list.setMaximumHeight(150)
        device_layout.addWidget(self.connected_list)
        
        disconnect_layout = QHBoxLayout()
        self.disconnect_button = QPushButton("断开选中")
        self.disconnect_button.clicked.connect(self.disconnect_selected_device)
        disconnect_layout.addWidget(self.disconnect_button)
        self.disconnect_all_button = QPushButton("断开所有")
        self.disconnect_all_button.clicked.connect(self.disconnect_all_devices)
        disconnect_layout.addWidget(self.disconnect_all_button)
        device_layout.addLayout(disconnect_layout)
        layout.addWidget(device_group)

        # 配置组
        config_group = QGroupBox("3. 配置设置")
        config_layout = QFormLayout()
        config_group.setLayout(config_layout)
        
        # 数据路径显示
        self.data_path_label = QLabel("请先输入志愿者姓名")
        self.data_path_label.setWordWrap(True)
        self.data_path_label.setStyleSheet("color: gray; background-color: #f0f0f0; padding: 5px; border: 1px solid #ccc;")
        config_layout.addRow("数据路径:", self.data_path_label)
        
        # 默认帧率显示（从配置文件读取，只读）
        default_fps = self.config_manager.get("camera.default_fps", 30.0)
        fps_label = QLabel(f"{default_fps} fps")
        fps_label.setStyleSheet("color: gray;")
        config_layout.addRow("默认帧率:", fps_label)
        
        # 默认分辨率显示（从配置文件读取，只读）
        default_width = self.config_manager.get("camera.default_resolution.width", 640)
        default_height = self.config_manager.get("camera.default_resolution.height", 480)
        resolution_label = QLabel(f"{default_width}x{default_height}")
        resolution_label.setStyleSheet("color: gray;")
        config_layout.addRow("默认分辨率:", resolution_label)
        
        layout.addWidget(config_group)

        # 录制组
        record_group = QGroupBox("4. 视频录制")
        record_layout = QHBoxLayout()
        record_group.setLayout(record_layout)
        self.start_record_button = QPushButton("开始录制所有")
        self.start_record_button.clicked.connect(self.start_recording_all)
        self.start_record_button.setEnabled(False)
        record_layout.addWidget(self.start_record_button)
        self.stop_record_button = QPushButton("停止录制所有")
        self.stop_record_button.clicked.connect(self.stop_recording_all)
        self.stop_record_button.setEnabled(False)
        record_layout.addWidget(self.stop_record_button)
        layout.addWidget(record_group)
        
        # 日志区域
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        self.log_text = QTextEdit()
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)
        
        layout.addStretch()
        return panel
    
    def start_camera_recorder(self):
        """启动摄像头录制协调器"""
        if self.camera_recorder is None:
            self.camera_recorder = CameraRecorder()
            # 连接信号
            self.camera_recorder.camera_connected.connect(self.on_camera_connected)
            self.camera_recorder.camera_disconnected.connect(self.on_camera_disconnected)
            self.camera_recorder.frame_received.connect(self.on_frame_received)
            self.camera_recorder.recording_started.connect(self.on_recording_started)
            self.camera_recorder.recording_stopped.connect(self.on_recording_stopped)
            self.camera_recorder.error_occurred.connect(self.on_error)
            
            self.camera_recorder.start()
            self.log_message("摄像头录制协调器已启动。")
            
            # 启动定时器更新队列信息
            self.update_timer = QTimer()
            self.update_timer.timeout.connect(self.update_queue_info)
            self.update_timer.start(1000)  # 每秒更新一次
    
    def on_volunteer_name_changed(self):
        """志愿者姓名变更回调"""
        self.volunteer_name = self.volunteer_input.text().strip()
        
        if self.volunteer_name:
            # 生成数据保存路径
            base_path = Path(__file__).parent.parent / "data" / self.volunteer_name / "camera"
            self.data_path_label.setText(str(base_path))
            self.data_path_label.setStyleSheet("color: black; background-color: white; padding: 5px; border: 1px solid #ccc;")
            self.scan_button.setEnabled(True)
        else:
            self.data_path_label.setText("请先输入志愿者姓名")
            self.data_path_label.setStyleSheet("color: gray; background-color: #f0f0f0; padding: 5px; border: 1px solid #ccc;")
            self.scan_button.setEnabled(False)
    
    def update_queue_info(self):
        """更新队列信息"""
        if self.camera_recorder:
            queue_size = self.camera_recorder.get_queue_size()
            self.queue_label.setText(f"队列: {queue_size}")
    
    def start_scan(self):
        """开始扫描"""
        if not self.volunteer_name:
            self.log_message("请先输入志愿者姓名")
            return
            
        self.discovered_list.clear()
        self.discovered_devices.clear()
        
        self.scan_button.setEnabled(False)
        self.scan_button.setText("正在扫描...")
        self.log_message(f"开始扫描摄像头，志愿者: {self.volunteer_name}...")
        if self.camera_recorder:
            self.camera_recorder.scan_cameras()
        # 异步扫描完成后，更新整个列表
        QTimer.singleShot(2000, self.update_discovered_list)

    def update_discovered_list(self):
        """扫描结束后，获取所有设备并更新UI"""
        self.log_message("正在更新设备列表...")
        if not self.camera_recorder:
            self.scan_button.setEnabled(True)
            self.scan_button.setText("扫描摄像头")
            return

        all_devices = self.camera_recorder.get_all_camera_info()
        self.discovered_list.clear()
        self.discovered_devices.clear()

        for device_info in all_devices:
            self.on_camera_discovered(device_info)

        # 恢复扫描按钮状态并报告结果
        self.scan_button.setEnabled(True)
        self.scan_button.setText("扫描摄像头")
        self.log_message(f"摄像头扫描完成，发现 {len(all_devices)} 个设备。")

    def on_camera_discovered(self, device_info: dict):
        """
        将发现的摄像头信息更新到UI列表中。
        此方法由 `update_discovered_list` 调用。
        """
        camera_id = device_info['id']
        
        # 避免重复添加
        if camera_id in self.discovered_devices:
            return
            
        self.discovered_devices[camera_id] = device_info
        
        item = QListWidgetItem(f"ID {camera_id}: {device_info['display_name']}")
        item.setData(Qt.ItemDataRole.UserRole, camera_id)
        self.discovered_list.addItem(item)
        
        self.log_message(f"发现/更新摄像头: {device_info['display_name']} (ID: {camera_id})")
    
    def connect_selected_device(self):
        """连接选中的设备"""
        current_item = self.discovered_list.currentItem()
        if current_item:
            camera_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.log_message(f"连接摄像头 ID {camera_id}...")
            if self.camera_recorder:
                self.camera_recorder.connect_camera(camera_id)
    
    def connect_all_devices(self):
        """连接所有设备"""
        self.log_message("连接所有发现的摄像头...")
        if self.camera_recorder:
            for cam_id in self.discovered_devices.keys():
                self.camera_recorder.connect_camera(cam_id)
    
    def on_camera_connected(self, camera_id: int):
        """摄像头连接成功回调"""
        device_info = self.discovered_devices.get(camera_id)
        if device_info:
            self.connected_devices[camera_id] = device_info
            
            item = QListWidgetItem(f"ID {camera_id}: {device_info['display_name']}")
            item.setData(Qt.ItemDataRole.UserRole, camera_id)
            self.connected_list.addItem(item)
            
            self.log_message(f"摄像头连接成功: {device_info['display_name']} (ID: {camera_id})")
            
            # 更新设备选择器
            self.update_device_lists()
            
            # 只在第一次有摄像头连接时启动捕获
            if self.camera_recorder and len(self.connected_devices) == 1:
                self.camera_recorder.start_capture()
                self.log_message("开始视频捕获")
    
    def disconnect_selected_device(self):
        """断开选中的设备"""
        current_item = self.connected_list.currentItem()
        if current_item:
            camera_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.log_message(f"断开摄像头 ID {camera_id}...")
            if self.camera_recorder:
                self.camera_recorder.disconnect_camera(camera_id)
    
    def disconnect_all_devices(self):
        """断开所有设备"""
        self.log_message("断开所有摄像头...")
        if self.camera_recorder:
            for camera_id in list(self.connected_devices.keys()):
                self.camera_recorder.disconnect_camera(camera_id)
    
    def on_camera_disconnected(self, camera_id: int):
        """摄像头断开回调"""
        if camera_id in self.connected_devices:
            device_info = self.connected_devices[camera_id]
            del self.connected_devices[camera_id]
            
            # 从已连接列表中移除
            for i in range(self.connected_list.count()):
                item = self.connected_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == camera_id:
                    self.connected_list.takeItem(i)
                    break
            
            self.log_message(f"摄像头断开连接: {device_info['display_name']} (ID: {camera_id})")
            
            # 更新设备选择器
            self.update_device_lists()
            
            # 如果没有连接的摄像头了，停止捕获
            if self.camera_recorder and len(self.connected_devices) == 0:
                self.camera_recorder.stop_capture()
                self.log_message("停止视频捕获")
            
            # 如果当前显示的是这个摄像头，清除显示
            if self.current_display_camera == camera_id:
                self.current_display_camera = None
                self.video_display_label.setText("摄像头已断开")
                self.fps_label.setText("FPS: --")
    
    def on_frame_received(self, camera_id: int, frame: np.ndarray):
        """帧接收回调"""
        # 计算实际帧率
        if camera_id not in self.frame_timestamps:
            self.frame_timestamps[camera_id] = deque(maxlen=30)
        
        current_time = time.time()
        self.frame_timestamps[camera_id].append(current_time)
        
        # 计算FPS
        if len(self.frame_timestamps[camera_id]) > 1:
            time_diff = current_time - self.frame_timestamps[camera_id][0]
            if time_diff > 0:
                fps = (len(self.frame_timestamps[camera_id]) - 1) / time_diff
                if self.current_display_camera == camera_id:
                    self.fps_label.setText(f"FPS: {fps:.1f}")
        
        # 如果是当前选中的摄像头，显示帧
        if self.current_display_camera == camera_id:
            self.display_frame(frame)
    
    def display_frame(self, frame: np.ndarray):
        """显示帧"""
        try:
            # 获取当前显示区域的尺寸
            display_size = self.video_display_label.size()
            
            # 只有在尺寸变化时才更新缓存
            if display_size != self.display_size_cache:
                self.display_size_cache = display_size
            
            # 使用cv2.resize进行缩放，性能更好
            display_width = self.display_size_cache.width()
            display_height = self.display_size_cache.height()
            
            if display_width > 0 and display_height > 0:
                # 保持宽高比
                h, w = frame.shape[:2]
                aspect_ratio = w / h
                
                if display_width / display_height > aspect_ratio:
                    # 高度为准
                    new_height = display_height
                    new_width = int(display_height * aspect_ratio)
                else:
                    # 宽度为准
                    new_width = display_width
                    new_height = int(display_width / aspect_ratio)
                
                # 使用cv2.resize缩放
                resized_frame = cv2.resize(frame, (new_width, new_height))
                
                # 转换为RGB
                rgb_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
                
                # 创建QImage
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                
                # 修复QImage创建问题
                frame_copy = rgb_frame.copy()
                qt_image = QImage(frame_copy.data.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888)
                
                # 转换为QPixmap并显示
                pixmap = QPixmap.fromImage(qt_image)
                self.video_display_label.setPixmap(pixmap)
        
        except Exception as e:
            print(f"显示帧时出错: {e}")
    
    def resizeEvent(self, event):
        """窗口大小变化事件"""
        super().resizeEvent(event)
        # 重置缓存，强制重新计算显示尺寸
        self.display_size_cache = QSize(0, 0)
    
    def on_device_selection_changed(self):
        """设备选择变化回调"""
        current_data = self.device_selector.currentData()
        if current_data is not None:
            self.current_display_camera = current_data
            self.log_message(f"切换显示设备到 ID {current_data}")
        else:
            self.current_display_camera = None
            self.video_display_label.setText("未选择摄像头")
            self.fps_label.setText("FPS: --")
        
        # 更新录制控件状态
        self.update_recording_controls()
    
    def update_device_lists(self):
        """更新设备列表"""
        # 更新设备选择器
        self.device_selector.clear()
        self.device_selector.addItem("请选择设备", None)
        
        for camera_id, device_info in self.connected_devices.items():
            self.device_selector.addItem(
                f"ID {camera_id}: {device_info['display_name']}", 
                camera_id
            )
        
        # 更新录制控件状态
        self.update_recording_controls()
    
    def start_recording_all(self):
        """开始录制所有已连接的摄像头"""
        if not self.connected_devices:
            self.log_message("没有已连接的摄像头可供录制")
            return

        if not self.volunteer_name:
            self.log_message("请先输入志愿者姓名")
            return

        self.log_message(f"准备开始录制所有 {len(self.connected_devices)} 个已连接的摄像头...")

        # 使用基于志愿者姓名的数据路径
        if not self.camera_recorder:
            self.log_message("摄像头录制器未初始化")
            return
            
        data_path = Path(__file__).parent.parent / "data" / self.volunteer_name / "camera"
        data_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = int(time.time())

        for cam_id in self.connected_devices.keys():
            if self.camera_recorder and self.camera_recorder.is_recording(cam_id):
                self.log_message(f"摄像头 {cam_id} 已经在录制中，跳过。")
                continue

            output_path = data_path / f"camera_{cam_id}_{timestamp}.mp4"

            self.log_message(f"开始录制摄像头 {cam_id} 到 {output_path}")

            if self.camera_recorder:
                if not self.camera_recorder.start_recording(cam_id, output_path, fourcc='MP4V'):
                    self.log_message(f"启动录制失败 - 摄像头 {cam_id}")

    def stop_recording_all(self):
        """停止录制所有正在录制的摄像头"""
        # 查找所有正在录制的摄像头ID
        recording_cams = [cam_id for cam_id, is_rec in self.is_recording.items() if is_rec]

        if not recording_cams:
            self.log_message("没有正在录制的摄像头。")
            return

        self.log_message(f"准备停止录制 {len(recording_cams)} 个摄像头...")

        for cam_id in recording_cams:
            if self.camera_recorder and self.camera_recorder.is_recording(cam_id):
                self.log_message(f"停止录制摄像头 {cam_id}")
                self.camera_recorder.stop_recording(cam_id)
            else:
                # 如果状态不一致，进行清理
                self.is_recording[cam_id] = False
        
        # 录制控件的状态将通过 on_recording_stopped 信号更新
        self.update_recording_controls()

    def on_recording_started(self, camera_id: int):
        """录制开始回调"""
        self.is_recording[camera_id] = True
        self.log_message(f"摄像头 {camera_id} 开始录制")
        self.update_recording_controls()
    
    def on_recording_stopped(self, camera_id: int, stats: dict):
        """录制停止回调"""
        self.is_recording[camera_id] = False
        self.log_message(f"摄像头 {camera_id} 录制完成 - "
                        f"帧数: {stats.get('frame_count', 0)}, "
                        f"时长: {stats.get('duration', 0):.1f}s, "
                        f"平均FPS: {stats.get('average_fps', 0):.1f}, "
                        f"丢帧: {stats.get('dropped_frames', 0)}")
        self.update_recording_controls()
    
    def update_recording_controls(self):
        """更新录制控件状态"""
        # 如果没有连接设备，禁用所有录制按钮
        if not self.connected_devices:
            self.start_record_button.setEnabled(False)
            self.stop_record_button.setEnabled(False)
            self.recording_status_label.setText("● 无连接设备")
            self.recording_status_label.setStyleSheet("color: gray; font-weight: bold;")
            return

        # 检查是否有任何一个连接的摄像头正在录制
        is_any_recording = any(self.is_recording.get(cam_id) for cam_id in self.connected_devices.keys())

        if is_any_recording:
            self.start_record_button.setEnabled(False)
            self.stop_record_button.setEnabled(True)
            self.recording_status_label.setText("● 正在录制")
            self.recording_status_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.start_record_button.setEnabled(True)
            self.stop_record_button.setEnabled(False)
            self.recording_status_label.setText("● 未录制")
            self.recording_status_label.setStyleSheet("color: gray; font-weight: bold;")
    
    def on_error(self, camera_id: int, error: str):
        """错误回调"""
        self.log_message(f"摄像头 {camera_id} 错误: {error}")
    
    def log_message(self, message: str):
        """记录日志消息"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.log_message("正在关闭应用程序...")
        
        # 停止定时器
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        
        # 清理摄像头录制协调器
        if self.camera_recorder:
            self.camera_recorder.cleanup()
        
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = CameraTestGUI()
    window.show()
    
    # 运行应用
    sys.exit(app.exec_())


if __name__ == "__main__":
    main() 