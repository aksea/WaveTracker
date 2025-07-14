import json
import sys
import threading

from PyQt5.QtCore import QObject, pyqtSignal


class IPCHandler(QObject):
    """进程间通信处理器"""

    # 信号定义
    volunteer_name_received = pyqtSignal(str)
    start_recording_received = pyqtSignal()
    stop_recording_received = pyqtSignal()
    stop_process_received = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = True
        self.input_thread = None
        self.start_listening()

    def start_listening(self):
        """开始监听标准输入"""
        self.input_thread = threading.Thread(target=self._listen_stdin, daemon=True)
        self.input_thread.start()

    def _listen_stdin(self):
        """监听标准输入的线程函数"""
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                line = line.strip()
                if line:
                    self._process_message(line)
            except Exception as e:
                print(f"IPC处理错误: {e}", file=sys.stderr)

    def _process_message(self, message: str):
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            command = data.get("command")

            if command == "sync_volunteer_name":
                volunteer_name = data.get("data", {}).get("volunteer_name", "")
                self.volunteer_name_received.emit(volunteer_name)
            elif command == "start_recording":
                self.start_recording_received.emit()
            elif command == "stop_recording":
                self.stop_recording_received.emit()
            elif command == "stop":
                self.stop_process_received.emit()
        except json.JSONDecodeError:
            print(f"无效的JSON消息: {message}", file=sys.stderr)
        except Exception as e:
            print(f"处理消息时出错: {e}", file=sys.stderr)

    def stop_listening(self):
        """停止监听"""
        self.running = False