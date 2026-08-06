@echo off
chcp 65001 >nul
echo =====================
echo     Ophio Windows 
echo =====================
echo.

echo [1/3] Checking Runtime...
where go >nul 2>&1
if errorlevel 1 (
    echo No Found Go...
    echo  https://golang.org/dl/ For Go
    pause
    exit /b 1
)

echo [2/3] Downloading...
go mod tidy
if errorlevel 1 (
    echo Failed...
    echo Proxy: go env -w GOPROXY=https://goproxy.cn,direct
    pause
    exit /b 1
)

echo [3/3] Compiling...
go build -o ophio-server.exe .
if errorlevel 1 (
    echo Failed
    pause
    exit /b 1
)

echo.
echo Success!
pause