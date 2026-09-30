# Ophio

**Ophio** lets you control your Windows PC from another device over LAN — screen sharing plus real mouse and keyboard. An upgrade for ***NoGame***.

**下载** → [Releases](https://github.com/Offblink/Ophio/releases)：**`Ophio-v0.1.1-full.rar`**，解压即用，不需要安装 Python（SHA256 见 release notes）。

## 快速开始

1. 下载并解压 `Ophio-v0.1.1-full.rar`
2. 双击 `Ophio.exe`，点「启动服务」
3. 用另一台设备的浏览器打开 `http://<主机IP>:8888`（启动窗口会列出局域网地址和二维码）

## 两个控制页

| 谁打开 | 页面 | 怎么操作 |
|---|---|---|
| 手机浏览器 | `index.html` | 底部按钮：左/右键、滚动、虚拟键盘 |
| 电脑浏览器 | `pc.html` | 整面共享屏幕、无按钮：鼠标悬停即接管，左/右/中键、拖拽、滚轮、键盘直接用 |

- 桌面浏览器自动进 PC 页，手机自动进移动页；`?view=pc` / `?view=mobile` 可强制指定
- PC 页按 **Esc** 释放全部按键并暂停控制；移出画面再移回即恢复

## 组成

| 文件 | 作用 |
|---|---|
| `Ophio.exe` | PyQt5 客户端：启动服务、捕获屏幕、系统托盘；屏幕捕获已内置其中 |
| `ophio-server.exe` | Go 服务器：HTTP `:8888` 发网页，WebSocket `:8889` 转发画面与控制指令 |
| `public/` | 两个控制页（`index.html`、`pc.html`） |
| `Ophio.pyw`、`screen_capture.py`、`pc_protocol.py` | 源码，也随 rar 一起发布，方便二次开发 |

传输特性：JPEG 二进制帧、画面静止不发帧、网络落后时丢弃过期帧、单实例启动（重复双击会唤醒已有窗口）。

## 从源码运行（开发）

```bat
server\build.bat        :: 编译 Go 服务器 → ophio-server.exe
python Ophio.pyw        :: 启动客户端
package.bat             :: PyInstaller 打包客户端
```

门禁：`ruff check .`、`pytest`（配置在 `pyproject.toml`，测试在 `tests/`）。

## 仓库结构

- `Ophio.pyw` — 客户端主程序（窗口、托盘、子进程管理）
- `screen_capture.py` — 屏幕捕获与控制指令执行
- `pc_protocol.py` — 控制指令解析、键鼠映射
- `public/` — 网页控制端
- `server/` — Go 服务器（`build.bat` 编译）
- `legacy/` — 旧版 JavaScript 服务器，仅作存档
- `tests/` — pytest 测试

更新日志见 [Releases](https://github.com/Offblink/Ophio/releases) 与提交历史。

---

**Blivno** · 19.4.2026
