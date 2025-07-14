"""
IMU通信协议处理器

负责IMU设备的通信协议解析和配置。
"""

from typing import Optional, Dict, Any

import numpy as np

from utils.logger import get_logger


class IMUProtocol:
    """IMU通信协议处理器"""
    
    # 特征UUID
    NOTIFICATION_CHARACTERISTIC = 0x0007
    WRITE_CHARACTERISTIC = 0x0005
    
    # 数据缩放因子
    SCALE_ACCEL = 0.00478515625      # 加速度 [-16g~+16g]    9.8*16/32768
    SCALE_ANGLE_SPEED = 0.06103515625  # 角速度 [-2000~+2000]    2000/32768
    SCALE_QUAT = 0.000030517578125   # 四元数 [-1~+1]         1/32768
    SCALE_ANGLE = 0.0054931640625    # 角度   [-180~+180]     180/32768
    SCALE_MAG = 0.15106201171875     # 磁场 [-4950~+4950]   4950/32768
    SCALE_TEMPERATURE = 0.01         # 温度
    SCALE_AIR_PRESSURE = 0.0002384185791  # 气压 [-2000~+2000]    2000/8388608
    SCALE_HEIGHT = 0.0010728836      # 高度 [-9000~+9000]    9000/8388608
    
    def __init__(self):
        """初始化协议处理器"""
        self.logger = get_logger("imu_protocol")
    
    @staticmethod
    def create_configuration_sequence(is_compass_on: int = 0,
                                      barometer_filter: int = 2,
                                      report_tag: int = 0x0FFF,
                                      report_rate: int = 60) -> list:
        """
        创建设备配置序列
        
        Args:
            is_compass_on (int): 是否使用磁场融合姿态
            barometer_filter (int): 气压计滤波系数
            report_tag (int): 功能订阅标识
            report_rate (int): 数据主动上报的传输帧率[取值0-250HZ]
            
        Returns:
            list: 配置命令序列
        """
        commands = []
        
        # 保持连接
        commands.append(bytes([0x29]))
        
        # 启用高速通信
        commands.append(bytes([0x46]))
        
        # 参数设置
        params = bytearray([0x00 for _ in range(11)])
        params[0] = 0x12
        params[1] = 5       # 静止状态加速度阈值
        params[2] = 255     # 静止归零速度(单位cm/s) 0:不归零 255:立即归零
        params[3] = 0       # 动态归零速度(单位cm/s) 0:不归零
        params[4] = ((barometer_filter & 3) << 1) | (is_compass_on & 1)
        params[5] = report_rate  # 数据主动上报的传输帧率[取值0-250HZ], 0表示0.5HZ
        params[6] = 1       # 陀螺仪滤波系数[取值0-2],数值越大越平稳但实时性越差
        params[7] = 3       # 加速计滤波系数[取值0-4],数值越大越平稳但实时性越差
        params[8] = 5       # 磁力计滤波系数[取值0-9],数值越大越平稳但实时性越差
        params[9] = report_tag & 0xff
        params[10] = (report_tag >> 8) & 0xff
        
        commands.append(bytes(params))
        
        # 启动数据上报
        commands.append(bytes([0x19]))
        
        return commands
    
    def parse_imu_data(self, buf: bytearray) -> Optional[Dict[str, Any]]:
        """
        解析IMU数据
        
        Args:
            buf (bytearray): 原始数据
            
        Returns:
            Optional[Dict[str, Any]]: 解析后的数据字典
        """
        if len(buf) < 7 or buf[0] != 0x11:
            self.logger.warning("无效的IMU数据包")
            return None
        
        try:
            # 解析控制字和时间戳
            ctl = (buf[2] << 8) | buf[1]
            timestamp = ((buf[6] << 24) | (buf[5] << 16) | (buf[4] << 8) | buf[3])
            
            data: Dict[str, Any] = {
                'timestamp': timestamp,
                'control': ctl
            }
            
            # 从第7字节开始解析数据
            L = 7
            
            # 线性加速度数据 (不含重力)
            if (ctl & 0x0001) != 0:
                if L + 6 <= len(buf):
                    ax = self._parse_int16_from_buffer(buf, L) * self.SCALE_ACCEL
                    ay = self._parse_int16_from_buffer(buf, L + 2) * self.SCALE_ACCEL
                    az = self._parse_int16_from_buffer(buf, L + 4) * self.SCALE_ACCEL
                    data['linear_accel'] = {'x': ax, 'y': ay, 'z': az}
                    L += 6
            
            # 含重力加速度数据
            if (ctl & 0x0002) != 0:
                if L + 6 <= len(buf):
                    ax = self._parse_int16_from_buffer(buf, L) * self.SCALE_ACCEL
                    ay = self._parse_int16_from_buffer(buf, L + 2) * self.SCALE_ACCEL
                    az = self._parse_int16_from_buffer(buf, L + 4) * self.SCALE_ACCEL
                    data['accel_with_gravity'] = {'x': ax, 'y': ay, 'z': az}
                    L += 6
            
            # 角速度数据
            if (ctl & 0x0004) != 0:
                if L + 6 <= len(buf):
                    gx = self._parse_int16_from_buffer(buf, L) * self.SCALE_ANGLE_SPEED
                    gy = self._parse_int16_from_buffer(buf, L + 2) * self.SCALE_ANGLE_SPEED
                    gz = self._parse_int16_from_buffer(buf, L + 4) * self.SCALE_ANGLE_SPEED
                    data['gyro'] = {'x': gx, 'y': gy, 'z': gz}
                    L += 6
            
            # 磁场数据
            if (ctl & 0x0008) != 0:
                if L + 6 <= len(buf):
                    mx = self._parse_int16_from_buffer(buf, L) * self.SCALE_MAG
                    my = self._parse_int16_from_buffer(buf, L + 2) * self.SCALE_MAG
                    mz = self._parse_int16_from_buffer(buf, L + 4) * self.SCALE_MAG
                    data['mag'] = {'x': mx, 'y': my, 'z': mz}
                    L += 6
            
            # 温度、气压、高度数据
            if (ctl & 0x0010) != 0:
                if L + 8 <= len(buf):
                    # 温度
                    temp = self._parse_int16_from_buffer(buf, L) * self.SCALE_TEMPERATURE
                    data['temperature'] = temp
                    L += 2
                    
                    # 气压 (24位)
                    pressure_raw = self._parse_int24_from_buffer(buf, L)
                    pressure = pressure_raw * self.SCALE_AIR_PRESSURE
                    data['pressure'] = pressure
                    L += 3
                    
                    # 高度 (24位)
                    height_raw = self._parse_int24_from_buffer(buf, L)
                    height = height_raw * self.SCALE_HEIGHT
                    data['height'] = height
                    L += 3
            
            # 四元数数据
            if (ctl & 0x0020) != 0:
                if L + 8 <= len(buf):
                    qw = self._parse_int16_from_buffer(buf, L) * self.SCALE_QUAT
                    qx = self._parse_int16_from_buffer(buf, L + 2) * self.SCALE_QUAT
                    qy = self._parse_int16_from_buffer(buf, L + 4) * self.SCALE_QUAT
                    qz = self._parse_int16_from_buffer(buf, L + 6) * self.SCALE_QUAT
                    data['quat'] = {'w': qw, 'x': qx, 'y': qy, 'z': qz}
                    L += 8
            
            # 角度数据
            if (ctl & 0x0040) != 0:
                if L + 6 <= len(buf):
                    roll = self._parse_int16_from_buffer(buf, L) * self.SCALE_ANGLE
                    pitch = self._parse_int16_from_buffer(buf, L + 2) * self.SCALE_ANGLE
                    yaw = self._parse_int16_from_buffer(buf, L + 4) * self.SCALE_ANGLE
                    data['angle'] = {'roll': roll, 'pitch': pitch, 'yaw': yaw}
                    L += 6
            
            # 位置偏移数据
            if (ctl & 0x0080) != 0:
                if L + 6 <= len(buf):
                    offset_x = self._parse_int16_from_buffer(buf, L) / 1000.0
                    offset_y = self._parse_int16_from_buffer(buf, L + 2) / 1000.0
                    offset_z = self._parse_int16_from_buffer(buf, L + 4) / 1000.0
                    data['offset'] = {'x': offset_x, 'y': offset_y, 'z': offset_z}
                    L += 6
            
            # 计步数据
            if (ctl & 0x0100) != 0:
                if L + 5 <= len(buf):
                    # 步数 (32位)
                    steps = ((buf[L+3] << 24) | (buf[L+2] << 16) | (buf[L+1] << 8) | buf[L])
                    data['steps'] = steps
                    L += 4
                    
                    # 运动状态
                    motion_state = buf[L]
                    data['motion'] = {
                        'walking': bool(motion_state & 0x01),
                        'running': bool(motion_state & 0x02),
                        'biking': bool(motion_state & 0x04),
                        'driving': bool(motion_state & 0x08)
                    }
                    L += 1
            
            # 高精度线性加速度数据 (备用)
            if (ctl & 0x0200) != 0:
                if L + 6 <= len(buf):
                    asx = self._parse_int16_from_buffer(buf, L) * self.SCALE_ACCEL
                    asy = self._parse_int16_from_buffer(buf, L + 2) * self.SCALE_ACCEL
                    asz = self._parse_int16_from_buffer(buf, L + 4) * self.SCALE_ACCEL
                    data['high_precision_linear_accel'] = {'x': asx, 'y': asy, 'z': asz}
                    L += 6
            
            # ADC数据
            if (ctl & 0x0400) != 0:
                if L + 2 <= len(buf):
                    adc_value = ((buf[L+1] << 8) | buf[L])
                    data['adc'] = adc_value  # 单位: mV
                    L += 2
            
            # GPIO数据
            if (ctl & 0x0800) != 0:
                if L + 1 <= len(buf):
                    gpio_value = buf[L]
                    data['gpio'] = {
                        'mode': (gpio_value >> 4) & 0x0f,
                        'value': gpio_value & 0x0f
                    }
                    L += 1
            
            return data
        
        except Exception as e:
            self.logger.error(f"解析IMU数据时发生错误: {e}")
            return None
    
    def _parse_int16_from_buffer(self, buf: bytearray, offset: int) -> int:
        """
        从缓冲区解析16位有符号整数
        
        Args:
            buf (bytearray): 数据缓冲区
            offset (int): 偏移量
            
        Returns:
            int: 解析后的整数
        """
        if offset + 1 >= len(buf):
            return 0
        
        # 小端序解析
        value = (buf[offset + 1] << 8) | buf[offset]
        
        # 转换为有符号整数
        if value >= 32768:
            value -= 65536
        
        return value
    
    def _parse_int24_from_buffer(self, buf: bytearray, offset: int) -> int:
        """
        从缓冲区解析24位有符号整数
        
        Args:
            buf (bytearray): 数据缓冲区
            offset (int): 偏移量
            
        Returns:
            int: 解析后的整数
        """
        if offset + 2 >= len(buf):
            return 0
        
        # 小端序解析24位数据
        value = (buf[offset + 2] << 16) | (buf[offset + 1] << 8) | buf[offset]
        
        # 如果最高位为1，则为负数，需要扩展为32位负数
        if (value & 0x800000) == 0x800000:
            value = value | 0xff000000
        
        return int(np.int32(value)) 