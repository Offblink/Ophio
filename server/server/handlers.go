package server

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "net"
    "net/http"
    "os"
    "path/filepath"
    "time"
    
    "github.com/gorilla/mux"
)

// HTTPServer HTTP 服务器
type HTTPServer struct {
    Port       int
    StaticDir  string
    WSServer   *WebSocketServer
    server     *http.Server
    router     *mux.Router
}

// NewHTTPServer 创建新的 HTTP 服务器
func NewHTTPServer(port int, staticDir string, wsServer *WebSocketServer) *HTTPServer {
    router := mux.NewRouter()
    
    s := &HTTPServer{
        Port:      port,
        StaticDir: staticDir,
        WSServer:  wsServer,
        router:    router,
    }
    
    // 设置路由
    s.setupRoutes()
    
    s.server = &http.Server{
        Addr:         fmt.Sprintf(":%d", port),
        Handler:      router,
        ReadTimeout:  10 * time.Second,
        WriteTimeout: 10 * time.Second,
        IdleTimeout:  120 * time.Second,
    }
    
    return s
}

func (s *HTTPServer) setupRoutes() {
    // 静态文件服务
    s.router.PathPrefix("/").Handler(http.StripPrefix("/", 
        http.FileServer(http.Dir(s.StaticDir))))
    
    // API 端点
    s.router.HandleFunc("/api/info", s.handleAPIInfo).Methods("GET")
    s.router.HandleFunc("/api/stats", s.handleAPIStats).Methods("GET")
    s.router.HandleFunc("/api/clients", s.handleAPIClients).Methods("GET")
    
    // 健康检查
    s.router.HandleFunc("/health", s.handleHealthCheck).Methods("GET")
    
    // 主页面
    s.router.HandleFunc("/", s.handleIndex)
}

func (s *HTTPServer) handleIndex(w http.ResponseWriter, r *http.Request) {
    // 如果请求的是根路径，尝试提供 index.html
    indexPath := filepath.Join(s.StaticDir, "index.html")
    if _, err := os.Stat(indexPath); err == nil {
        http.ServeFile(w, r, indexPath)
    } else {
        // 如果 index.html 不存在，返回默认页面
        s.handleDefaultPage(w, r)
    }
}

func (s *HTTPServer) handleDefaultPage(w http.ResponseWriter, r *http.Request) {
    html := `<!DOCTYPE html>
<html>
<head>
    <title>Ophio Screen Share</title>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            margin: 40px; 
            background: #f5f5f5; 
        }
        .container { 
            max-width: 800px; 
            margin: 0 auto; 
            background: white; 
            padding: 20px; 
            border-radius: 8px; 
            box-shadow: 0 2px 10px rgba(0,0,0,0.1); 
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Ophio Screen Share Server</h1>
        <p>This is the Go version of Ophio screen share server.</p>
        <p>Please place the full frontend files in the <code>public</code> directory.</p>
    </div>
</body>
</html>`
    
    w.Header().Set("Content-Type", "text/html; charset=utf-8")
    w.WriteHeader(http.StatusOK)
    fmt.Fprint(w, html)
}

func (s *HTTPServer) handleHealthCheck(w http.ResponseWriter, r *http.Request) {
    response := map[string]interface{}{
        "status":    "ok",
        "timestamp": time.Now().Unix(),
        "service":   "ophio-go-server",
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(response)
    
    // 记录访问日志
    log.Printf("[HTTP] Health check from %s", r.RemoteAddr)
}

func (s *HTTPServer) handleAPIInfo(w http.ResponseWriter, r *http.Request) {
    info := map[string]interface{}{
        "name":        "Ophio Screen Share Server",
        "version":     "1.0.0",
        "language":    "Go",
        "http_port":   s.Port,
        "ws_port":     s.WSServer.Port,
        "static_dir":  s.StaticDir,
        "timestamp":   time.Now().Format(time.RFC3339),
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(info)
    
    // 记录访问日志
    log.Printf("[HTTP] API Info request from %s", r.RemoteAddr)
}

func (s *HTTPServer) handleAPIStats(w http.ResponseWriter, r *http.Request) {
    // 从 WebSocket 服务器获取统计信息
    clientCount := 0
    if s.WSServer != nil {
        s.WSServer.mu.RLock()
        clientCount = len(s.WSServer.Clients)
        s.WSServer.mu.RUnlock()
    }
    
    stats := map[string]interface{}{
        "clients_count":   clientCount,
        "timestamp":       time.Now().Format(time.RFC3339),
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(stats)
    
    // 记录访问日志
    log.Printf("[HTTP] Stats request from %s", r.RemoteAddr)
}

func (s *HTTPServer) handleAPIClients(w http.ResponseWriter, r *http.Request) {
    clients := []map[string]interface{}{}
    
    if s.WSServer != nil {
        s.WSServer.mu.RLock()
        for client := range s.WSServer.Clients {
            clients = append(clients, map[string]interface{}{
                "remote_ip": client.RemoteIP,
                "type":      client.Type,
            })
        }
        s.WSServer.mu.RUnlock()
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(clients)
    
    // 记录访问日志
    log.Printf("[HTTP] Clients list request from %s", r.RemoteAddr)
}

// Start 启动 HTTP 服务器
func (s *HTTPServer) Start() error {
    addr := s.server.Addr
    if addr == "" {
        addr = fmt.Sprintf(":%d", s.Port)
    }
    
    // 获取网络地址信息
    addrs, err := net.InterfaceAddrs()
    if err == nil {
        log.Println("[HTTP] 服务器网络地址:")
        for _, addr := range addrs {
            if ipNet, ok := addr.(*net.IPNet); ok && !ipNet.IP.IsLoopback() {
                if ipNet.IP.To4() != nil {
                    log.Printf("  - http://%s:%d", ipNet.IP.String(), s.Port)
                }
            }
        }
    }
    
    log.Printf("[HTTP] 服务器正在监听 %s", addr)
    return s.server.ListenAndServe()
}

// Stop 停止 HTTP 服务器
func (s *HTTPServer) Stop(ctx context.Context) error {
    if s.server != nil {
        return s.server.Shutdown(ctx)
    }
    return nil
}