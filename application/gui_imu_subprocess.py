#!/usr/bin/env python3
"""
IMU数据实时显示和录制GUI (子进程版本)

基于原有的gui_imu_test.py，增加进程间通信功能
支持主进程的志愿者姓名同步和录制控制
"""

import datetime
import os
import sys
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from core.multiprocessing.IPCHandler import IPCHandler

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
                             QGroupBox, QGridLayout, QComboBox, QListWidget,
                             QListWidgetItem, QFileDialog)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont
import pyqtgraph as pg
from pyqtgraph import PlotWidget, mkPen

from core.imu.data_type import IMUDevice
from core.imu.imu_recorder import IMURecorder
from utils.config_manager import get_config_manager





class IMUPlotWidget(QWidget):
    """IMU数据绘图组件"""
    
    def __init__(self, parent_gui: 'IMUSubprocessGUI'):
        """
        初始化绘图组件
        Args:
            parent_gui: 父级GUI窗口的引用，用于访问IMURecorder
        """
        super().__init__()
        self.gui_parent = parent_gui
        self.known_devices: List[str] = []
        self.current_device: Optional[str] = None
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()
        
        # 设置pyqtgraph背景色
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        
        # 创建设备选择控件
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("显示设备:"))
        self.device_selector = QComboBox()
        self.device_selector.addItem("请选择设备", None)
        self.device_selector.currentIndexChanged.connect(self.on_device_changed)
        device_layout.addWidget(self.device_selector)
        device_layout.addStretch()
        
        layout.addLayout(device_layout)
        
        # 创建加速度图表
        self.accel_plot = PlotWidget(title="含重力加速度 (m/s^2)")
        self.accel_plot.setLabel('left', '加速度', units='m/s^2')
        self.accel_plot.setLabel('bottom', '时间', units='s')
        self.accel_plot.showGrid(x=True, y=True, alpha=0.3)
        self.accel_plot.addLegend()
        
        # 创建角速度图表
        self.gyro_plot = PlotWidget(title="角速度 (°/s)")
        self.gyro_plot.setLabel('left', '角速度', units='°/s')
        self.gyro_plot.setLabel('bottom', '时间', units='s')
        self.gyro_plot.showGrid(x=True, y=True, alpha=0.3)
        self.gyro_plot.addLegend()
        
        # 添加到布局
        layout.addWidget(self.accel_plot)
        layout.addWidget(self.gyro_plot)
        
        # 初始化曲线
        self.accel_curves = {}
        self.gyro_curves = {}
        
        # 定义颜色和标签
        colors = ['r', 'g', 'b']
        labels = ['X', 'Y', 'Z']
        
        for i, (color, label) in enumerate(zip(colors, labels)):
            # 加速度曲线
            self.accel_curves[label.lower()] = self.accel_plot.plot(
                [], [], pen=mkPen(color=color, width=2), name=f'含重力加速度 {label}'
            )
            
            # 角速度曲线
            self.gyro_curves[label.lower()] = self.gyro_plot.plot(
                [], [], pen=mkPen(color=color, width=2), name=f'角速度 {label}'
            )
        
        self.setLayout(layout)
    
    def add_device(self, address: str, display_name: str):
        """添加设备"""
        if address not in self.known_devices:
            self.known_devices.append(address)
            self.device_selector.addItem(display_name, address)
            
            # 如果这是第一个设备，自动选择
            if len(self.known_devices) == 1:
                self.device_selector.setCurrentIndex(1)  # 跳过"请选择设备"选项
    
    def remove_device(self, address: str):
        """移除设备"""
        if address in self.known_devices:
            self.known_devices.remove(address)
            
            # 从下拉框中移除
            for i in range(self.device_selector.count()):
                if self.device_selector.itemData(i) == address:
                    self.device_selector.removeItem(i)
                    break
            
            # 如果当前显示的设备被移除，清空显示
            if self.current_device == address:
                self.current_device = None
                self.clear_plot()
    
    def trigger_redraw_if_current(self, address: str):
        """如果传入的地址是当前显示的设备，则触发重绘"""
        if self.current_device == address:
            self.update_plot()

    def on_device_changed(self):
        """设备选择改变回调"""
        current_address = self.device_selector.currentData()
        if current_address != self.current_device:
            self.current_device = current_address
            if current_address:
                self.update_plot()
            else:
                self.clear_plot()
    
    def _prepare_plot_data(self, raw_data: List[Dict]) -> Dict[str, np.ndarray]:
        """将从核心缓冲区获取的原始数据转换为绘图格式"""
        if not raw_data:
            return {
                'timestamps': np.array([]), 'accel_x': np.array([]),
                'accel_y': np.array([]), 'accel_z': np.array([]),
                'gyro_x': np.array([]), 'gyro_y': np.array([]),
                'gyro_z': np.array([])
            }

        # 为了性能，预分配列表
        timestamps, ax, ay, az, gx, gy, gz = ([] for _ in range(7))

        for data_point in raw_data:
            timestamps.append(data_point.get('timestamp', 0))
            accel = data_point.get('accel_with_gravity', {})
            gyro = data_point.get('gyro', {})
            ax.append(accel.get('x', 0))
            ay.append(accel.get('y', 0))
            az.append(accel.get('z', 0))
            gx.append(gyro.get('x', 0))
            gy.append(gyro.get('y', 0))
            gz.append(gyro.get('z', 0))

        return {
            'timestamps': np.array(timestamps), 'accel_x': np.array(ax),
            'accel_y': np.array(ay), 'accel_z': np.array(az),
            'gyro_x': np.array(gx), 'gyro_y': np.array(gy),
            'gyro_z': np.array(gz)
        }

    def update_plot(self):
        """更新图形"""
        if not self.current_device or not self.gui_parent.imu_recorder:
            self.clear_plot()
            return
        
        # 从核心缓冲区拉取数据
        raw_data = self.gui_parent.imu_recorder.get_all_data(self.current_device)
        data = self._prepare_plot_data(raw_data)
        
        if len(data['timestamps']) == 0:
            self.clear_plot()
            return
        
        # 计算相对时间（以第一个时间戳为基准）
        if len(data['timestamps']) > 0:
            relative_time = data['timestamps'] - data['timestamps'][0]
        else:
            relative_time = data['timestamps']
        
        # 更新加速度曲线
        self.accel_curves['x'].setData(relative_time, data['accel_x'])
        self.accel_curves['y'].setData(relative_time, data['accel_y'])
        self.accel_curves['z'].setData(relative_time, data['accel_z'])
        
        # 更新角速度曲线
        self.gyro_curves['x'].setData(relative_time, data['gyro_x'])
        self.gyro_curves['y'].setData(relative_time, data['gyro_y'])
        self.gyro_curves['z'].setData(relative_time, data['gyro_z'])
    
    def clear_plot(self):
        """清空图形"""
        # 清空曲线
        for curve in self.accel_curves.values():
            curve.setData([], [])
        for curve in self.gyro_curves.values():
            curve.setData([], [])
    
    def clear_device_data(self, address: str):
        """清空指定设备的数据"""
        if self.current_device == address:
            self.clear_plot()
    
    def clear_all_data(self):
        """清空所有设备数据"""
        self.clear_plot()


class IMUSubprocessGUI(QMainWindow):
    """IMU子进程GUI主窗口"""
    
    def __init__(self):
        super().__init__()
        self.imu_recorder: Optional[IMURecorder] = None
        self.discovered_devices = {}  # 存储发现的设备
        self.connected_devices = {}   # 存储已连接的设备
        self.device_data_counts = {}  # 存储每个设备的数据计数
        self.recording_devices = {}   # 存储正在录制的设备
        
        # 配置管理器
        self.config_manager = get_config_manager()
        
        # 志愿者信息（从主进程同步）
        self.volunteer_name = ""
        
        # 进程实例标识
        self.instance_id = self.parse_instance_id()
        
        # 进程间通信处理器
        self.ipc_handler = IPCHandler()
        self.setup_ipc_connections()
        
        self.init_ui()
    
    def parse_instance_id(self) -> str:
        """解析进程实例标识"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--instance', default='imu_1', help='进程实例标识')
        args, _ = parser.parse_known_args()
        return args.instance
        
    def setup_ipc_connections(self):
        """设置进程间通信连接"""
        self.ipc_handler.volunteer_name_received.connect(self.on_volunteer_name_received)
        self.ipc_handler.start_recording_received.connect(self.on_start_recording_received)
        self.ipc_handler.stop_recording_received.connect(self.on_stop_recording_received)
        self.ipc_handler.stop_process_received.connect(self.quit_application)
    
    def quit_application(self):
        """安全退出应用程序的槽函数"""
        self.close()

    def on_volunteer_name_received(self, volunteer_name: str):
        """接收到志愿者姓名同步"""
        self.volunteer_name = volunteer_name
        self.volunteer_input.setText(volunteer_name)
        self.volunteer_input.setEnabled(False)  # 禁用编辑，由主进程控制
        self.scan_button.setEnabled(bool(volunteer_name))
        self.log_message(f"已从主进程同步志愿者姓名: {volunteer_name}")
    
    def on_start_recording_received(self):
        """接收到开始录制命令"""
        self.start_recording_all()
        self.log_message("收到主进程开始录制命令")
    
    def on_stop_recording_received(self):
        """接收到停止录制命令"""
        self.stop_recording_all()
        self.log_message("收到主进程停止录制命令")
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle(f"IMU 多设备6DOF数据实时显示和录制 (子进程 - {self.instance_id})")
        self.setGeometry(100, 100, 1600, 1000)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        
        # 创建右侧绘图区域
        self.plot_widget = IMUPlotWidget(self)
        
        # 创建左侧控制面板
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel, 1)
        
        main_layout.addWidget(self.plot_widget, 3)
        
        # 启动IMU录制器
        self.start_imu_recorder()
    
    def create_control_panel(self):
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)
        
        # 进程信息组
        process_group = QGroupBox("进程信息")
        process_layout = QVBoxLayout()
        process_group.setLayout(process_layout)
        
        process_info_label = QLabel(f"此窗口为IMU子进程 ({self.instance_id})")
        process_info_label.setStyleSheet("color: blue; font-weight: bold;")
        process_layout.addWidget(process_info_label)
        
        control_info_label = QLabel("志愿者姓名和录制由主进程控制")
        control_info_label.setStyleSheet("color: gray;")
        process_layout.addWidget(control_info_label)
        
        layout.addWidget(process_group)
        
        # 扫描设置组
        scan_group = QGroupBox("扫描设置")
        scan_layout = QGridLayout()
        scan_group.setLayout(scan_layout)
        
        # 志愿者姓名输入（只读显示）
        scan_layout.addWidget(QLabel("志愿者姓名:"), 0, 0)
        self.volunteer_input = QLineEdit()
        self.volunteer_input.setPlaceholderText("等待主进程同步...")
        self.volunteer_input.setEnabled(False)  # 禁用编辑
        scan_layout.addWidget(self.volunteer_input, 0, 1)
        
        self.scan_button = QPushButton("开始扫描")
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_button.setEnabled(False)
        scan_layout.addWidget(self.scan_button, 1, 0, 1, 2)
        
        layout.addWidget(scan_group)
        
        # 设备管理组
        device_group = QGroupBox("设备管理")
        device_layout = QVBoxLayout()
        device_group.setLayout(device_layout)
        
        # 发现的设备列表
        device_layout.addWidget(QLabel("发现的设备:"))
        self.discovered_list = QListWidget()
        self.discovered_list.setMaximumHeight(120)
        device_layout.addWidget(self.discovered_list)
        
        # 连接按钮
        connect_layout = QHBoxLayout()
        self.connect_button = QPushButton("连接选中设备")
        self.connect_button.clicked.connect(self.connect_selected_device)
        self.connect_button.setEnabled(False)
        connect_layout.addWidget(self.connect_button)
        
        self.connect_all_button = QPushButton("连接所有设备")
        self.connect_all_button.clicked.connect(self.connect_all_devices)
        self.connect_all_button.setEnabled(False)
        connect_layout.addWidget(self.connect_all_button)
        
        device_layout.addLayout(connect_layout)
        
        # 已连接设备列表
        device_layout.addWidget(QLabel("已连接设备:"))
        self.connected_list = QListWidget()
        self.connected_list.setMaximumHeight(120)
        device_layout.addWidget(self.connected_list)
        
        # 断开按钮
        disconnect_layout = QHBoxLayout()
        self.disconnect_button = QPushButton("断开选中设备")
        self.disconnect_button.clicked.connect(self.disconnect_selected_device)
        self.disconnect_button.setEnabled(False)
        disconnect_layout.addWidget(self.disconnect_button)
        
        self.disconnect_all_button = QPushButton("断开所有设备")
        self.disconnect_all_button.clicked.connect(self.disconnect_all_devices)
        self.disconnect_all_button.setEnabled(False)
        disconnect_layout.addWidget(self.disconnect_all_button)
        
        device_layout.addLayout(disconnect_layout)
        
        layout.addWidget(device_group)
        
        # 录制管理组（显示状态，由主进程控制）
        record_group = QGroupBox("录制管理 (主进程控制)")
        record_layout = QVBoxLayout()
        record_group.setLayout(record_layout)
        
        self.record_status_label = QLabel("录制状态: 等待主进程命令")
        self.record_status_label.setStyleSheet("color: gray; font-weight: bold;")
        record_layout.addWidget(self.record_status_label)
        
        layout.addWidget(record_group)
        
        # 状态信息组
        status_group = QGroupBox("状态信息")
        status_layout = QVBoxLayout()
        status_group.setLayout(status_layout)
        
        self.status_label = QLabel("等待扫描...")
        status_layout.addWidget(self.status_label)
        
        self.total_data_label = QLabel("总接收数据: 0 条")
        status_layout.addWidget(self.total_data_label)
        
        self.device_status_label = QLabel("设备状态: 无")
        status_layout.addWidget(self.device_status_label)
        
        layout.addWidget(status_group)
        
        # 操作按钮组
        action_group = QGroupBox("操作")
        action_layout = QVBoxLayout()
        action_group.setLayout(action_layout)
        
        self.clear_button = QPushButton("清空当前设备数据")
        self.clear_button.clicked.connect(self.clear_current_data)
        action_layout.addWidget(self.clear_button)
        
        self.clear_all_button = QPushButton("清空所有设备数据")
        self.clear_all_button.clicked.connect(self.clear_all_data)
        action_layout.addWidget(self.clear_all_button)
        
        layout.addWidget(action_group)
        
        # 日志区域
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(200)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_group)
        
        return panel
    
    def start_imu_recorder(self):
        """启动IMU录制器"""
        if self.imu_recorder is None:
            self.imu_recorder = IMURecorder()
            self.imu_recorder.device_discovered.connect(self.on_device_discovered)
            self.imu_recorder.device_connected.connect(self.on_device_connected)
            self.imu_recorder.device_disconnected.connect(self.on_device_disconnected)
            self.imu_recorder.data_received.connect(self.on_data_received)
            self.imu_recorder.error_occurred.connect(self.on_error)
            self.imu_recorder.scan_finished.connect(self.scan_finished)
            self.imu_recorder.recording_started.connect(self.on_recording_started)
            self.imu_recorder.recording_stopped.connect(self.on_recording_stopped)
            self.imu_recorder.start()
    
    def start_scan(self):
        """开始扫描"""
        if not self.imu_recorder:
            self.start_imu_recorder()
        
        if not self.volunteer_name:
            self.log_message("等待主进程同步志愿者姓名")
            return
        
        # 清空设备列表
        self.discovered_devices.clear()
        self.discovered_list.clear()
        self.connect_button.setEnabled(False)
        self.connect_all_button.setEnabled(False)
        
        # 从配置文件获取扫描参数
        scan_settings = self.config_manager.get_imu_scan_settings()
        duration = scan_settings.get('duration', 10.0)
        name_filter = scan_settings.get('name_filter', ["im948"])
        
        # 开始扫描
        self.scan_button.setEnabled(False)
        self.status_label.setText("正在扫描...")
        self.log_message(f"开始扫描设备，志愿者: {self.volunteer_name}, 过滤条件: {', '.join(name_filter)}")
        
        if self.imu_recorder:
            self.imu_recorder.start_scan(duration, name_filter=name_filter)
    
    def scan_finished(self):
        """扫描完成"""
        self.scan_button.setEnabled(True)
        self.status_label.setText("扫描完成")
        
        if len(self.discovered_devices) == 0:
            self.log_message("未发现符合条件的设备")
        else:
            self.connect_button.setEnabled(True)
            self.connect_all_button.setEnabled(True)
            self.log_message(f"发现 {len(self.discovered_devices)} 个设备")
    
    def connect_selected_device(self):
        """连接选中的设备"""
        current_item = self.discovered_list.currentItem()
        if current_item and self.imu_recorder:
            address = current_item.data(Qt.ItemDataRole.UserRole)
            self.log_message(f"正在连接设备: {address}")
            self.imu_recorder.connect_device(address)
    
    def connect_all_devices(self):
        """连接所有发现的设备"""
        if self.imu_recorder:
            for address in self.discovered_devices.keys():
                if address not in self.connected_devices:
                    self.log_message(f"正在连接设备: {address}")
                    self.imu_recorder.connect_device(address)
    
    def disconnect_selected_device(self):
        """断开选中的设备"""
        current_item = self.connected_list.currentItem()
        if current_item and self.imu_recorder:
            address = current_item.data(Qt.ItemDataRole.UserRole)
            self.log_message(f"正在断开设备: {address}")
            self.imu_recorder.disconnect_device(address)
    
    def disconnect_all_devices(self):
        """断开所有设备"""
        if self.imu_recorder:
            for address in list(self.connected_devices.keys()):
                self.log_message(f"正在断开设备: {address}")
                self.imu_recorder.disconnect_device(address)
    
    def start_recording_all(self):
        """开始录制所有设备（由主进程调用）"""
        if self.imu_recorder:
            for address in self.connected_devices.keys():
                if address not in self.recording_devices:
                    self._start_recording_device(address)
    
    def stop_recording_all(self):
        """停止录制所有设备（由主进程调用）"""
        if self.imu_recorder:
            for address in list(self.recording_devices.keys()):
                if self.imu_recorder.stop_recording(address):
                    device_name = self.connected_devices[address].display_name
                    self.log_message(f"停止录制设备 {device_name}")
    
    def _start_recording_device(self, address: str):
        """开始录制指定设备"""
        if not self.imu_recorder:
            return
        
        if not self.volunteer_name:
            self.log_message("等待主进程同步志愿者姓名")
            return
        
        # 生成文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        device_name = self.connected_devices[address].display_name
        filename = f"{device_name}_{timestamp}.csv"
        
        # 创建完整路径（基于志愿者姓名，无imu子目录）
        base_path = Path(__file__).parent.parent / "data" / self.volunteer_name/ "imu"
        base_path.mkdir(parents=True, exist_ok=True)
        output_path = base_path / filename
        
        # 开始录制
        if self.imu_recorder.start_recording(address, output_path):
            self.log_message(f"开始录制设备 {device_name}: {output_path}")
        else:
            self.log_message(f"启动录制失败 - 设备 {device_name}")
    
    def clear_current_data(self):
        """清空当前显示设备的数据"""
        current_device = self.plot_widget.current_device
        if current_device:
            self.plot_widget.clear_device_data(current_device)
            if self.imu_recorder:
                self.imu_recorder.clear_device_data(current_device)
            self.log_message(f"已清空设备 {current_device} 的数据")
        else:
            self.log_message("请先选择要清空数据的设备")
    
    def clear_all_data(self):
        """清空所有设备数据"""
        self.plot_widget.clear_all_data()
        if self.imu_recorder:
            self.imu_recorder.clear_all_data()
        
        # 为所有已连接的设备重置计数器
        self.device_data_counts = {address: 0 for address in self.connected_devices.keys()}
        self.update_data_display()
        self.log_message("已清空所有设备数据")
    
    def on_device_discovered(self, device_info: IMUDevice):
        """设备发现回调"""
        address = device_info.address
        self.discovered_devices[address] = device_info
        
        display_text = f"{device_info.display_name}"
        if device_info.rssi is not None:
            display_text += f" [{device_info.rssi} dBm]"
        
        item = QListWidgetItem(display_text)
        item.setData(Qt.ItemDataRole.UserRole, address)
        self.discovered_list.addItem(item)
        
        self.log_message(f"发现设备: {display_text} ({address})")
    
    def on_device_connected(self, address):
        """设备连接回调"""
        if address in self.discovered_devices:
            device_info = self.discovered_devices[address]
            self.connected_devices[address] = device_info
            self.device_data_counts[address] = 0
            
            # 添加到绘图组件
            self.plot_widget.add_device(address, device_info.display_name)
            
            # 更新已连接设备列表
            display_text = f"{device_info.display_name}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, address)
            self.connected_list.addItem(item)
            
            self.disconnect_button.setEnabled(True)
            self.disconnect_all_button.setEnabled(True)
            
            self.update_status_display()
            self.log_message(f"设备已连接: {device_info.display_name} ({address})")
    
    def on_device_disconnected(self, address):
        """设备断开回调"""
        if address in self.connected_devices:
            device_info = self.connected_devices[address]
            del self.connected_devices[address]
            
            if address in self.device_data_counts:
                del self.device_data_counts[address]
            
            if address in self.recording_devices:
                del self.recording_devices[address]
            
            # 从绘图组件中移除
            self.plot_widget.remove_device(address)
            
            # 从已连接设备列表中移除
            for i in range(self.connected_list.count()):
                item = self.connected_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == address:
                    self.connected_list.takeItem(i)
                    break
            
            if not self.connected_devices:
                self.disconnect_button.setEnabled(False)
                self.disconnect_all_button.setEnabled(False)
            
            self.update_status_display()
            self.update_record_status_display()
            self.log_message(f"设备已断开: {device_info.display_name} ({address})")
    
    def on_data_received(self, address, data):
        """数据接收回调"""
        if address in self.device_data_counts:
            self.device_data_counts[address] += 1
        
        # 仅当设备为当前显示设备时，触发重绘
        self.plot_widget.trigger_redraw_if_current(address)
        
        self.update_data_display()
    
    def on_recording_started(self, address):
        """录制开始回调"""
        if address in self.connected_devices:
            self.recording_devices[address] = True
            device_name = self.connected_devices[address].display_name
            self.log_message(f"录制已开始: {device_name}")
            self.update_record_status_display()
    
    def on_recording_stopped(self, address, stats):
        """录制停止回调"""
        if address in self.recording_devices:
            del self.recording_devices[address]
            
            if address in self.connected_devices:
                device_name = self.connected_devices[address].display_name
                self.log_message(f"录制已停止: {device_name} - "
                               f"数据量: {stats['data_count']}, "
                               f"时长: {stats['duration']:.1f}s, "
                               f"文件大小: {stats['file_size']} bytes")
            
            self.update_record_status_display()
    
    def on_error(self, context, error):
        """错误回调"""
        self.log_message(f"错误 [{context}]: {error}")
        self.status_label.setText(f"错误: {error}")
    
    def update_status_display(self):
        """更新状态显示"""
        connected_count = len(self.connected_devices)
        if connected_count == 0:
            self.device_status_label.setText("设备状态: 无连接")
        else:
            device_names = [info.display_name for info in self.connected_devices.values()]
            self.device_status_label.setText(f"已连接设备({connected_count}): {', '.join(device_names)}")
    
    def update_record_status_display(self):
        """更新录制状态显示"""
        recording_count = len(self.recording_devices)
        if recording_count == 0:
            self.record_status_label.setText("录制状态: 无录制")
            self.record_status_label.setStyleSheet("color: gray; font-weight: bold;")
        else:
            recording_names = []
            for address in self.recording_devices.keys():
                if address in self.connected_devices:
                    recording_names.append(self.connected_devices[address].display_name)
            self.record_status_label.setText(f"正在录制({recording_count}): {', '.join(recording_names)}")
            self.record_status_label.setStyleSheet("color: red; font-weight: bold;")
    
    def update_data_display(self):
        """更新数据显示"""
        total_count = sum(self.device_data_counts.values())
        self.total_data_label.setText(f"总接收数据: {total_count} 条")
    
    def log_message(self, message):
        """记录日志消息"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        
        # 限制日志行数
        document = self.log_text.document()
        if document and document.blockCount() > 100:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, 10)
            cursor.removeSelectedText()
    
    def closeEvent(self, event):
        """关闭事件"""
        self.log_message("正在关闭IMU子进程...")
        
        # 停止IPC监听
        if hasattr(self, 'ipc_handler'):
            self.ipc_handler.stop_listening()
        
        # 清理IMU录制器
        if self.imu_recorder:
            self.imu_recorder.cleanup()
        
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 检查依赖
    try:
        import bleak
        import numpy
        import pyqtgraph
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请安装依赖: pip install bleak numpy pyqtgraph PyQt5")
        return
    
    # 创建并显示GUI
    gui = IMUSubprocessGUI()
    gui.show()
    
    # 运行应用
    sys.exit(app.exec_())


if __name__ == "__main__":
    main() 