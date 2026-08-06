// ophio-go-server\main.go
package main

import (
    "context"
    "fmt"
    "log"
    "net"
    "net/http"
    "os"
    "os/signal"
    "strings"
    "syscall"
    "time"
    
    "ophio-go-server/server"
)

const (
    HTTP_PORT  = 8888
    WS_PORT    = 8889
    STATIC_DIR = "public"  // Windows 路径，无前导点
)

var startTime = time.Now()

func main() {
    // 设置控制台编码为 UTF-8（Windows 需要）
    enableUTF8()
    
    printBanner()
    
    // 确保静态目录存在
    if _, err := os.Stat(STATIC_DIR); os.IsNotExist(err) {
        log.Printf("创建静态文件目录: %s", STATIC_DIR)
        os.MkdirAll(STATIC_DIR, 0755)
        createDefaultIndexHTML()
    }
    
    // 检查端口占用
    if isPortInUse(HTTP_PORT) {
        log.Printf("❌ HTTP 端口 %d 已被占用", HTTP_PORT)
        showPortProcessInfo(HTTP_PORT)
        return
    }
    
    if isPortInUse(WS_PORT) {
        log.Printf("❌ WebSocket 端口 %d 已被占用", WS_PORT)
        showPortProcessInfo(WS_PORT)
        return
    }
    
    // 启动 WebSocket 服务器
    wsServer := server.NewWebSocketServer(WS_PORT)
    go func() {
        log.Printf("启动 WebSocket 服务器 (端口: %d)", WS_PORT)
        if err := wsServer.Start(); err != nil && err != http.ErrServerClosed {
            log.Fatalf("WebSocket 服务器启动失败: %v", err)
        }
    }()
    
    // 启动 HTTP 服务器
    httpServer := server.NewHTTPServer(HTTP_PORT, STATIC_DIR, wsServer)
    go func() {
        log.Printf("启动 HTTP 服务器 (端口: %d)", HTTP_PORT)
        if err := httpServer.Start(); err != nil && err != http.ErrServerClosed {
            log.Fatalf("HTTP 服务器启动失败: %v", err)
        }
    }()
    
    // 等待启动
    time.Sleep(500 * time.Millisecond)
    
    // 打印访问信息
    printNetworkInfo(HTTP_PORT)
    
    // 等待中断信号
    waitForInterrupt(wsServer, httpServer)
}

func enableUTF8() {
    // Windows 控制台 UTF-8 支持
    // 在 Windows 10/11 中，控制台通常已支持 UTF-8
    // 如果需要，可以添加 chcp 65001 调用
}

func printBanner() {
    fmt.Println(strings.Repeat("=", 60))
    fmt.Println("            Ophio 屏幕共享服务器 (Go Windows 版)")
    fmt.Println(strings.Repeat("=", 60))
    fmt.Printf("HTTP 服务端口:     %d\n", HTTP_PORT)
    fmt.Printf("WebSocket 端口:    %d\n", WS_PORT)
    fmt.Printf("静态文件目录:     %s\n", STATIC_DIR)
    fmt.Println(strings.Repeat("=", 60))
    fmt.Println("启动时间:", time.Now().Format("2006-01-02 15:04:05"))
    fmt.Println(strings.Repeat("=", 60))
    fmt.Println()
}

func printNetworkInfo(httpPort int) {
    fmt.Println("[网络信息] 可通过以下地址访问:")
    fmt.Printf("  本地访问:    http://localhost:%d\n", httpPort)
    
    // 获取本机 IP
    addrs, err := net.InterfaceAddrs()
    if err != nil {
        log.Printf("获取网络地址失败: %v", err)
        return
    }
    
    fmt.Println("  局域网访问:")
    for _, addr := range addrs {
        if ipNet, ok := addr.(*net.IPNet); ok && !ipNet.IP.IsLoopback() {
            if ipNet.IP.To4() != nil {
                fmt.Printf("              http://%s:%d\n", ipNet.IP.String(), httpPort)
            }
        }
    }
    fmt.Println()
    fmt.Println("提示: 在手机浏览器中输入上述局域网地址即可访问")
    fmt.Println(strings.Repeat("-", 60))
}

func isPortInUse(port int) bool {
    timeout := time.Second
    conn, err := net.DialTimeout("tcp", fmt.Sprintf(":%d", port), timeout)
    if err != nil {
        return false
    }
    if conn != nil {
        conn.Close()
        return true
    }
    return false
}

func showPortProcessInfo(port int) {
    // Windows 查看端口占用: netstat -ano | findstr :端口号
    fmt.Printf("查看端口 %d 占用: netstat -ano | findstr :%d\n", port, port)
    fmt.Println("结束进程: taskkill /F /PID 进程号")
}

func waitForInterrupt(wsServer *server.WebSocketServer, httpServer *server.HTTPServer) {
    // Windows 信号处理
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, 
        syscall.SIGINT,    // Ctrl+C
        syscall.SIGTERM,   // 系统终止
        os.Interrupt,      // 中断信号
    )
    
    fmt.Println("\n[提示] 按 Ctrl+C 停止服务器")
    <-sigChan
    
    fmt.Println("\n" + strings.Repeat("=", 60))
    fmt.Println("正在停止服务器...")
    
    // 停止 WebSocket 服务器
    if wsServer != nil {
        wsServer.Stop()
    }
    
    // 停止 HTTP 服务器
    if httpServer != nil {
        ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
        defer cancel()
        httpServer.Stop(ctx)
    }
    
    fmt.Println("服务器已安全停止")
    fmt.Println(strings.Repeat("=", 60))
}

func createDefaultIndexHTML() {
    htmlContent := `<!DOCTYPE html>
<html>
<head>
    <title>Ophio - Windows 屏幕共享</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: #fff;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px;
            max-width: 800px;
            width: 100%;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        header {
            text-align: center;
            margin-bottom: 30px;
        }
        h1 {
            color: #00d4ff;
            font-size: 2.8em;
            margin-bottom: 10px;
            text-shadow: 0 2px 10px rgba(0, 212, 255, 0.3);
        }
        .subtitle {
            color: #a0a0ff;
            font-size: 1.2em;
            margin-bottom: 20px;
        }
        .info-box {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 15px;
            padding: 25px;
            margin: 20px 0;
            border-left: 5px solid #00d4ff;
        }
        .info-box h3 {
            color: #00d4ff;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .info-box h3 i {
            font-size: 1.3em;
        }
        .url-list {
            list-style: none;
            padding: 0;
        }
        .url-list li {
            background: rgba(255, 255, 255, 0.05);
            margin: 10px 0;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
        }
        .url-list li:hover {
            background: rgba(0, 212, 255, 0.1);
            border-color: #00d4ff;
            transform: translateX(5px);
        }
        .url-list code {
            font-family: 'Consolas', 'Courier New', monospace;
            background: rgba(0, 0, 0, 0.5);
            padding: 5px 10px;
            border-radius: 4px;
            color: #00ffaa;
            font-size: 1.1em;
            display: block;
            margin: 5px 0;
        }
        .url-list .label {
            color: #a0a0ff;
            font-size: 0.9em;
            display: block;
            margin-bottom: 5px;
        }
        .status {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 20px 0;
            padding: 15px;
            background: rgba(0, 255, 0, 0.1);
            border-radius: 10px;
            border: 1px solid rgba(0, 255, 0, 0.3);
        }
        .status-dot {
            width: 12px;
            height: 12px;
            background: #00ff00;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        .note {
            background: rgba(255, 255, 0, 0.1);
            border-left: 5px solid #ffff00;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            color: #ffffaa;
        }
        .instructions {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }
        .instructions h3 {
            color: #ff6b6b;
            margin-bottom: 15px;
        }
        .instructions ol {
            margin-left: 20px;
            line-height: 1.8;
        }
        footer {
            text-align: center;
            margin-top: 30px;
            color: #888;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🖥️ Ophio 屏幕共享</h1>
            <div class="subtitle">Windows 系统 | Go 语言服务器 | 实时屏幕控制</div>
        </header>
        
        <div class="status">
            <div class="status-dot"></div>
            <strong>服务器运行正常</strong>
        </div>
        
        <div class="info-box">
            <h3>🌐 访问地址</h3>
            <ul class="url-list">
                <li>
                    <span class="label">本地计算机访问：</span>
                    <code>http://localhost:8888</code>
                </li>
                <li>
                    <span class="label">手机/平板访问（需在同一网络）：</span>
                    <code>http://YOUR_WINDOWS_IP:8888</code>
                    <small style="color: #aaa; display: block; margin-top: 5px;">
                        * 将 YOUR_WINDOWS_IP 替换为上面显示的实际 IP 地址
                    </small>
                </li>
            </ul>
        </div>
        
        <div class="info-box">
            <h3>🔧 服务状态</h3>
            <ul class="url-list">
                <li><strong>HTTP 服务器：</strong>端口 8888 ✓ 运行中</li>
                <li><strong>WebSocket 服务：</strong>端口 8889 ✓ 运行中</li>
                <li><strong>服务器版本：</strong>Go 1.21+</li>
                <li><strong>系统平台：</strong>Windows</li>
            </ul>
        </div>
        
        <div class="instructions">
            <h3>📱 使用说明</h3>
            <ol>
                <li>确保手机/平板与 Windows 电脑连接同一 Wi-Fi 网络</li>
                <li>在手机浏览器中输入上方显示的 IP 地址（如 http://192.168.1.100:8888）</li>
                <li>页面将显示实时屏幕画面和控制界面</li>
                <li>如需控制权限，请在页面中点击"获取控制权"</li>
            </ol>
        </div>
        
        <div class="note">
            <strong>注意：</strong>这是 Go 语言版本的服务器。如需完整功能，请从原 Python 项目复制 <code>index.html</code> 文件到此目录的 public 文件夹中。
        </div>
        
        <footer>
            <p>Ophio Screen Share Server for Windows | © 2024</p>
            <p>按 Ctrl+C 停止服务器</p>
        </footer>
    </div>
</body>
</html>`
    
    os.WriteFile(STATIC_DIR+"\\index.html", []byte(htmlContent), 0644)
    log.Printf("已创建默认首页: %s\\index.html", STATIC_DIR)
}