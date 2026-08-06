@echo off
chcp 65001 >nul
title 屏幕共享控制端 (键盘增强版)
color 0A

echo ========================================
echo    屏幕共享控制端 - 键盘增强版
echo ========================================
echo.

echo 1. 启动服务器...
start "服务器" cmd /k "node server.js"
timeout /t 3 /nobreak >nul

echo 2. 启动屏幕捕获与控制...
start "屏幕捕获" cmd /k "python screen_capture.py"

echo.
echo ========================================
echo 启动完成！
echo.
echo 访问: http://localhost:8888
echo 更新功能:
echo   - Enter键修正为普通功能键
echo   - 新增Backspace退格键
echo   - 特殊键: Ctrl, Shift, Win
echo   - 组合键自动释放
echo ========================================
echo.
echo 按任意键停止服务...
pause >nul

echo.
echo 正在停止服务...
taskkill /F /FI "WINDOWTITLE eq 服务器" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq 屏幕捕获" /T 2>nul
echo 服务已停止
timeout /t 2 /nobreak >nul