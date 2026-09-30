"""screen_capture 输入注入测试：用假 pyautogui 断言调用参数，不碰真实鼠标键盘。"""

import asyncio
import json

import pytest

import screen_capture


class FakePyAutoGUI:
    """记录调用序列的 pyautogui 替身。"""

    def __init__(self, screen=(1920, 1080)):
        self.calls = []
        self._screen = screen
        self._pos = (100, 100)

    def size(self):
        return self._screen

    def position(self):
        return self._pos

    def moveTo(self, x, y, duration=None):
        self.calls.append(("moveTo", x, y, duration))
        self._pos = (x, y)

    def moveRel(self, dx, dy, duration=None):
        self.calls.append(("moveRel", dx, dy, duration))
        self._pos = (self._pos[0] + dx, self._pos[1] + dy)

    def mouseDown(self, button="left"):
        self.calls.append(("mouseDown", button))

    def mouseUp(self, button="left"):
        self.calls.append(("mouseUp", button))

    def click(self, button="left", clicks=1, interval=None):
        self.calls.append(("click", button, clicks, interval))

    def scroll(self, amount):
        self.calls.append(("scroll", amount))

    def keyDown(self, key):
        self.calls.append(("keyDown", key))

    def keyUp(self, key):
        self.calls.append(("keyUp", key))

    def press(self, key):
        self.calls.append(("press", key))


@pytest.fixture
def env(monkeypatch):
    fake = FakePyAutoGUI()
    monkeypatch.setattr(screen_capture, "pyautogui", fake)
    monkeypatch.setattr(screen_capture, "HAS_PYAUTOGUI", True)
    client = screen_capture.ScreenCaptureWithKeyboard()
    return client, fake


def dispatch(client, msg):
    asyncio.run(client.handle_control_message(json.dumps(msg)))


class TestMouseMove:
    def test_absolute_maps_to_pixels_with_zero_animation(self, env):
        client, fake = env
        client.handle_mouse_move(x=0.5, y=0.25)
        # duration 必须为 0：旧实现 duration=0.1 让桌面操作每次移动都有 100ms 动画
        assert fake.calls == [("moveTo", 960, 270, 0)]

    def test_absolute_far_edge_clamped(self, env):
        client, fake = env
        client.handle_mouse_move(x=1.0, y=1.0)
        assert fake.calls == [("moveTo", 1919, 1079, 0)]

    def test_relative_moves_without_animation(self, env):
        client, fake = env
        client.handle_mouse_move(dx=10, dy=-4)
        assert fake.calls == [("moveRel", 10, -4, 0)]

    def test_dispatch_from_json_absolute(self, env):
        client, fake = env
        dispatch(client, {"action": "mouse_move", "x": 0, "y": 0})
        assert fake.calls == [("moveTo", 0, 0, 0)]

    def test_dispatch_ignores_garbage_without_raising(self, env):
        client, fake = env
        dispatch(client, {"action": "mouse_move", "x": "NaN-ish"})
        assert fake.calls == []


class TestMouseButtons:
    def test_mouse_down_moves_first_then_presses(self, env):
        client, fake = env
        client.handle_mouse_down("right", x=0.25, y=0.5)
        assert fake.calls == [("moveTo", 480, 540, 0), ("mouseDown", "right")]

    def test_mouse_up_without_coords_only_releases(self, env):
        client, fake = env
        client.handle_mouse_up("left", x=None, y=None)
        assert fake.calls == [("mouseUp", "left")]

    def test_invalid_button_never_reaches_pyautogui(self, env):
        client, fake = env
        dispatch(client, {"action": "mouse_down", "button": "thumb"})
        assert fake.calls == []

    def test_click_with_position_and_count(self, env):
        client, fake = env
        dispatch(client, {"action": "click", "button": "middle", "clicks": 2, "x": 1.0, "y": 0.0})
        assert fake.calls == [("moveTo", 1919, 0, 0), ("click", "middle", 2, 0.05)]


class TestScroll:
    def test_scroll_notches_converted_to_wheel_delta(self, env):
        # Windows dwData 必须是 120 的整数倍；1 格不换算 = 1/120 格 = 滚不动
        client, fake = env
        dispatch(client, {"action": "scroll", "amount": -3})
        assert fake.calls == [("scroll", -360)]

    def test_scroll_capped_value(self, env):
        client, fake = env
        dispatch(client, {"action": "scroll", "amount": -9999})
        assert fake.calls == [("scroll", -1200)]  # 钳制10格 → 10*120

    def test_zero_scroll_is_noop(self, env):
        client, fake = env
        dispatch(client, {"action": "scroll", "amount": 0})
        assert fake.calls == []

    def test_legacy_scroll_buttons_send_full_notch(self, env):
        client, fake = env
        dispatch(client, {"action": "scroll_up"})
        dispatch(client, {"action": "scroll_down"})
        assert fake.calls == [("scroll", 120), ("scroll", -120)]


class TestKeyboard:
    def test_pc_code_keydown_keyup(self, env):
        client, fake = env
        dispatch(client, {"action": "keyboard", "key": "KeyQ", "state": "keydown"})
        dispatch(client, {"action": "keyboard", "key": "KeyQ", "state": "keyup"})
        assert fake.calls == [("keyDown", "q"), ("keyUp", "q")]

    def test_special_key_press_is_deduplicated_until_release(self, env):
        client, fake = env
        dispatch(client, {"action": "keyboard", "key": "ControlLeft", "state": "keydown"})
        dispatch(client, {"action": "keyboard", "key": "ControlLeft", "state": "keydown"})
        assert fake.calls == [("keyDown", "ctrl")]  # 宿主不重复按下

        dispatch(client, {"action": "keyboard", "key": "ControlLeft", "state": "keyup"})
        assert fake.calls[-1] == ("keyUp", "ctrl")

    def test_mobile_legacy_key_still_works(self, env):
        client, fake = env
        dispatch(client, {"action": "keyboard", "key": "space", "state": "press"})
        assert fake.calls == [("press", "space")]

    def test_pc_navigation_key(self, env):
        client, fake = env
        dispatch(client, {"action": "keyboard", "key": "PageDown", "state": "keydown"})
        dispatch(client, {"action": "keyboard", "key": "PageDown", "state": "keyup"})
        assert fake.calls == [("keyDown", "pagedown"), ("keyUp", "pagedown")]

    def test_repeat_keydown_reissues_press(self, env):
        # 长按：repeat 帧必须再次 keyDown 才能连发（注入的 keyDown 不自重复）
        client, fake = env
        dispatch(client, {"action": "keyboard", "key": "KeyQ", "state": "keydown"})
        dispatch(client, {"action": "keyboard", "key": "KeyQ", "state": "keydown", "repeat": True})
        dispatch(client, {"action": "keyboard", "key": "KeyQ", "state": "keyup"})
        assert fake.calls == [("keyDown", "q"), ("keyDown", "q"), ("keyUp", "q")]

    def test_repeat_never_represses_modifier(self, env):
        client, fake = env
        dispatch(client, {"action": "keyboard", "key": "ControlLeft", "state": "keydown"})
        dispatch(client, {"action": "keyboard", "key": "ControlLeft", "state": "keydown", "repeat": True})
        assert fake.calls == [("keyDown", "ctrl")]  # 修饰键保持按下，不连发

    def test_repeat_frames_are_silent(self, env, capsys):
        # repeat 约30条/秒，任何日志都会刷爆控制台；普通键仍打日志作对照
        client, fake = env
        capsys.readouterr()  # 丢弃构造期输出
        dispatch(client, {"action": "keyboard", "key": "KeyA", "state": "keydown", "repeat": True})
        assert capsys.readouterr().out == ""
        assert fake.calls == [("keyDown", "a")]

        dispatch(client, {"action": "keyboard", "key": "KeyA", "state": "keydown"})
        assert "[键盘]" in capsys.readouterr().out


class TestDispatchRobustness:
    def test_unknown_action_is_dropped(self, env):
        client, fake = env
        dispatch(client, {"action": "launch_missiles"})
        assert fake.calls == []

    def test_malformed_json_does_not_raise(self, env):
        client, fake = env
        asyncio.run(client.handle_control_message("not json"))
        asyncio.run(client.handle_control_message("[1, 2, 3]"))
        assert fake.calls == []

    def test_legacy_mobile_left_click_still_dispatches(self, env):
        client, fake = env
        dispatch(client, {"action": "left_click"})
        assert fake.calls == [("click", "left", 1, None)]
