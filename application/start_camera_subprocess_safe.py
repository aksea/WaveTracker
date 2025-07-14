#!/usr/bin/env python3
"""
安全的摄像头子进程启动器

包含自动重启机制，用于处理macOS TSM错误导致的应用卡顿
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from utils.logger import get_logger

class SafeCameraSubprocessLauncher:
    """安全的摄像头子进程启动器"""
    
    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        self.logger = get_logger(f"camera_launcher_{instance_id}")
        self.process = None
        self.restart_count = 0
        self.max_restarts = 5
        self.restart_delay = 2.0
        self.running = True
        
        # 设置信号处理器
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"接收到信号 {signum}，正在关闭...")
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
    
    def start_subprocess(self):
        """启动子进程"""
        try:
            script_path = Path(__file__).parent / "gui_camera_subprocess.py"
            cmd = [sys.executable, str(script_path), self.instance_id]
            
            # 设置环境变量
            env = os.environ.copy()
            env['QT_IM_MODULE'] = ''
            env['XMODIFIERS'] = ''
            env['GTK_IM_MODULE'] = ''
            env['QT_MAC_WANTS_LAYER'] = '1'
            env['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
            
            self.process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            self.logger.info(f"摄像头子进程 {self.instance_id} 启动成功，PID: {self.process.pid}")
            return True
            
        except Exception as e:
            self.logger.error(f"启动摄像头子进程失败: {e}")
            return False
    
    def monitor_subprocess(self):
        """监控子进程"""
        while self.running:
            if not self.process:
                break
                
            # 检查进程状态
            poll_result = self.process.poll()
            
            if poll_result is not None:
                # 进程已退出
                stdout, stderr = self.process.communicate()
                
                if poll_result == 0:
                    self.logger.info(f"摄像头子进程 {self.instance_id} 正常退出")
                    break
                else:
                    self.logger.error(f"摄像头子进程 {self.instance_id} 异常退出，退出码: {poll_result}")
                    
                    # 检查是否是TSM错误
                    if "TSM" in stderr or "AdjustCapsLockLED" in stderr:
                        self.logger.warning("检测到TSM错误，准备重启子进程")
                    
                    # 检查是否需要重启
                    if self.restart_count < self.max_restarts and self.running:
                        self.restart_count += 1
                        self.logger.info(f"准备重启子进程 ({self.restart_count}/{self.max_restarts})")
                        
                        time.sleep(self.restart_delay)
                        
                        if self.start_subprocess():
                            self.logger.info("子进程重启成功")
                            continue
                        else:
                            self.logger.error("子进程重启失败")
                            break
                    else:
                        self.logger.error("达到最大重启次数或被要求停止")
                        break
            
            time.sleep(1)
    
    def run(self):
        """运行启动器"""
        self.logger.info(f"启动摄像头子进程监控器 - {self.instance_id}")
        
        # 启动初始进程
        if not self.start_subprocess():
            self.logger.error("初始进程启动失败")
            return 1
        
        # 监控进程
        self.monitor_subprocess()
        
        # 清理
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        
        self.logger.info("摄像头子进程监控器已退出")
        return 0


def main():
    """主函数"""
    # 获取实例ID
    if len(sys.argv) > 1:
        instance_id = sys.argv[1]
    else:
        instance_id = 'camera_1'
    
    # 创建启动器
    launcher = SafeCameraSubprocessLauncher(instance_id)
    
    # 运行
    exit_code = launcher.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main() 