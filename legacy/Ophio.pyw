#!/usr/bin/env python3
"""
屏幕共享控制端启动器
整合 screen_capture.py 和启动管理功能
"""

import os
import sys
import socket
import subprocess
import time
import platform
import threading
import queue
import atexit
import signal
from typing import Optional, Tuple, List
import psutil

# 导入 PyQt5
try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QLabel, QPushButton, QTextEdit, 
                                 QMessageBox, QGroupBox, QSpinBox, QCheckBox, QFrame)
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize
    from PyQt5.QtGui import QFont, QIcon, QTextCursor, QPixmap, QImage
    from PyQt5.QtGui import QDesktopServices
    from PyQt5.QtCore import QUrl
    PYQT_AVAILABLE = True
except ImportError as e:
    PYQT_AVAILABLE = False
    print(f"注意: 需要 PyQt5 来使用图形界面: {e}")
    print("请运行: pip install PyQt5")

# 系统托盘
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError as e:
    TRAY_AVAILABLE = False
    print(f"注意: 系统托盘功能需要 pystray 和 Pillow 库: {e}")
    print("请运行: pip install pystray pillow")

# QR 码库
try:
    import qrcode
    import qrcode.image.pil
    QRCODE_AVAILABLE = True
except ImportError as e:
    QRCODE_AVAILABLE = False
    print(f"注意: QR 码功能需要 qrcode 库: {e}")
    print("请运行: pip install qrcode[pil]")


class ScreenCaptureThread(QThread):
    """运行屏幕捕获进程的线程"""
    output_received = pyqtSignal(str)
    process_finished = pyqtSignal(int)
    
    def __init__(self, host="127.0.0.1", port=8889):
        super().__init__()
        self.host = host
        self.port = port
        self.process = None
        self.running = False
        self.encoding = 'utf-8'
        self.child_processes = []  # 存储子进程ID
        
    def run(self):
        """运行屏幕捕获进程"""
        self.running = True
        
        try:
            # 设置环境变量
            env = os.environ.copy()
            if platform.system().lower() == 'windows':
                env['PYTHONIOENCODING'] = 'utf-8'
            
            # 启动屏幕捕获
            self.process = subprocess.Popen(
                [sys.executable, 'screen_capture.py'],
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env
            )
            
            # 记录主进程ID
            main_pid = self.process.pid
            self.log_message(f"主进程已启动，PID: {main_pid}")
            
            # 读取输出
            while self.running and self.process and self.process.poll() is None:
                try:
                    # 尝试读取一行
                    line = self.process.stdout.readline()
                    if line:
                        # 尝试解码
                        try:
                            text = line.decode(self.encoding)
                        except UnicodeDecodeError:
                            try:
                                text = line.decode('gbk', errors='replace')
                            except:
                                text = line.decode('utf-8', errors='replace')
                        
                        self.output_received.emit(text.rstrip())
                except (AttributeError, ValueError, OSError):
                    break
            
            # 进程结束
            if self.process:
                return_code = self.process.wait()
                self.process_finished.emit(return_code)
                
        except Exception as e:
            self.output_received.emit(f"启动屏幕捕获时出错: {str(e)}")
        finally:
            self.running = False
            self.child_processes.clear()
    
    def log_message(self, message):
        """线程安全的日志记录"""
        self.output_received.emit(f"[进程管理] {message}")
    
    def stop(self):
        """停止进程 - 直接强制结束，不等待"""
        self.running = False
        
        if not self.process:
            return
            
        self.log_message("正在强制结束屏幕捕获进程...")
        
        try:
            # 获取主进程PID
            main_pid = self.process.pid
            
            # 强制终止进程树
            if platform.system().lower() == 'windows':
                # Windows: 强制终止整个进程树
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(main_pid)], 
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
            else:
                # Linux/Mac: 强制终止进程
                subprocess.run(['pkill', '-9', '-P', str(main_pid)], 
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
                subprocess.run(['kill', '-9', str(main_pid)], 
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
            
            self.log_message(f"已强制结束进程树，主进程PID: {main_pid}")
            
        except subprocess.TimeoutExpired:
            self.log_message("强制结束进程时超时")
        except Exception as e:
            self.log_message(f"强制结束进程时出错: {e}")
        finally:
            # 清理进程对象
            try:
                if self.process and self.process.poll() is None:
                    self.process.terminate()
            except:
                pass
                
            self.process = None
            self.child_processes.clear()


class ServerThread(QThread):
    """运行Node.js服务器的线程"""
    output_received = pyqtSignal(str)
    process_finished = pyqtSignal(int)
    
    def __init__(self, port=8888):
        super().__init__()
        self.port = port
        self.process = None
        self.running = False
        self.encoding = 'utf-8'
        
    def run(self):
        """运行Node.js服务器"""
        self.running = True
        
        try:
            # 设置环境变量
            env = os.environ.copy()
            if platform.system().lower() == 'windows':
                env['PYTHONIOENCODING'] = 'utf-8'
            
            # 启动Node.js服务器
            self.process = subprocess.Popen(
                ['node', 'server.js'],
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env
            )
            
            # 记录主进程ID
            main_pid = self.process.pid
            self.log_message(f"Node.js服务器已启动，PID: {main_pid}")
            
            # 读取输出
            while self.running and self.process and self.process.poll() is None:
                try:
                    # 尝试读取一行
                    line = self.process.stdout.readline()
                    if line:
                        # 尝试解码
                        try:
                            text = line.decode(self.encoding)
                        except UnicodeDecodeError:
                            try:
                                text = line.decode('gbk', errors='replace')
                            except:
                                text = line.decode('utf-8', errors='replace')
                        
                        self.output_received.emit(text.rstrip())
                except (AttributeError, ValueError, OSError):
                    break
            
            # 进程结束
            if self.process:
                return_code = self.process.wait()
                self.process_finished.emit(return_code)
                
        except Exception as e:
            self.output_received.emit(f"启动Node.js服务器时出错: {str(e)}")
        finally:
            self.running = False
    
    def log_message(self, message):
        """线程安全的日志记录"""
        self.output_received.emit(f"[服务器管理] {message}")
    
    def stop(self):
        """停止进程"""
        self.running = False
        
        if not self.process:
            return
            
        self.log_message("正在强制结束Node.js服务器进程...")
        
        try:
            # 获取主进程PID
            main_pid = self.process.pid
            
            # 强制终止进程树
            if platform.system().lower() == 'windows':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(main_pid)], 
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
            else:
                subprocess.run(['pkill', '-9', '-P', str(main_pid)], 
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
                subprocess.run(['kill', '-9', str(main_pid)], 
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
            
            self.log_message(f"已强制结束进程树，主进程PID: {main_pid}")
            
        except subprocess.TimeoutExpired:
            self.log_message("强制结束进程时超时")
        except Exception as e:
            self.log_message(f"强制结束进程时出错: {e}")
        finally:
            try:
                if self.process and self.process.poll() is None:
                    self.process.terminate()
            except:
                pass
            self.process = None


class ScreenControlLauncher(QMainWindow):
    """屏幕共享控制端主窗口"""
    
    # 定义信号用于线程间通信
    show_window_signal = pyqtSignal()
    log_message_signal = pyqtSignal(str)
    update_status_signal = pyqtSignal(str)
    quit_app_signal = pyqtSignal()  # 新增：退出应用的信号
    
    def __init__(self):
        super().__init__()
        self.http_port = 8888
        self.ws_port = 8889
        self.server_thread = None
        self.screen_thread = None
        self.tray_icon = None
        self.tray_thread = None
        self.is_minimized_to_tray = False
        self.server_running = False
        self.screen_capture_running = False
        self.local_ip = self.get_local_ip()
        self.auto_refresh_timer = QTimer()  # 自动刷新定时器
        self.auto_refresh_timer.timeout.connect(self.auto_refresh_ip)
        self.auto_refresh_interval = 30000  # 默认30秒刷新一次
        self.auto_refresh_enabled = False  # 是否启用自动刷新
        
        # 连接信号和槽
        self.show_window_signal.connect(self._show_window_slot)
        self.log_message_signal.connect(self._log_message_slot)
        self.update_status_signal.connect(self._update_status_slot)
        self.quit_app_signal.connect(self.quit_application)  # 连接退出信号
        
        self.init_ui()
        self.create_tray_icon()
        
    def get_local_ip(self):
        """获取本机IP地址"""
        try:
            # 创建一个临时的socket连接
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                # 如果上述方法失败，尝试获取主机名
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
                return ip
            except Exception:
                return "127.0.0.1"  # 返回默认本地地址
        
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle('Ophio')
        self.setMinimumSize(900, 1150)  # 设置为最小大小而不是固定大小
        
        # 设置窗口图标
        try:
            self.setWindowIcon(QIcon('icon.ico'))
        except:
            pass
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)  # 增加边距
        
        # 标题
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        
        # 配置区域
        config_group = QGroupBox("配置选项")
        config_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #3498db;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        config_layout = QVBoxLayout()
        config_layout.setSpacing(15)
        
        # 端口配置
        port_layout = QHBoxLayout()
        port_layout.setSpacing(10)
        
        http_port_layout = QHBoxLayout()
        http_port_label = QLabel('HTTP端口:')
        http_port_label.setFont(QFont("Arial", 10))
        self.http_port_input = QSpinBox()
        self.http_port_input.setRange(1, 65535)
        self.http_port_input.setValue(8888)
        self.http_port_input.setFixedWidth(100)
        self.http_port_input.valueChanged.connect(self.on_http_port_changed)
        http_port_layout.addWidget(http_port_label)
        http_port_layout.addWidget(self.http_port_input)
        http_port_layout.addStretch()
        
        ws_port_layout = QHBoxLayout()
        ws_port_label = QLabel('WebSocket端口:')
        ws_port_label.setFont(QFont("Arial", 10))
        self.ws_port_input = QSpinBox()
        self.ws_port_input.setRange(1, 65535)
        self.ws_port_input.setValue(8889)
        self.ws_port_input.setFixedWidth(100)
        self.ws_port_input.valueChanged.connect(self.on_ws_port_changed)
        ws_port_layout.addWidget(ws_port_label)
        ws_port_layout.addWidget(self.ws_port_input)
        ws_port_layout.addStretch()
        
        port_layout.addLayout(http_port_layout)
        port_layout.addLayout(ws_port_layout)
        config_layout.addLayout(port_layout)
        
        # 选项
        options_layout = QHBoxLayout()
        options_layout.setSpacing(20)
        self.auto_refresh_check = QCheckBox('自动刷新IP和QR码')
        self.auto_refresh_check.setChecked(True)
        self.auto_refresh_check.stateChanged.connect(self.on_auto_refresh_changed)
        options_layout.addWidget(self.auto_refresh_check)
        options_layout.addStretch()
        config_layout.addLayout(options_layout)
        
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)
        
        # 服务器信息区域 - 初始隐藏
        self.server_group = QGroupBox("访问信息")
        self.server_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #2ecc71;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        self.server_group.hide()  # 初始隐藏
        
        server_layout = QVBoxLayout()
        server_layout.setSpacing(15)
        
        # 连接提示
        self.connection_note = QLabel("📱 请在手机浏览器中访问以下链接，确保设备连接到同一网络")
        self.connection_note.setFont(QFont("Arial", 9))
        self.connection_note.setStyleSheet("color: #2c3e50; background-color: #e8f4fd; padding: 8px; border-radius: 4px;")
        self.connection_note.setWordWrap(True)
        server_layout.addWidget(self.connection_note)
        
        # 链接和QR码区域
        link_qrcode_layout = QHBoxLayout()
        link_qrcode_layout.setSpacing(20)
        
        # 左侧：链接信息
        link_layout = QVBoxLayout()
        link_layout.setSpacing(10)
        
        # 服务器地址标题
        server_info_label = QLabel("访问地址:")
        server_info_font = QFont()
        server_info_font.setPointSize(11)
        server_info_font.setBold(True)
        server_info_label.setFont(server_info_font)
        server_info_label.setStyleSheet("color: #2980b9;")
        link_layout.addWidget(server_info_label)
        
        # 本地链接
        local_layout = QVBoxLayout()
        local_title = QLabel("本地访问:")
        local_title.setFont(QFont("Arial", 9, QFont.Bold))
        local_layout.addWidget(local_title)
        
        self.local_link_label = QLabel("http://localhost:8888")
        self.local_link_label.setFont(QFont("Arial", 10))
        self.local_link_label.setStyleSheet("""
            QLabel {
                color: #3498db;
                background-color: #f8f9fa;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        """)
        self.local_link_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.local_link_label.setWordWrap(True)
        self.local_link_label.setCursor(Qt.PointingHandCursor)
        local_layout.addWidget(self.local_link_label)
        link_layout.addLayout(local_layout)
        
        # 网络链接
        network_layout = QVBoxLayout()
        network_title = QLabel("网络访问:")
        network_title.setFont(QFont("Arial", 9, QFont.Bold))
        network_layout.addWidget(network_title)
        
        self.network_link_label = QLabel("http://192.168.1.100:8888")
        self.network_link_label.setFont(QFont("Arial", 10))
        self.network_link_label.setStyleSheet("""
            QLabel {
                color: #3498db;
                background-color: #f8f9fa;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        """)
        self.network_link_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.network_link_label.setWordWrap(True)
        self.network_link_label.setCursor(Qt.PointingHandCursor)
        network_layout.addWidget(self.network_link_label)
        link_layout.addLayout(network_layout)
        
        # 复制按钮布局
        copy_buttons_layout = QHBoxLayout()
        copy_buttons_layout.setSpacing(10)
        
        self.copy_local_btn = QPushButton("复制本地链接")
        self.copy_local_btn.clicked.connect(self.copy_local_link)
        self.copy_local_btn.setFixedHeight(35)
        
        self.copy_network_btn = QPushButton("复制网络链接")
        self.copy_network_btn.clicked.connect(self.copy_network_link)
        self.copy_network_btn.setFixedHeight(35)
        
        self.refresh_btn = QPushButton("手动刷新 IP")
        self.refresh_btn.clicked.connect(self.refresh_server_info)
        self.refresh_btn.setFixedHeight(35)
        self.refresh_btn.setStyleSheet("background-color: #3498db; color: white;")
        
        copy_buttons_layout.addWidget(self.copy_local_btn)
        copy_buttons_layout.addWidget(self.copy_network_btn)
        copy_buttons_layout.addWidget(self.refresh_btn)
        
        link_layout.addLayout(copy_buttons_layout)
        link_layout.addStretch()
        
        # 右侧：QR码
        qrcode_layout = QVBoxLayout()
        qrcode_layout.setAlignment(Qt.AlignCenter)
        qrcode_layout.setSpacing(10)
        
        qrcode_title = QLabel("手机扫描访问")
        qrcode_title.setFont(QFont("Arial", 10, QFont.Bold))
        qrcode_title.setAlignment(Qt.AlignCenter)
        qrcode_title.setStyleSheet("color: #2c3e50;")
        qrcode_layout.addWidget(qrcode_title)
        
        self.qrcode_label = QLabel("QR码")
        self.qrcode_label.setAlignment(Qt.AlignCenter)
        self.qrcode_label.setFixedSize(220, 220)
        self.qrcode_label.setStyleSheet("""
            QLabel {
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                background-color: white;
                padding: 10px;
            }
        """)
        
        qrcode_layout.addWidget(self.qrcode_label)
        
        # QR码操作按钮
        qrcode_buttons_layout = QHBoxLayout()
        qrcode_buttons_layout.setSpacing(10)
        
        self.save_qrcode_btn = QPushButton("保存QR码")
        self.save_qrcode_btn.clicked.connect(self.save_qrcode_image)
        self.save_qrcode_btn.setFixedHeight(35)
        self.save_qrcode_btn.setStyleSheet("background-color: #27ae60; color: white;")
        
        qrcode_buttons_layout.addWidget(self.save_qrcode_btn)
        qrcode_layout.addLayout(qrcode_buttons_layout)
        
        # 将左右两侧布局添加到服务器布局
        link_qrcode_layout.addLayout(link_layout, 1)
        link_qrcode_layout.addLayout(qrcode_layout, 0)
        
        server_layout.addLayout(link_qrcode_layout)
        self.server_group.setLayout(server_layout)
        main_layout.addWidget(self.server_group)
        
        # 控制按钮区域
        control_group = QGroupBox("控制面板")
        control_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #f39c12;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        control_layout = QVBoxLayout()
        control_layout.setSpacing(15)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        self.check_port_btn = QPushButton('检查端口')
        self.check_port_btn.clicked.connect(self.check_ports)
        self.check_port_btn.setFixedHeight(40)
        self.check_port_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        
        self.kill_process_btn = QPushButton('结束占用进程')
        self.kill_process_btn.clicked.connect(self.kill_process)
        self.kill_process_btn.setFixedHeight(40)
        self.kill_process_btn.setEnabled(False)
        self.kill_process_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover:enabled {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        
        self.install_deps_btn = QPushButton('检查依赖')
        self.install_deps_btn.clicked.connect(self.check_dependencies)
        self.install_deps_btn.setFixedHeight(40)
        self.install_deps_btn.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        """)
        
        self.start_btn = QPushButton('启动服务')
        self.start_btn.clicked.connect(self.start_services)
        self.start_btn.setFixedHeight(40)
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover:enabled {
                background-color: #27ae60;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        
        button_layout.addWidget(self.check_port_btn)
        button_layout.addWidget(self.kill_process_btn)
        button_layout.addWidget(self.install_deps_btn)
        button_layout.addWidget(self.start_btn)
        button_layout.addStretch()
        
        control_layout.addLayout(button_layout)
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)
        
        # 服务状态区域
        status_group = QGroupBox("服务状态")
        status_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #34495e;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        status_layout = QVBoxLayout()
        status_layout.setSpacing(10)
        
        # HTTP服务器状态
        http_status_layout = QHBoxLayout()
        http_status_label = QLabel("HTTP服务器 (8888):")
        http_status_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.http_status_indicator = QLabel("●")
        self.http_status_indicator.setFont(QFont("Arial", 16))
        self.http_status_indicator.setStyleSheet("color: #e74c3c;")  # 红色，未运行
        self.http_status_text = QLabel("未运行")
        http_status_layout.addWidget(http_status_label)
        http_status_layout.addWidget(self.http_status_indicator)
        http_status_layout.addWidget(self.http_status_text)
        http_status_layout.addStretch()
        status_layout.addLayout(http_status_layout)
        
        # 屏幕捕获状态
        capture_status_layout = QHBoxLayout()
        capture_status_label = QLabel("屏幕捕获服务 (8889):")
        capture_status_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.capture_status_indicator = QLabel("●")
        self.capture_status_indicator.setFont(QFont("Arial", 16))
        self.capture_status_indicator.setStyleSheet("color: #e74c3c;")  # 红色，未运行
        self.capture_status_text = QLabel("未运行")
        capture_status_layout.addWidget(capture_status_label)
        capture_status_layout.addWidget(self.capture_status_indicator)
        capture_status_layout.addWidget(self.capture_status_text)
        capture_status_layout.addStretch()
        status_layout.addLayout(capture_status_layout)
        
        # 自动刷新状态
        self.refresh_status_label = QLabel("自动刷新: 未启用")
        self.refresh_status_label.setFont(QFont("Arial", 9))
        self.refresh_status_label.setStyleSheet("color: #7f8c8d;")
        status_layout.addWidget(self.refresh_status_label)
        
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        # 日志输出区域
        log_group = QGroupBox("运行日志")
        log_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #34495e;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        log_layout = QVBoxLayout()
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(200)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 10pt;
            }
        """)
        
        # 设置日志框始终显示垂直滚动条
        self.log_output.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.log_output.setLineWrapMode(QTextEdit.WidgetWidth)
        
        log_layout.addWidget(self.log_output)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        # 状态栏
        self.status_label = QLabel('就绪')
        self.status_label.setStyleSheet("color: #7f8c8d;")
        self.statusBar().addWidget(self.status_label)
        
        # 添加伸缩项使布局更宽松
        main_layout.addStretch()
        
    def on_auto_refresh_changed(self, state):
        """自动刷新复选框状态改变"""
        self.auto_refresh_enabled = (state == Qt.Checked)
        if self.auto_refresh_enabled:
            self.log_message("✅ 已启用自动刷新功能")
        else:
            self.log_message("⏸️ 已禁用自动刷新功能")
    
    def auto_refresh_ip(self):
        """自动刷新IP地址"""
        if not (self.server_running or self.screen_capture_running) or not self.auto_refresh_enabled:
            return
            
        # 获取新的本机IP
        old_ip = self.local_ip
        new_ip = self.get_local_ip()
        
        if old_ip != new_ip:
            self.local_ip = new_ip
            self.log_message(f"🔄 自动刷新: IP地址已更新 {old_ip} -> {new_ip}")
            
            # 更新链接显示
            self.update_server_links()
            
            # 更新状态提示
            self.refresh_status_label.setText(f"自动刷新: 已启用 (30秒/次) | 最后刷新: {time.strftime('%H:%M:%S')}")
    
    def refresh_server_info(self):
        """手动刷新服务器信息"""
        if not (self.server_running or self.screen_capture_running):
            self.log_message("❌ 服务未运行，无法刷新信息")
            return
            
        self.log_message("正在刷新服务器信息...")
        
        # 获取新的本机IP
        old_ip = self.local_ip
        self.local_ip = self.get_local_ip()
        
        if old_ip != self.local_ip:
            self.log_message(f"IP地址已更新: {old_ip} -> {self.local_ip}")
        else:
            self.log_message("IP地址未变化")
            
        # 更新链接显示
        self.update_server_links()
        
    def update_server_links(self):
        """更新服务器链接显示"""
        if not QRCODE_AVAILABLE:
            self.log_message("警告: 未安装 qrcode 库，无法生成QR码")
            self.log_message("请运行: pip install qrcode[pil]")
            return
            
        local_url = f"http://localhost:{self.http_port}"
        network_url = f"http://{self.local_ip}:{self.http_port}"
        
        # 更新链接标签
        self.local_link_label.setText(f"{local_url}")
        self.local_link_label.setToolTip("本地访问地址")
        
        self.network_link_label.setText(f"{network_url}")
        self.network_link_label.setToolTip("网络访问地址")
        
        # 启用按钮
        self.copy_local_btn.setEnabled(True)
        self.copy_network_btn.setEnabled(True)
        self.save_qrcode_btn.setEnabled(True)
        
        # 生成并显示QR码
        self.generate_and_display_qrcode(network_url)
        
    def generate_and_display_qrcode(self, url):
        """生成并显示QR码"""
        try:
            # 生成QR码
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            
            # 创建PIL图像
            img = qr.make_image(fill_color="black", back_color="white")
            
            # 转换为QPixmap
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimage = QImage(data, img.size[0], img.size[1], QImage.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimage)
            
            # 缩放并显示
            scaled_pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.qrcode_label.setPixmap(scaled_pixmap)
            
        except Exception as e:
            self.log_message(f"生成QR码时出错: {e}")
            # 显示错误图标
            self.qrcode_label.setText("QR码生成失败")
            self.qrcode_label.setStyleSheet("""
                QLabel {
                    border: 2px solid #e74c3c;
                    border-radius: 8px;
                    background-color: #fadbd8;
                    padding: 10px;
                    color: #c0392b;
                    font-weight: bold;
                }
            """)
            
    def save_qrcode_image(self):
        """保存QR码图片"""
        if not QRCODE_AVAILABLE:
            self.log_message("错误: qrcode 库未安装，无法保存QR码")
            return
            
        network_url = f"http://{self.local_ip}:{self.http_port}"
        
        try:
            # 创建文件名
            filename = f"screen_control_qrcode_{self.http_port}.png"
            
            # 生成并保存QR码
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(network_url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(filename)
            
            self.log_message(f"✅ QR码已保存: {filename}")
            
        except Exception as e:
            self.log_message(f"保存QR码时出错: {e}")
            
    def copy_local_link(self):
        """复制本地链接到剪贴板"""
        local_url = f"http://localhost:{self.http_port}"
        clipboard = QApplication.clipboard()
        clipboard.setText(local_url)
        self.log_message(f"✅ 已复制本地链接: {local_url}")
        
    def copy_network_link(self):
        """复制网络链接到剪贴板"""
        network_url = f"http://{self.local_ip}:{self.http_port}"
        clipboard = QApplication.clipboard()
        clipboard.setText(network_url)
        self.log_message(f"✅ 已复制网络链接: {network_url}")
        
    def _log_message_slot(self, message):
        """日志消息槽函数（在主线程中执行）"""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_output.append(f"[{timestamp}] {message}")
        
        # 自动滚动到底部
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)
        self.log_output.ensureCursorVisible()
        
    def _update_status_slot(self, message):
        """更新状态栏槽函数（在主线程中执行）"""
        self.status_label.setText(message[:50] + "..." if len(message) > 50 else message)
        
    def _show_window_slot(self):
        """显示窗口槽函数（在主线程中执行）"""
        self.showNormal()  # 恢复窗口
        self.raise_()  # 将窗口提升到顶层
        self.activateWindow()  # 激活窗口
        self.is_minimized_to_tray = False
        
    def on_http_port_changed(self, value):
        """HTTP端口号改变事件"""
        self.http_port = value
        if self.server_running or self.screen_capture_running:
            self.update_server_links()
    
    def on_ws_port_changed(self, value):
        """WebSocket端口号改变事件"""
        self.ws_port = value
        
    def log_message(self, message):
        """添加日志消息（线程安全）"""
        # 通过信号槽机制在主线程中更新UI
        self.log_message_signal.emit(message)
        self.update_status_signal.emit(message)
        
    def is_port_in_use(self, port: int) -> bool:
        """检查端口是否被占用"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.connect(('localhost', port))
                return True
            except (ConnectionRefusedError, socket.timeout):
                return False
            except Exception as e:
                self.log_message(f"检查端口时出错: {e}")
                return False
    
    def get_process_using_port(self, port: int) -> Optional[Tuple[int, str]]:
        """获取占用端口的进程信息"""
        try:
            for conn in psutil.net_connections(kind='inet'):
                if hasattr(conn.laddr, 'port') and conn.laddr.port == port and conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        return (conn.pid, proc.name())
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            return None
        except Exception as e:
            self.log_message(f"获取进程信息时出错: {e}")
            return None
    
    def get_all_processes_using_port(self, port: int) -> List[Tuple[int, str]]:
        """获取占用端口的所有进程信息"""
        processes = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                if hasattr(conn.laddr, 'port') and conn.laddr.port == port and conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        processes.append((conn.pid, proc.name()))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
        except Exception as e:
            self.log_message(f"获取进程信息时出错: {e}")
        return processes
    
    def check_ports(self):
        """检查端口占用"""
        self.log_message(f"检查HTTP端口 {self.http_port} 和WebSocket端口 {self.ws_port} ...")
        
        http_in_use = self.is_port_in_use(self.http_port)
        ws_in_use = self.is_port_in_use(self.ws_port)
        
        if http_in_use or ws_in_use:
            if http_in_use:
                self.log_message(f"⚠️ HTTP端口 {self.http_port} 已被占用")
                
                process_info = self.get_process_using_port(self.http_port)
                if process_info:
                    pid, process_name = process_info
                    self.log_message(f"占用进程: {process_name} (PID: {pid})")
                else:
                    self.log_message("无法获取进程信息")
                    
            if ws_in_use:
                self.log_message(f"⚠️ WebSocket端口 {self.ws_port} 已被占用")
                
                process_info = self.get_process_using_port(self.ws_port)
                if process_info:
                    pid, process_name = process_info
                    self.log_message(f"占用进程: {process_name} (PID: {pid})")
                else:
                    self.log_message("无法获取进程信息")
                    
            self.kill_process_btn.setEnabled(True)
            self.start_btn.setEnabled(False)
        else:
            self.log_message(f"✅ HTTP端口 {self.http_port} 可用")
            self.log_message(f"✅ WebSocket端口 {self.ws_port} 可用")
            self.kill_process_btn.setEnabled(False)
            self.start_btn.setEnabled(True)
    
    def kill_process(self):
        """结束占用进程"""
        # 获取HTTP端口占用进程
        http_process_info = self.get_process_using_port(self.http_port)
        ws_process_info = self.get_process_using_port(self.ws_port)
        
        processes_to_kill = []
        if http_process_info:
            processes_to_kill.append(("HTTP", http_process_info))
        if ws_process_info:
            processes_to_kill.append(("WebSocket", ws_process_info))
        
        if not processes_to_kill:
            self.log_message("无法获取进程信息")
            return
        
        # 显示确认对话框
        message = "确定要结束以下进程吗？\n"
        for port_type, (pid, process_name) in processes_to_kill:
            message += f"\n{port_type}端口占用: {process_name} (PID: {pid})"
        
        reply = QMessageBox.question(
            self, '确认',
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for port_type, (pid, process_name) in processes_to_kill:
                self.log_message(f"正在结束进程 {process_name} (PID: {pid})...")
                
                try:
                    if platform.system().lower() == 'windows':
                        subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                      capture_output=True, shell=True)
                    else:
                        subprocess.run(['kill', '-9', str(pid)], 
                                      capture_output=True, shell=True)
                    
                except Exception as e:
                    self.log_message(f"结束进程时出错: {e}")
            
            time.sleep(2)  # 等待进程结束
            
            # 重新检查端口
            self.check_ports()
    
    def immediate_port_cleanup(self):
        """立即清理占用端口的进程"""
        http_in_use = self.is_port_in_use(self.http_port)
        ws_in_use = self.is_port_in_use(self.ws_port)
        
        if not http_in_use and not ws_in_use:
            self.log_message(f"✅ 端口 {self.http_port} 和 {self.ws_port} 已释放")
            self.start_btn.setEnabled(True)
            self.kill_process_btn.setEnabled(False)
            return
            
        self.log_message(f"正在立即清理端口 {self.http_port} 和 {self.ws_port} ...")
        
        # 获取所有占用端口的进程
        processes = []
        if http_in_use:
            processes.extend(self.get_all_processes_using_port(self.http_port))
        if ws_in_use:
            processes.extend(self.get_all_processes_using_port(self.ws_port))
        
        if processes:
            for pid, process_name in processes:
                self.log_message(f"强制清理进程: {process_name} (PID: {pid})")
                try:
                    if platform.system().lower() == 'windows':
                        # Windows: 强制终止进程树
                        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], 
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
                    else:
                        # Linux/Mac: 强制终止进程
                        subprocess.run(['kill', '-9', str(pid)], 
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
                        
                        # 尝试终止子进程
                        subprocess.run(['pkill', '-9', '-P', str(pid)], 
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, timeout=2)
                except subprocess.TimeoutExpired:
                    self.log_message(f"清理进程 {pid} 时超时")
                except Exception as e:
                    self.log_message(f"清理进程时出错: {e}")
        
        # 短暂等待后再次检查
        time.sleep(0.5)
        
        http_in_use = self.is_port_in_use(self.http_port)
        ws_in_use = self.is_port_in_use(self.ws_port)
        
        if not http_in_use and not ws_in_use:
            self.log_message(f"✅ 端口 {self.http_port} 和 {self.ws_port} 已成功释放")
            self.start_btn.setEnabled(True)
            self.kill_process_btn.setEnabled(False)
        else:
            self.log_message(f"⚠️ 端口仍被占用，可能需要手动清理")
            self.kill_process_btn.setEnabled(True)
    
    def check_dependencies(self):
        """检查依赖"""
        self.log_message("开始检查依赖...")
        
        # 检查Node.js依赖
        if os.path.exists('node_modules'):
            self.log_message("✅ Node.js依赖已安装")
        else:
            self.log_message("⚠️ Node.js依赖未安装，请运行: npm install")
        
        # 检查Python依赖
        try:
            import websockets
            self.log_message("✅ websockets 已安装")
        except ImportError:
            self.log_message("⚠️ websockets 未安装，请运行: pip install websockets")
        
        try:
            from PIL import ImageGrab
            self.log_message("✅ Pillow 已安装")
        except ImportError:
            self.log_message("⚠️ Pillow 未安装，请运行: pip install Pillow")
        
        try:
            import pyautogui
            self.log_message("✅ pyautogui 已安装")
        except ImportError:
            self.log_message("⚠️ pyautogui 未安装，请运行: pip install pyautogui")
            
        self.log_message("依赖检查完成")
    
    def start_services(self):
        """启动服务"""
        # 检查端口
        if self.is_port_in_use(self.http_port):
            self.log_message(f"❌ HTTP端口 {self.http_port} 被占用，无法启动")
            return
        
        if self.is_port_in_use(self.ws_port):
            self.log_message(f"❌ WebSocket端口 {self.ws_port} 被占用，无法启动")
            return
        
        # 启动Node.js服务器
        self.log_message("正在启动Node.js服务器...")
        self.server_thread = ServerThread(self.http_port)
        self.server_thread.output_received.connect(self.log_message)
        self.server_thread.process_finished.connect(self.on_server_process_finished)
        self.server_thread.start()
        
        # 启动屏幕捕获
        self.log_message("正在启动屏幕捕获服务...")
        self.screen_thread = ScreenCaptureThread("127.0.0.1", self.ws_port)
        self.screen_thread.output_received.connect(self.log_message)
        self.screen_thread.process_finished.connect(self.on_screen_process_finished)
        self.screen_thread.start()
        
        # 更新按钮状态
        self.server_running = True
        self.screen_capture_running = True
        self.start_btn.setText("停止服务")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        self.start_btn.clicked.disconnect()
        self.start_btn.clicked.connect(self.stop_services)
        
        # 显示服务器信息区域
        self.server_group.show()
        
        # 更新链接显示
        self.update_server_links()
        
        # 更新状态指示器
        self.http_status_indicator.setStyleSheet("color: #2ecc71;")  # 绿色，运行中
        self.http_status_text.setText("运行中")
        self.capture_status_indicator.setStyleSheet("color: #2ecc71;")  # 绿色，运行中
        self.capture_status_text.setText("运行中")
        
        # 启动自动刷新定时器
        if self.auto_refresh_enabled:
            self.auto_refresh_timer.start(self.auto_refresh_interval)
            self.refresh_status_label.setText(f"自动刷新: 已启用 (30秒/次) | 启动时间: {time.strftime('%H:%M:%S')}")
            self.log_message("🔄 自动刷新功能已启动")
        
        self.check_port_btn.setEnabled(False)
        self.kill_process_btn.setEnabled(False)
        self.install_deps_btn.setEnabled(False)
    
    def stop_services(self):
        """停止服务 - 立即强制结束，不等待"""
        self.log_message("正在强制停止服务...")
        
        # 立即停止两个线程
        if self.server_thread and self.server_thread.isRunning():
            self.server_thread.stop()
            self.server_thread.quit()
            self.server_thread.wait(100)
            
        if self.screen_thread and self.screen_thread.isRunning():
            self.screen_thread.stop()
            self.screen_thread.quit()
            self.screen_thread.wait(100)
        
        # 停止自动刷新定时器
        if self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.stop()
            self.log_message("⏸️ 自动刷新功能已停止")
        
        # 重置按钮状态
        self.server_running = False
        self.screen_capture_running = False
        self.start_btn.setText("启动服务")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
        """)
        self.start_btn.clicked.disconnect()
        self.start_btn.clicked.connect(self.start_services)
        
        # 隐藏服务器信息区域
        self.server_group.hide()
        
        # 更新状态指示器
        self.http_status_indicator.setStyleSheet("color: #e74c3c;")  # 红色，未运行
        self.http_status_text.setText("未运行")
        self.capture_status_indicator.setStyleSheet("color: #e74c3c;")  # 红色，未运行
        self.capture_status_text.setText("未运行")
        
        self.check_port_btn.setEnabled(True)
        self.install_deps_btn.setEnabled(True)
        
        # 立即检查端口并清理残留进程
        self.immediate_port_cleanup()
        
        # 记录停止完成
        self.log_message("✅ 服务已强制停止")
    
    def on_server_process_finished(self, return_code):
        """服务器进程结束事件"""
        self.log_message(f"Node.js服务器进程已停止，退出码: {return_code}")
        
        # 如果进程异常结束，更新按钮状态
        if self.server_running:
            self.server_running = False
            self.http_status_indicator.setStyleSheet("color: #e74c3c;")
            self.http_status_text.setText(f"已停止 (退出码: {return_code})")
    
    def on_screen_process_finished(self, return_code):
        """屏幕捕获进程结束事件"""
        self.log_message(f"屏幕捕获进程已停止，退出码: {return_code}")
        
        # 如果进程异常结束，更新按钮状态
        if self.screen_capture_running:
            self.screen_capture_running = False
            self.capture_status_indicator.setStyleSheet("color: #e74c3c;")
            self.capture_status_text.setText(f"已停止 (退出码: {return_code})")
    
    def create_tray_icon(self):
        """创建系统托盘图标"""
        if not TRAY_AVAILABLE:
            return
        
        def create_image():
            """创建托盘图标"""
            # 尝试加载图标文件
            icon_path = "icon.ico"
            if os.path.exists(icon_path):
                try:
                    return Image.open(icon_path)
                except:
                    pass
            
            # 创建默认图标
            image = Image.new('RGB', (64, 64), color='blue')
            dc = ImageDraw.Draw(image)
            dc.text((20, 20), "SC", fill='white')
            return image
        
        def restore_window(icon=None, item=None):
            """从托盘恢复窗口（在托盘线程中调用）"""
            # 使用信号槽机制在主线程中恢复窗口
            self.show_window_signal.emit()
        
        def quit_app(icon=None, item=None):
            """退出应用"""
            # 通过信号槽机制在主线程中退出应用
            self.quit_app_signal.emit()
        
        # 创建托盘菜单
        menu = (
            pystray.MenuItem('打开主界面', restore_window, default=True),
            pystray.MenuItem('退出', quit_app)
        )
        
        # 创建托盘图标
        image = create_image()
        self.tray_icon = pystray.Icon("screen_control", image, "Ophio", menu)
        
        # 启动托盘线程
        def run_tray():
            try:
                self.tray_icon.run()
            except Exception as e:
                print(f"托盘图标运行错误: {e}")
        
        self.tray_thread = threading.Thread(target=run_tray, daemon=True)
        self.tray_thread.start()
    
    def restore_from_tray(self):
        """从托盘恢复窗口"""
        self.show_window_signal.emit()
    
    def minimize_to_tray(self):
        """最小化到托盘"""
        self.hide()
        self.is_minimized_to_tray = True
        self.log_message("窗口已最小化到托盘")
    
    def quit_application(self):
        """安全退出应用 - 强制结束"""
        try:
            self.log_message("正在退出应用...")
            
            # 强制停止服务
            self.stop_services()
            
            # 立即清理端口
            self.immediate_port_cleanup()
            
            # 停止托盘图标
            if self.tray_icon:
                self.log_message("停止托盘图标...")
                self.tray_icon.stop()
            
            # 退出应用
            self.log_message("应用程序退出中...")
            QApplication.quit()
            
        except Exception as e:
            print(f"退出应用时出错: {e}")
            # 如果正常退出失败，强制退出
            os._exit(0)
    
    def closeEvent(self, event):
        """重写关闭事件，最小化到托盘而不是退出"""
        event.ignore()  # 忽略默认关闭行为
        self.minimize_to_tray()


def main():
    """主函数"""
    if not PYQT_AVAILABLE:
        print("错误: 需要安装 PyQt5")
        print("请运行: pip install PyQt5")
        return
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 防止关闭窗口时退出应用
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    # 创建并显示主窗口
    window = ScreenControlLauncher()
    window.show()
    
    # 初始检查端口
    window.check_ports()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    # 检查必要的包
    required_packages = []
    
    if not PYQT_AVAILABLE:
        required_packages.append('PyQt5')
    
    if not TRAY_AVAILABLE:
        required_packages.extend(['pystray', 'Pillow'])
    
    if not QRCODE_AVAILABLE:
        required_packages.append('qrcode[pil]')
    
    try:
        import psutil
    except ImportError:
        required_packages.append('psutil')
    
    if required_packages:
        print("检测到缺少以下Python包:")
        for pkg in required_packages:
            print(f"  - {pkg}")
        
        choice = input("是否自动安装? (y/n): ").strip().lower()
        if choice in ['y', 'yes', '是']:
            try:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + required_packages)
                print("所有包安装成功，请重新启动脚本")
                sys.exit(0)
            except Exception as e:
                print(f"安装失败: {e}")
                print("请手动安装: pip install " + " ".join(required_packages))
        else:
            print("将尝试运行基本版本...")
    
    main()