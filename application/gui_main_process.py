#!/usr/bin/env python3
"""
主进程GUI - 多进程数据采集系统

管理IMU和摄像头子进程，提供统一的志愿者姓名管理和录制控制
支持子进程的启动、关闭和状态监控
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
                             QGroupBox, QGridLayout, QSpinBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from utils.config_manager import get_config_manager
from core.multiprocessing.process_manager import ProcessManager, ProcessStatus, ProcessInfo


# 状态映射字典
STATUS_DISPLAY_MAP = {
    ProcessStatus.STOPPED: "已停止",
    ProcessStatus.STARTING: "启动中",
    ProcessStatus.RUNNING: "运行中",
    ProcessStatus.STOPPING: "停止中",
    ProcessStatus.ERROR: "错误"
}


class ProcessStatusWidget(QWidget):
    """进程状态显示组件"""
    
    def __init__(self, process_info: ProcessInfo, process_manager: ProcessManager):
        super().__init__()
        self.process_info = process_info
        self.process_manager = process_manager
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout()
        self.setLayout(layout)
        
        # 状态指示器
        self.status_indicator = QLabel("●")
        self.status_indicator.setFixedSize(20, 20)
        self.status_indicator.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_indicator)
        
        # 进程名称
        self.name_label = QLabel(self.process_info.process_id)
        self.name_label.setMinimumWidth(80)
        layout.addWidget(self.name_label)
        
        # 状态文本
        self.state_label = QLabel(STATUS_DISPLAY_MAP[ProcessStatus.STOPPED])
        self.state_label.setMinimumWidth(60)
        layout.addWidget(self.state_label)
        
        # 控制按钮
        self.start_button = QPushButton("启动")
        self.start_button.setFixedSize(60, 30)
        self.start_button.clicked.connect(self.start_process)
        layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("停止")
        self.stop_button.setFixedSize(60, 30)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_process)
        layout.addWidget(self.stop_button)
        
        self.update_display()
    
    def start_process(self):
        """启动进程"""
        self.process_manager.start_process(self.process_info.process_id)
    
    def stop_process(self):
        """停止进程"""
        self.process_manager.stop_process(self.process_info.process_id)
    
    def update_display(self):
        """更新显示"""
        # 获取最新的进程信息
        current_info = self.process_manager.get_process_info(self.process_info.process_id)
        if not current_info:
            return
        
        # 更新状态文本
        status_text = STATUS_DISPLAY_MAP.get(current_info.status, "未知")
        self.state_label.setText(status_text)
        
        # 更新状态指示器颜色
        color_map = {
            ProcessStatus.STOPPED: "gray",
            ProcessStatus.STARTING: "orange",
            ProcessStatus.RUNNING: "green",
            ProcessStatus.STOPPING: "orange",
            ProcessStatus.ERROR: "red"
        }
        
        color = color_map.get(current_info.status, "gray")
        self.status_indicator.setStyleSheet(f"color: {color}; font-weight: bold;")
        
        # 更新按钮状态
        is_running = current_info.status == ProcessStatus.RUNNING
        self.start_button.setEnabled(not is_running)
        self.stop_button.setEnabled(is_running)


class MainProcessGUI(QMainWindow):
    """主进程GUI"""
    
    def __init__(self):
        super().__init__()
        self.config_manager = get_config_manager()
        self.process_manager = ProcessManager(log_callback=self.log_message)
        self.volunteer_name = ""
        self.process_widgets: Dict[str, ProcessStatusWidget] = {}
        
        self.init_ui()
        self.setup_connections()
        
        # 在UI初始化完成后加载进程配置
        self.load_process_config()
        self.apply_process_config()
        
        # 启动状态监控定时器
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.monitor_processes)
        self.monitor_timer.start(1000)  # 每秒检查一次
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("多进程数据采集系统 - 主控制台")
        self.setGeometry(100, 100, 800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # 志愿者信息组
        volunteer_group = QGroupBox("志愿者信息")
        volunteer_layout = QHBoxLayout()
        volunteer_group.setLayout(volunteer_layout)
        
        volunteer_layout.addWidget(QLabel("志愿者姓名:"))
        self.volunteer_input = QLineEdit()
        self.volunteer_input.setPlaceholderText("请输入志愿者姓名")
        self.volunteer_input.textChanged.connect(self.on_volunteer_name_changed)
        volunteer_layout.addWidget(self.volunteer_input)
        
        self.sync_button = QPushButton("同步到所有子进程")
        self.sync_button.clicked.connect(self.sync_volunteer_name)
        self.sync_button.setEnabled(False)
        volunteer_layout.addWidget(self.sync_button)
        
        main_layout.addWidget(volunteer_group)
        
        # 进程配置组
        config_group = QGroupBox("进程配置")
        config_layout = QGridLayout()
        config_group.setLayout(config_layout)
        
        # IMU进程数量配置
        config_layout.addWidget(QLabel("IMU进程数量:"), 0, 0)
        self.imu_count_spin = QSpinBox()
        self.imu_count_spin.setRange(0, 10)
        self.imu_count_spin.setValue(1)
        self.imu_count_spin.valueChanged.connect(self.on_process_count_changed)
        config_layout.addWidget(self.imu_count_spin, 0, 1)
        
        # 摄像头进程数量配置
        config_layout.addWidget(QLabel("摄像头进程数量:"), 0, 2)
        self.camera_count_spin = QSpinBox()
        self.camera_count_spin.setRange(0, 10)
        self.camera_count_spin.setValue(1)
        self.camera_count_spin.valueChanged.connect(self.on_process_count_changed)
        config_layout.addWidget(self.camera_count_spin, 0, 3)
        
        # 应用配置按钮
        self.apply_config_button = QPushButton("应用配置")
        self.apply_config_button.clicked.connect(self.apply_process_config)
        config_layout.addWidget(self.apply_config_button, 0, 4)
        
        main_layout.addWidget(config_group)
        
        # 进程管理组
        process_group = QGroupBox("进程管理")
        process_layout = QVBoxLayout()
        process_group.setLayout(process_layout)
        
        # 进程状态显示容器
        self.process_status_widget = QWidget()
        self.process_status_layout = QVBoxLayout()
        self.process_status_widget.setLayout(self.process_status_layout)
        process_layout.addWidget(self.process_status_widget)
        
        # 全局控制按钮
        global_control_layout = QHBoxLayout()
        
        self.start_all_button = QPushButton("启动所有进程")
        self.start_all_button.clicked.connect(self.start_all_processes)
        global_control_layout.addWidget(self.start_all_button)
        
        self.stop_all_button = QPushButton("停止所有进程")
        self.stop_all_button.clicked.connect(self.stop_all_processes)
        global_control_layout.addWidget(self.stop_all_button)
        
        process_layout.addLayout(global_control_layout)
        
        main_layout.addWidget(process_group)
        
        # 录制控制组
        record_group = QGroupBox("录制控制")
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
        
        main_layout.addWidget(record_group)
        
        # 数据路径显示
        path_group = QGroupBox("数据路径")
        path_layout = QVBoxLayout()
        path_group.setLayout(path_layout)
        
        self.data_path_label = QLabel("请先输入志愿者姓名")
        self.data_path_label.setWordWrap(True)
        self.data_path_label.setStyleSheet("background-color: #f0f0f0; padding: 10px; border: 1px solid #ccc;")
        path_layout.addWidget(self.data_path_label)
        
        main_layout.addWidget(path_group)
        
        # 日志区域
        log_group = QGroupBox("系统日志")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        
        self.log_text = QTextEdit()
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        main_layout.addWidget(log_group)
    
    def setup_connections(self):
        """设置信号连接"""
        # 新的ProcessManager不需要Qt信号连接
        pass
    
    def on_volunteer_name_changed(self):
        """志愿者姓名变更回调"""
        self.volunteer_name = self.volunteer_input.text().strip()
        
        if self.volunteer_name:
            # 生成数据保存路径
            base_path = Path(__file__).parent.parent / "data" / self.volunteer_name
            self.data_path_label.setText(f"数据保存路径: {base_path}")
            self.data_path_label.setStyleSheet("background-color: white; padding: 10px; border: 1px solid #ccc;")
            self.sync_button.setEnabled(True)
        else:
            self.data_path_label.setText("请先输入志愿者姓名")
            self.data_path_label.setStyleSheet("background-color: #f0f0f0; padding: 10px; border: 1px solid #ccc;")
            self.sync_button.setEnabled(False)
        
        # 更新录制按钮状态
        self.update_record_buttons()
    
    def sync_volunteer_name(self):
        """同步志愿者姓名到所有子进程"""
        if self.volunteer_name:
            self.process_manager.sync_volunteer_name(self.volunteer_name)
            self.log_message(f"已同步志愿者姓名 '{self.volunteer_name}' 到所有子进程")
            # 同步后也需要更新录制按钮状态
            self.update_record_buttons()
    
    def on_process_count_changed(self):
        """进程数量变化回调"""
        # 当数量改变时，提示用户应用配置
        self.apply_config_button.setStyleSheet("background-color: #ffeb3b; font-weight: bold;")
        self.apply_config_button.setText("应用配置 (有更改)")
    
    def apply_process_config(self):
        """应用进程配置"""
        imu_count = self.imu_count_spin.value()
        camera_count = self.camera_count_spin.value()
        
        # 保存配置到ProcessManager
        self.process_manager.save_process_config(imu_count, camera_count)
        
        # 重新加载进程配置
        self.process_manager.load_process_config()
        
        # 清除现有的进程状态组件
        self.clear_process_widgets()
        
        # 创建新的进程状态组件
        self.create_process_widgets()
        
        # 重置按钮样式
        self.apply_config_button.setStyleSheet("")
        self.apply_config_button.setText("应用配置")
        
        self.log_message(f"已应用进程配置: IMU进程={imu_count}, 摄像头进程={camera_count}")
    
    def clear_process_widgets(self):
        """清除现有的进程状态组件"""
        # 清除布局中的所有组件
        while self.process_status_layout.count():
            child = self.process_status_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # 清空进程组件字典
        self.process_widgets.clear()
    
    def create_process_widgets(self):
        """创建进程状态组件"""
        # 获取进程列表
        process_list = self.process_manager.get_process_list()
        
        # 按类型分组
        imu_processes = [p for p in process_list if p.process_type == "imu"]
        camera_processes = [p for p in process_list if p.process_type == "camera"]
        
        # 创建IMU进程组件
        if imu_processes:
            imu_group = QGroupBox(f"IMU进程 ({len(imu_processes)}个)")
            imu_layout = QVBoxLayout()
            imu_group.setLayout(imu_layout)
            
            for process_info in imu_processes:
                widget = ProcessStatusWidget(process_info, self.process_manager)
                self.process_widgets[process_info.process_id] = widget
                imu_layout.addWidget(widget)
            
            self.process_status_layout.addWidget(imu_group)
        
        # 创建摄像头进程组件
        if camera_processes:
            camera_group = QGroupBox(f"摄像头进程 ({len(camera_processes)}个)")
            camera_layout = QVBoxLayout()
            camera_group.setLayout(camera_layout)
            
            for process_info in camera_processes:
                widget = ProcessStatusWidget(process_info, self.process_manager)
                self.process_widgets[process_info.process_id] = widget
                camera_layout.addWidget(widget)
            
            self.process_status_layout.addWidget(camera_group)
    

    
    def load_process_config(self):
        """加载进程配置"""
        try:
            # 从配置管理器加载进程配置
            process_counts = self.config_manager.get_process_counts()
            
            # 设置控件值
            self.imu_count_spin.setValue(process_counts.get("imu_count", 1))
            self.camera_count_spin.setValue(process_counts.get("camera_count", 1))
            
            # 加载ProcessManager的配置
            self.process_manager.load_process_config()
            
            self.log_message("进程配置已加载")
        except Exception as e:
            self.log_message(f"加载进程配置失败: {e}")
            # 使用默认配置
            self.imu_count_spin.setValue(1)
            self.camera_count_spin.setValue(1)
    
    def start_all_processes(self):
        """启动所有进程"""
        success = self.process_manager.start_all_processes()
        if success:
            self.log_message("所有进程启动成功")
        else:
            self.log_message("部分进程启动失败")
    
    def stop_all_processes(self):
        """停止所有进程"""
        success = self.process_manager.stop_all_processes()
        if success:
            self.log_message("所有进程已停止")
        else:
            self.log_message("部分进程停止失败")
    
    def start_recording_all(self):
        """开始录制所有"""
        if not self.volunteer_name:
            self.log_message("请先输入志愿者姓名")
            return
        
        success = self.process_manager.start_recording()
        if success:
            self.log_message("已发送开始录制命令到所有子进程")
        else:
            self.log_message("发送开始录制命令失败")
    
    def stop_recording_all(self):
        """停止录制所有"""
        success = self.process_manager.stop_recording()
        if success:
            self.log_message("已发送停止录制命令到所有子进程")
        else:
            self.log_message("发送停止录制命令失败")
    
    def update_record_buttons(self):
        """更新录制按钮状态"""
        # 检查是否有运行中的进程
        summary = self.process_manager.get_process_status_summary()
        has_running_process = summary["running"] > 0
        
        # 只有在有运行进程且输入了志愿者姓名时才启用录制按钮
        enable_record = has_running_process and bool(self.volunteer_name)
        self.start_record_button.setEnabled(enable_record)
        self.stop_record_button.setEnabled(enable_record)
    
    def monitor_processes(self):
        """监控进程状态"""
        # 监控ProcessManager中的进程状态
        self.process_manager.monitor_processes()
        
        # 更新UI显示
        for process_id, widget in self.process_widgets.items():
            widget.update_display()
    
    def log_message(self, message: str):
        """记录日志消息"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        
        # 限制日志行数
        document = self.log_text.document()
        if document and document.blockCount() > 200:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, 20)
            cursor.removeSelectedText()
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.log_message("正在关闭主进程...")
        
        # 停止监控定时器
        if hasattr(self, 'monitor_timer'):
            self.monitor_timer.stop()
        
        # 清理所有子进程
        self.process_manager.cleanup()
        
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = MainProcessGUI()
    window.show()
    
    # 运行应用
    sys.exit(app.exec_())


if __name__ == "__main__":
    main() 