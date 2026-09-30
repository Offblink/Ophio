#!/usr/bin/env python3
"""PC 端远程控制协议的纯逻辑模块。

不含 pyautogui / websockets 等副作用，供 screen_capture.py 调用、供 pytest 直接测试。

三条协议约定：
1. PC 页面发送 ``KeyboardEvent.code``（物理键名，如 "KeyA" / "Home"），见 CODE_MAP；
   移动端虚拟键盘继续发送历史键名（如 "a" / "space"），见 LEGACY_KEYS，两者互不干扰。
2. 归一化坐标 x, y ∈ [0, 1]，乘以宿主屏幕分辨率得到像素坐标（to_screen）。
3. 滚轮为带符号的格数 amount（正数=向上），由前端按 deltaX/deltaY 累积换算。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# 按键映射
# ---------------------------------------------------------------------------

# KeyboardEvent.code → pyautogui 键名（精确匹配，大小写敏感）
CODE_MAP = {
    # 字母键 KeyA-KeyZ → a-z
    **{f"Key{chr(c)}": chr(c).lower() for c in range(ord("A"), ord("Z") + 1)},
    # 主键盘数字 Digit0-9 → 0-9
    **{f"Digit{i}": i for i in "0123456789"},
    # 小键盘 Numpad0-9 → 0-9（NumLock 开时输出数字）
    **{f"Numpad{i}": i for i in "0123456789"},
    # 功能键 F1-F24
    **{f"F{i}": f"f{i}" for i in range(1, 25)},
    # 方向键与光标控制
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
    "Home": "home",
    "End": "end",
    "PageUp": "pageup",
    "PageDown": "pagedown",
    "Insert": "insert",
    "Delete": "delete",
    # 编辑与开关
    "Backspace": "backspace",
    "Enter": "enter",
    "Tab": "tab",
    "Space": "space",
    "Escape": "esc",
    "CapsLock": "capslock",
    "NumLock": "numlock",
    "ScrollLock": "scrolllock",
    "PrintScreen": "printscreen",
    "Pause": "pause",
    "ContextMenu": "apps",
    # 修饰键（左右侧映射到同一个 pyautogui 键）
    "ControlLeft": "ctrl",
    "ControlRight": "ctrl",
    "ShiftLeft": "shift",
    "ShiftRight": "shift",
    "AltLeft": "alt",
    "AltRight": "alt",
    "MetaLeft": "win",
    "MetaRight": "win",
    # 标点与符号（物理键位，输出字符由宿主键盘布局决定）
    "Backquote": "`",
    "Minus": "-",
    "Equal": "=",
    "BracketLeft": "[",
    "BracketRight": "]",
    "Backslash": "\\",
    "Semicolon": ";",
    "Quote": "'",
    "Comma": ",",
    "Period": ".",
    "Slash": "/",
    # 小键盘运算符
    "NumpadAdd": "+",
    "NumpadSubtract": "-",
    "NumpadMultiply": "*",
    "NumpadDivide": "/",
    "NumpadDecimal": "decimal",
    "NumpadEnter": "enter",
}

# 移动端虚拟键盘的历史键名 → pyautogui 键名（旧 key_map 的等价迁移，
# 注意历史行为把 'delete' 映射为 'backspace'——移动端没有独立删除键）
LEGACY_KEYS = {
    **{c: c for c in "0123456789"},
    **{c: c for c in "abcdefghijklmnopqrstuvwxyz"},
    **{c.upper(): c for c in "abcdefghijklmnopqrstuvwxyz"},
    "escape": "esc",
    "esc": "esc",
    "tab": "tab",
    "enter": "enter",
    "return": "enter",
    "backspace": "backspace",
    "delete": "backspace",
    "space": "space",
    " ": "space",
    "capslock": "capslock",
    "arrowup": "up",
    "up": "up",
    "arrowdown": "down",
    "down": "down",
    "arrowleft": "left",
    "left": "left",
    "arrowright": "right",
    "right": "right",
    "control": "ctrl",
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "meta": "win",
    "win": "win",
    "command": "win",
    "-": "-",
    "=": "=",
    "[": "[",
    "]": "]",
    "\\": "\\",
    ";": ";",
    "'": "'",
    ",": ",",
    ".": ".",
    "/": "/",
    "`": "`",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}

# 这些动作是高频静默流：宿主不打日志、服务器不回 ack
QUIET_ACTIONS = frozenset({"mouse_move"})

# 合法的鼠标按键
MOUSE_BUTTONS = frozenset({"left", "middle", "right"})

# 合法的键盘事件状态
KEY_STATES = frozenset({"keydown", "keyup", "press"})


def resolve_key(raw: Any) -> Optional[str]:
    """把协议里的键名解析为 pyautogui 键名；无法识别返回 None。

    优先精确匹配 KeyboardEvent.code（PC 端），再回退到历史键名（移动端，不区分大小写）。
    """
    if not isinstance(raw, str) or not raw:
        return None
    if raw in CODE_MAP:
        return CODE_MAP[raw]
    legacy = LEGACY_KEYS.get(raw.lower())
    return legacy


def _as_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_screen(nx: float, ny: float, screen_width: int, screen_height: int) -> Tuple[int, int]:
    """归一化坐标 (0-1) → 屏幕像素坐标，钳制在屏幕范围内。"""
    x = int(nx * screen_width)
    y = int(ny * screen_height)
    x = max(0, min(x, screen_width - 1))
    y = max(0, min(y, screen_height - 1))
    return x, y


def clamp_scroll_amount(amount: Any, cap: int = 10) -> int:
    """滚轮格数转 int 并钳制，防止异常值导致狂滚。"""
    value = _as_int(amount, 0)
    return max(-cap, min(value, cap))


def parse_control(msg: Mapping[str, Any]) -> Optional[Tuple[str, dict]]:
    """把一条控制消息解析为 ``(action, handler_kwargs)``；无法识别返回 None。

    解析结果与 screen_capture 的处理器签名一一对应，非法参数直接返回 None。
    """
    action = msg.get("action")
    if not isinstance(action, str) or not action:
        return None

    if action == "keyboard":
        state = msg.get("state", "keydown")
        if state not in KEY_STATES:
            return None
        key = resolve_key(msg.get("key"))
        if key is None:
            return None
        return "keyboard", {"key": key, "state": state}

    if action == "mouse_move":
        dx = _as_float(msg.get("dx")) if "dx" in msg else None
        dy = _as_float(msg.get("dy")) if "dy" in msg else None
        if dx is not None and dy is not None:
            return "mouse_move", {"dx": dx, "dy": dy}
        x = _as_float(msg.get("x")) if "x" in msg else None
        y = _as_float(msg.get("y")) if "y" in msg else None
        if x is not None and y is not None:
            return "mouse_move", {"x": x, "y": y}
        return None

    if action in ("mouse_down", "mouse_up"):
        button = msg.get("button", "left")
        if button not in MOUSE_BUTTONS:
            return None
        x = _as_float(msg.get("x")) if "x" in msg else None
        y = _as_float(msg.get("y")) if "y" in msg else None
        if (x is None) != (y is None):
            return None
        return action, {"button": button, "x": x, "y": y}

    if action == "click":
        button = msg.get("button", "left")
        if button not in MOUSE_BUTTONS:
            return None
        clicks = _as_int(msg.get("clicks", 1), 1)
        if clicks < 1 or clicks > 3:
            return None
        x = _as_float(msg.get("x")) if "x" in msg else None
        y = _as_float(msg.get("y")) if "y" in msg else None
        if (x is None) != (y is None):
            return None
        return "click", {"button": button, "clicks": clicks, "x": x, "y": y}

    if action == "scroll":
        return "scroll", {"amount": clamp_scroll_amount(msg.get("amount", 0))}

    # 无参数动作（移动端按钮与既有行为）
    if action in ("left_click", "right_click", "double_click", "scroll_up", "scroll_down",
                  "touch_end"):
        return action, {}

    if action in ("touch_start", "touch_move"):
        x = _as_float(msg.get("x"))
        y = _as_float(msg.get("y"))
        if x is None or y is None:
            return None
        return action, {"x": x, "y": y}

    if action == "test_touch":
        return action, {"data": dict(msg)}

    return None
