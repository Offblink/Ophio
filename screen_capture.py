#!/usr/bin/env python3
"""
屏幕捕获客户端 - 调试版本
支持相对移动量（dx, dy）和绝对坐标（x, y）两种格式
包含详细调试输出
"""

import asyncio
import json
import time
import sys
import os
import platform
from io import BytesIO
import traceback

from pc_protocol import QUIET_ACTIONS, parse_control, resolve_key, to_screen

os.environ['PYAUTOGUI_SAFETY'] = '0'

try:
    from PIL import ImageGrab, Image, ImageDraw, ImageChops
    HAS_PIL = True
except ImportError as e:
    print(f"[错误] 未安装Pillow库: {e}")
    HAS_PIL = False
    sys.exit(1)

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError as e:
    print(f"[错误] 未安装websockets库: {e}")
    HAS_WEBSOCKETS = False
    sys.exit(1)

try:
    import pyautogui
    HAS_PYAUTOGUI = True
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.01
    print("[信息] pyautogui 已启用")
except ImportError:
    HAS_PYAUTOGUI = False
    print("[警告] 未安装pyautogui，控制功能将不可用")
except Exception as e:
    HAS_PYAUTOGUI = False
    print(f"[警告] pyautogui 初始化失败: {e}")

# pyautogui.scroll 把参数原样当 mouse_event 的 dwData 传，而 Windows 要求
# dwData 是 WHEEL_DELTA(120) 的整数倍（120 = 一格）——直接传格数只有 1/120 格，
# 应用侧表现为"滚不动"
WHEEL_DELTA = 120

class ScreenCaptureWithKeyboard:
    def __init__(self, host="127.0.0.1", port=8889):
        self.host = host
        self.port = port
        self.ws_url = f"ws://{host}:{port}"
        self.websocket = None
        self.is_running = False
        self.frame_count = 0
        self.last_status_time = 0
        self.last_control_time = 0
        self.last_mouse_pos = None

        # 帧优化：静止检测 + 丢帧统计
        self.last_raw = None
        self.dropped_frames = 0
        self.max_pending_bytes = 512 * 1024  # 写缓冲超512KB视为网络积压，丢旧帧
        
        # 触摸手势相关
        self.screen_width, self.screen_height = (0, 0)
        if HAS_PYAUTOGUI:
            self.screen_width, self.screen_height = pyautogui.size()

        # 键名映射统一走 pc_protocol.resolve_key（KeyboardEvent.code + 移动端历史键名）
        self.special_key_states = {
            'ctrl': False,
            'shift': False,
            'alt': False,
            'win': False
        }

        self.control_handlers = {
            'left_click': self.handle_left_click,
            'right_click': self.handle_right_click,
            'double_click': self.handle_double_click,
            'scroll_up': self.handle_scroll_up,
            'scroll_down': self.handle_scroll_down,
            'keyboard': self.handle_keyboard,
            'mouse_move': self.handle_mouse_move,
            'mouse_down': self.handle_mouse_down,
            'mouse_up': self.handle_mouse_up,
            'click': self.handle_click,
            'scroll': self.handle_scroll,
            'test_touch': self.handle_test_touch,
            'touch_start': self.handle_touch_start,
            'touch_move': self.handle_touch_move,
            'touch_end': self.handle_touch_end
        }

        self.active_special_keys = set()
        self.debug = True

        print(f"[初始化] 操作系统: {platform.system()}")
        print(f"[初始化] pyautogui 状态: {'可用' if HAS_PYAUTOGUI else '不可用'}")

    async def connect(self):
        try:
            print(f"[连接] 正在连接到 {self.ws_url}")
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=None,
                max_size=None
            )

            identity_msg = {
                "type": "capture",
                "client": "screen_capture",
                "has_pyautogui": HAS_PYAUTOGUI,
                "platform": platform.system(),
                "timestamp": time.time()
            }

            await self.websocket.send(json.dumps(identity_msg))
            print(f"[成功] 已连接到服务器，发送标识: {identity_msg}")
            print("[提示] 开始捕获屏幕并等待控制指令")

            return True

        except ConnectionRefusedError:
            print("[错误] 连接被拒绝，请确保服务器已启动")
            return False
        except Exception as e:
            print(f"[错误] 连接失败: {e}")
            return False

    def is_connected(self):
        if not self.websocket:
            return False
        try:
            if hasattr(self.websocket, 'closed'):
                return not self.websocket.closed
            elif hasattr(self.websocket, 'open'):
                return self.websocket.open
            else:
                return True
        except Exception:
            return False

    def get_mouse_position(self):
        try:
            if HAS_PYAUTOGUI:
                return pyautogui.position()
            else:
                return None
        except Exception as e:
            print(f"[错误] 获取鼠标位置失败: {e}")
            return None

    def draw_mouse_cursor(self, screenshot, mouse_pos):
        try:
            if mouse_pos is None:
                return screenshot

            x, y = mouse_pos
            img = screenshot.copy()
            draw = ImageDraw.Draw(img)

            screen_width, screen_height = pyautogui.size()
            if x < 0 or y < 0 or x >= screen_width or y >= screen_height:
                return screenshot

            cursor_size = 15
            cursor_color = (255, 0, 0)
            line_length = 10
            line_width = 2

            draw.line([(x - line_length, y), (x + line_length, y)],
                     fill=cursor_color, width=line_width)
            draw.line([(x, y - line_length), (x, y + line_length)],
                     fill=cursor_color, width=line_width)
            draw.ellipse([(x - cursor_size, y - cursor_size),
                         (x + cursor_size, y + cursor_size)],
                     outline=cursor_color, width=2)

            return img

        except Exception as e:
            print(f"[错误] 绘制鼠标指示器失败: {e}")
            return screenshot

    async def capture_frame(self):
        try:
            raw = ImageGrab.grab()

            mouse_pos = self.get_mouse_position()

            # 静止检测：画面没变且鼠标没动 → 整帧跳过（不编码、不发送）
            if self.last_raw is not None and self.last_mouse_pos == mouse_pos:
                try:
                    if ImageChops.difference(self.last_raw, raw).getbbox() is None:
                        return None
                except Exception:
                    pass  # diff失败（如分辨率变化）按有变化处理

            self.last_raw = raw
            screenshot = self.draw_mouse_cursor(raw, mouse_pos)
            self.last_mouse_pos = mouse_pos

            scale = 0.5
            if scale != 1.0:
                new_size = (int(screenshot.width * scale), int(screenshot.height * scale))
                try:
                    screenshot = screenshot.resize(new_size, Image.Resampling.LANCZOS)
                except AttributeError:
                    screenshot = screenshot.resize(new_size, Image.LANCZOS)

            buffer = BytesIO()
            screenshot.save(buffer, format='JPEG', quality=60, optimize=True)

            # 直接返回 JPEG 字节（省掉 base64 的 33% 膨胀和两端 CPU）
            return buffer.getvalue()

        except Exception as e:
            print(f"[错误] 捕获失败: {e}")
            return None

    async def send_frame(self, frame_data):
        if not frame_data or not self.is_connected():
            return False

        # 丢旧帧：写缓冲积压超阈值说明网络跟不上，跳过本帧
        transport = getattr(self.websocket, 'transport', None)
        if transport is not None:
            try:
                if transport.get_write_buffer_size() > self.max_pending_bytes:
                    self.dropped_frames += 1
                    return True
            except Exception:
                pass  # transport 查询失败按正常发送处理

        try:
            await self.websocket.send(frame_data)
            self.frame_count += 1

            if self.frame_count % 30 == 0:
                current_time = time.time()
                if current_time - self.last_status_time > 1:
                    fps = 30 / (current_time - self.last_status_time) if self.last_status_time > 0 else 0
                    drop_info = f" | 丢弃 {self.dropped_frames} 帧" if self.dropped_frames else ""
                    print(f"[状态] 已发送 {self.frame_count} 帧 | 帧率: {fps:.1f} FPS{drop_info}")
                    self.last_status_time = current_time

            return True

        except websockets.exceptions.ConnectionClosed:
            print("[警告] 连接已关闭")
            self.websocket = None
            return False
        except Exception as e:
            print(f"[错误] 发送失败: {e}")
            return False

    async def receive_control_messages(self):
        try:
            while self.is_running and self.is_connected():
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=0.1)
                    if message:
                        await self.handle_control_message(message)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("[警告] 控制连接已关闭")
                    self.websocket = None
                    break
                except Exception as e:
                    print(f"[错误] 接收消息失败: {e}")
                    break
        except Exception as e:
            print(f"[错误] 接收循环异常: {e}")
            traceback.print_exc()

    async def handle_control_message(self, message):
        try:
            data = json.loads(message)
            if not isinstance(data, dict):
                return
        except ValueError:
            if len(message) < 100:
                print(f"[警告] 非JSON控制消息: {message}")
            return
        except Exception as e:
            print(f"[错误] 处理控制消息失败: {e}")
            return

        action = data.get('action', '')
        # repeat 帧是长按自动重复（约30条/秒），与鼠标移动同为高频流：不打日志、不回执行日志
        quiet = action in QUIET_ACTIONS or bool(data.get('repeat'))
        if not quiet:
            print(f"[调试] 收到控制消息: {data}")

        parsed = parse_control(data)
        if parsed is None:
            if not quiet:
                print(f"[警告] 无效或未知的控制指令: {data}")
            return
        action, kwargs = parsed

        handler = self.control_handlers.get(action)
        if handler is None:
            print(f"[警告] 未知控制指令: {action}")
            return
        if not HAS_PYAUTOGUI:
            if not quiet:
                print(f"[警告] pyautogui未安装，无法执行 {action}")
            return

        if not quiet:
            print(f"[控制] 执行: {action}")
        try:
            handler(**kwargs)
        except Exception as e:
            print(f"[错误] 执行控制指令 {action} 失败: {e}")
            traceback.print_exc()

    def handle_test_touch(self, data):
        print(f"[调试消息] {data.get('message', '空')}")

    def handle_left_click(self):
        try:
            print("[鼠标] 执行左键点击")
            if HAS_PYAUTOGUI:
                pyautogui.click(button='left')
                print("[鼠标] 左键点击完成")
        except Exception as e:
            print(f"[错误] 左键点击失败: {e}")

    def handle_right_click(self):
        try:
            print("[鼠标] 执行右键点击")
            if HAS_PYAUTOGUI:
                pyautogui.click(button='right')
                print("[鼠标] 右键点击完成")
        except Exception as e:
            print(f"[错误] 右键点击失败: {e}")

    def handle_double_click(self):
        try:
            print("[鼠标] 执行双击")
            if HAS_PYAUTOGUI:
                pyautogui.doubleClick()
                print("[鼠标] 双击完成")
        except Exception as e:
            print(f"[错误] 双击失败: {e}")

    def handle_scroll_up(self):
        try:
            print("[鼠标] 执行向上滚动")
            if HAS_PYAUTOGUI:
                pyautogui.scroll(WHEEL_DELTA)
                print("[鼠标] 向上滚动完成")
        except Exception as e:
            print(f"[错误] 向上滚动失败: {e}")

    def handle_scroll_down(self):
        try:
            print("[鼠标] 执行向下滚动")
            if HAS_PYAUTOGUI:
                pyautogui.scroll(-WHEEL_DELTA)
                print("[鼠标] 向下滚动完成")
        except Exception as e:
            print(f"[错误] 向下滚动失败: {e}")

    def _move_to_normalized(self, x, y):
        """归一化坐标 → 屏幕坐标并瞬移（高频路径：零动画、零日志）"""
        screen_width, screen_height = pyautogui.size()
        abs_x, abs_y = to_screen(x, y, screen_width, screen_height)
        pyautogui.moveTo(abs_x, abs_y, duration=0)
        self.last_mouse_pos = (abs_x, abs_y)

    def handle_mouse_move(self, x=None, y=None, dx=None, dy=None):
        """鼠标移动：dx/dy 为相对位移，x/y 为归一化绝对坐标（二选一，相对优先）"""
        if not HAS_PYAUTOGUI:
            return
        try:
            if dx is not None and dy is not None:
                pyautogui.moveRel(dx, dy, duration=0)
                self.last_mouse_pos = pyautogui.position()
            elif x is not None and y is not None:
                self._move_to_normalized(x, y)
        except Exception as e:
            print(f"[错误] 鼠标移动失败: {e}")

    def handle_mouse_down(self, button, x=None, y=None):
        """按下鼠标按键（PC 端拖拽/点击的按下半段）"""
        if not HAS_PYAUTOGUI:
            return
        try:
            if x is not None and y is not None:
                self._move_to_normalized(x, y)
            pyautogui.mouseDown(button=button)
        except Exception as e:
            print(f"[错误] 鼠标按下失败: {e}")

    def handle_mouse_up(self, button, x=None, y=None):
        """释放鼠标按键（PC 端拖拽/点击的释放半段）"""
        if not HAS_PYAUTOGUI:
            return
        try:
            if x is not None and y is not None:
                self._move_to_normalized(x, y)
            pyautogui.mouseUp(button=button)
        except Exception as e:
            print(f"[错误] 鼠标释放失败: {e}")

    def handle_click(self, button='left', clicks=1, x=None, y=None):
        """在指定位置（可选）执行 1-3 次点击"""
        if not HAS_PYAUTOGUI:
            return
        try:
            if x is not None and y is not None:
                self._move_to_normalized(x, y)
            pyautogui.click(button=button, clicks=clicks, interval=0.05)
        except Exception as e:
            print(f"[错误] 点击失败: {e}")

    def handle_scroll(self, amount):
        """滚轮：正数向上、负数向下，单位为格（异常值已在 parse 阶段钳制）"""
        if not HAS_PYAUTOGUI:
            return
        try:
            if amount:
                pyautogui.scroll(int(amount) * WHEEL_DELTA)
        except Exception as e:
            print(f"[错误] 滚轮失败: {e}")

    def handle_touch_start(self, x, y):
        """处理触摸开始事件（归一化坐标 0-1）"""
        if not HAS_PYAUTOGUI:
            print("[警告] pyautogui不可用，无法处理触摸事件")
            return
        
        print(f"[触摸] 按下: ({x:.3f}, {y:.3f})")

    def handle_touch_move(self, x, y):
        """处理触摸移动事件 - 实时瞬移鼠标到触摸坐标"""
        if not HAS_PYAUTOGUI:
            return
        
        # 将归一化坐标转换为屏幕像素坐标
        screen_x = int(x * self.screen_width)
        screen_y = int(y * self.screen_height)
        
        print(f"[触摸] 移动: ({x:.3f}, {y:.3f}) -> 屏幕坐标: ({screen_x}, {screen_y})")
        
        # 实时瞬移鼠标到触摸位置
        try:
            pyautogui.moveTo(screen_x, screen_y, duration=0)
        except Exception as e:
            print(f"[错误] 鼠标移动失败: {e}")

    def handle_touch_end(self):
        """处理触摸结束事件"""
        print("[触摸] 松开")

    def handle_keyboard(self, key, state, repeat=False):
        """键盘事件；repeat=True 为长按的自动重复帧——静默重按下产生连发"""
        try:
            if not HAS_PYAUTOGUI:
                print("[警告] pyautogui未安装，无法处理键盘事件")
                return

            self.last_control_time = time.time()

            # 长按重复帧不打日志（浏览器自动重复约30条/秒会刷爆控制台）
            verbose = self.debug and not repeat

            if verbose:
                print(f"[键盘] 处理事件: key='{key}', state='{state}'")

            # key 已由 pc_protocol.parse_control 解析；兜底再解析一次保持幂等
            mapped_key = resolve_key(key) or key

            if verbose:
                print(f"[键盘] 映射键: {key} -> {mapped_key}")

            is_special_key = mapped_key in self.special_key_states

            if state == 'keydown':
                if is_special_key:
                    if not self.special_key_states[mapped_key]:
                        pyautogui.keyDown(mapped_key)
                        self.special_key_states[mapped_key] = True
                        self.active_special_keys.add(mapped_key)
                        if verbose:
                            print(f"[键盘] 按下特殊键: {mapped_key}")
                else:
                    # 注入的 keyDown 不会像物理键盘那样自重复：长按重复帧靠再次
                    # keyDown 产生 WM_KEYDOWN 连发（与 OS 自动重复同路径）
                    pyautogui.keyDown(mapped_key)
                    if verbose:
                        print(f"[键盘] 按下: {mapped_key}")

            elif state == 'keyup':
                if is_special_key:
                    if self.special_key_states[mapped_key]:
                        pyautogui.keyUp(mapped_key)
                        self.special_key_states[mapped_key] = False
                        if mapped_key in self.active_special_keys:
                            self.active_special_keys.remove(mapped_key)
                        print(f"[键盘] 释放特殊键: {mapped_key}")
                else:
                    pyautogui.keyUp(mapped_key)
                    print(f"[键盘] 释放: {mapped_key}")

            elif state == 'press':
                pyautogui.press(mapped_key)
                print(f"[键盘] 按键: {mapped_key}")

        except Exception as e:
            print(f"[错误] 键盘事件失败: {e}")
            traceback.print_exc()

    def release_all_special_keys(self):
        if not HAS_PYAUTOGUI:
            return

        for key, is_pressed in self.special_key_states.items():
            if is_pressed:
                try:
                    pyautogui.keyUp(key)
                    self.special_key_states[key] = False
                    print(f"[清理] 释放特殊键: {key}")
                except Exception as e:
                    print(f"[错误] 释放特殊键 {key} 失败: {e}")

        self.active_special_keys.clear()

    async def main_loop(self):
        self.is_running = True

        print("="*60)
        print("屏幕共享控制客户端 (调试版本)")
        print(f"服务器: {self.ws_url}")
        print(f"控制功能: {'已启用' if HAS_PYAUTOGUI else '未启用'}")
        print("鼠标指示器: 已启用")
        print("支持相对移动: 已启用")
        print("="*60)

        if not await self.connect():
            return

        control_task = asyncio.create_task(self.receive_control_messages())

        reconnect_count = 0
        max_reconnect = 5

        try:
            while self.is_running:
                try:
                    start_time = time.time()

                    if not self.is_connected():
                        reconnect_count += 1
                        if reconnect_count <= max_reconnect:
                            print(f"[重连] 尝试重新连接 ({reconnect_count}/{max_reconnect})...")
                            if await self.connect():
                                reconnect_count = 0
                                control_task.cancel()
                                control_task = asyncio.create_task(self.receive_control_messages())
                            else:
                                await asyncio.sleep(2)
                                continue
                        else:
                            print("[错误] 重连次数过多，退出")
                            break

                    frame_data = await self.capture_frame()
                    if frame_data:
                        await self.send_frame(frame_data)

                    elapsed = time.time() - start_time
                    target_delay = 1/15

                    if elapsed < target_delay:
                        await asyncio.sleep(target_delay - elapsed)

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"[错误] 主循环异常: {e}")
                    await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("\n[中断] 用户中断")
        finally:
            await self.cleanup(control_task)

    async def cleanup(self, control_task=None):
        self.is_running = False
        self.release_all_special_keys()

        if control_task and not control_task.done():
            control_task.cancel()
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
        print("[关闭] 客户端已停止")

async def main():
    if not HAS_PIL or not HAS_WEBSOCKETS:
        return

    if platform.system().lower() == 'darwin':
        print("[提示] macOS 系统可能需要辅助功能权限")

    client = ScreenCaptureWithKeyboard(host="127.0.0.1", port=8889)

    try:
        await client.main_loop()
    except KeyboardInterrupt:
        print("\n[退出] 程序结束")
    except Exception as e:
        print(f"[致命错误] {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

