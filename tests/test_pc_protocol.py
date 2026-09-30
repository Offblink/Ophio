"""pc_protocol 纯逻辑测试：键码映射、坐标换算、控制命令解析。"""

import pc_protocol as pp


class TestResolveKey:
    def test_code_map_letters(self):
        assert pp.resolve_key("KeyA") == "a"
        assert pp.resolve_key("KeyZ") == "z"

    def test_code_map_digits(self):
        assert pp.resolve_key("Digit5") == "5"
        assert pp.resolve_key("Numpad7") == "7"

    def test_code_map_navigation(self):
        assert pp.resolve_key("ArrowUp") == "up"
        assert pp.resolve_key("Home") == "home"
        assert pp.resolve_key("End") == "end"
        assert pp.resolve_key("PageUp") == "pageup"
        assert pp.resolve_key("PageDown") == "pagedown"
        assert pp.resolve_key("Insert") == "insert"

    def test_code_map_modifiers_both_sides(self):
        assert pp.resolve_key("ControlLeft") == "ctrl"
        assert pp.resolve_key("ControlRight") == "ctrl"
        assert pp.resolve_key("ShiftLeft") == "shift"
        assert pp.resolve_key("MetaRight") == "win"
        assert pp.resolve_key("AltLeft") == "alt"

    def test_code_map_function_keys(self):
        assert pp.resolve_key("F1") == "f1"
        assert pp.resolve_key("F12") == "f12"
        assert pp.resolve_key("F24") == "f24"

    def test_code_map_special(self):
        assert pp.resolve_key("Escape") == "esc"
        assert pp.resolve_key("Space") == "space"
        assert pp.resolve_key("Enter") == "enter"
        assert pp.resolve_key("NumpadEnter") == "enter"
        assert pp.resolve_key("NumpadDecimal") == "decimal"
        assert pp.resolve_key("ContextMenu") == "apps"
        assert pp.resolve_key("PrintScreen") == "printscreen"

    def test_forward_delete_wins_over_legacy_backspace(self):
        # PC 端 e.code="Delete" 是前进删除；移动端历史键名 "delete" 仍是退格
        assert pp.resolve_key("Delete") == "delete"
        assert pp.resolve_key("delete") == "backspace"

    def test_legacy_mobile_keys(self):
        assert pp.resolve_key("space") == "space"
        assert pp.resolve_key("esc") == "esc"
        assert pp.resolve_key("A") == "a"
        assert pp.resolve_key("backspace") == "backspace"
        assert pp.resolve_key("win") == "win"
        assert pp.resolve_key("f5") == "f5"

    def test_unknown_and_invalid(self):
        assert pp.resolve_key("foobar") is None
        assert pp.resolve_key("") is None
        assert pp.resolve_key(None) is None
        assert pp.resolve_key(123) is None
        assert pp.resolve_key("HyperRight") is None


class TestToScreen:
    def test_origin(self):
        assert pp.to_screen(0.0, 0.0, 1920, 1080) == (0, 0)

    def test_center(self):
        assert pp.to_screen(0.5, 0.5, 1920, 1080) == (960, 540)

    def test_far_edge_clamped_inside_screen(self):
        # 归一化 1.0 乘分辨率会越界一像素，必须钳到 w-1/h-1
        assert pp.to_screen(1.0, 1.0, 1920, 1080) == (1919, 1079)

    def test_out_of_range_clamped(self):
        assert pp.to_screen(1.5, -0.2, 1920, 1080) == (1919, 0)


class TestClampScrollAmount:
    def test_normal_values(self):
        assert pp.clamp_scroll_amount(3) == 3
        assert pp.clamp_scroll_amount(-2) == -2

    def test_overflow_capped(self):
        assert pp.clamp_scroll_amount(9999) == 10
        assert pp.clamp_scroll_amount(-9999) == -10

    def test_garbage_is_zero(self):
        assert pp.clamp_scroll_amount("abc") == 0
        assert pp.clamp_scroll_amount(None) == 0
        assert pp.clamp_scroll_amount(2.7) == 2


class TestParseControl:
    def test_keyboard_resolves_code_and_defaults_state(self):
        action, kwargs = pp.parse_control({"action": "keyboard", "key": "KeyB"})
        assert action == "keyboard"
        assert kwargs == {"key": "b", "state": "keydown"}

    def test_keyboard_keyup(self):
        _, kwargs = pp.parse_control({"action": "keyboard", "key": "ShiftLeft", "state": "keyup"})
        assert kwargs == {"key": "shift", "state": "keyup"}

    def test_keyboard_unknown_key_rejected(self):
        assert pp.parse_control({"action": "keyboard", "key": "NotAKey"}) is None

    def test_keyboard_bad_state_rejected(self):
        assert pp.parse_control({"action": "keyboard", "key": "KeyA", "state": "hold"}) is None

    def test_mouse_move_absolute_keeps_zero_coordinates(self):
        # Go 端曾用 omitempty 吞掉 0 坐标；解析必须保留 x=0/y=0
        action, kwargs = pp.parse_control({"action": "mouse_move", "x": 0, "y": 0})
        assert action == "mouse_move"
        assert kwargs == {"x": 0.0, "y": 0.0}

    def test_mouse_move_relative_wins_when_both_present(self):
        _, kwargs = pp.parse_control({"action": "mouse_move", "x": 0.5, "y": 0.5, "dx": -3, "dy": 4})
        assert kwargs == {"dx": -3.0, "dy": 4.0}

    def test_mouse_move_relative_zero_is_kept(self):
        _, kwargs = pp.parse_control({"action": "mouse_move", "dx": 0, "dy": 0})
        assert kwargs == {"dx": 0.0, "dy": 0.0}

    def test_mouse_move_missing_axis_rejected(self):
        assert pp.parse_control({"action": "mouse_move", "x": 0.3}) is None
        assert pp.parse_control({"action": "mouse_move"}) is None

    def test_mouse_move_non_numeric_rejected(self):
        assert pp.parse_control({"action": "mouse_move", "x": "abc", "y": 0.5}) is None

    def test_mouse_down_defaults_button_and_keeps_coords(self):
        action, kwargs = pp.parse_control({"action": "mouse_down", "x": 0.1, "y": 0.2})
        assert action == "mouse_down"
        assert kwargs == {"button": "left", "x": 0.1, "y": 0.2}

    def test_mouse_up_without_coords(self):
        _, kwargs = pp.parse_control({"action": "mouse_up", "button": "right"})
        assert kwargs == {"button": "right", "x": None, "y": None}

    def test_invalid_button_rejected(self):
        assert pp.parse_control({"action": "mouse_down", "button": "thumb"}) is None

    def test_half_coordinates_rejected(self):
        assert pp.parse_control({"action": "mouse_down", "x": 0.5}) is None

    def test_click_validates_clicks_range(self):
        assert pp.parse_control({"action": "click", "clicks": 2}) is not None
        assert pp.parse_control({"action": "click", "clicks": 0}) is None
        assert pp.parse_control({"action": "click", "clicks": 4}) is None

    def test_scroll_amount_coerced_and_capped(self):
        _, kwargs = pp.parse_control({"action": "scroll", "amount": -100})
        assert kwargs == {"amount": -10}
        _, kwargs = pp.parse_control({"action": "scroll", "amount": 3})
        assert kwargs == {"amount": 3}

    def test_legacy_click_actions_pass_through(self):
        for action in ("left_click", "right_click", "double_click", "scroll_up", "scroll_down"):
            parsed = pp.parse_control({"action": action})
            assert parsed == (action, {})

    def test_touch_move_requires_coords(self):
        assert pp.parse_control({"action": "touch_move", "x": 0.5, "y": 0.5}) is not None
        assert pp.parse_control({"action": "touch_move", "x": 0.5}) is None

    def test_unknown_action_rejected(self):
        assert pp.parse_control({"action": "launch_missiles"}) is None

    def test_missing_action_rejected(self):
        assert pp.parse_control({"type": "ping"}) is None

    def test_test_touch_passes_message(self):
        action, kwargs = pp.parse_control({"action": "test_touch", "message": "hi"})
        assert action == "test_touch"
        assert kwargs["data"]["message"] == "hi"


def test_quiet_actions_only_mouse_move():
    assert pp.QUIET_ACTIONS == frozenset({"mouse_move"})
