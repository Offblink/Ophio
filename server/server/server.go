package server

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/rs/cors"
)

// ClientType 定义客户端类型
type ClientType string

const (
	ClientTypeBrowser ClientType = "browser"
	ClientTypeCapture ClientType = "capture"
	ClientTypeUnknown ClientType = "unknown"
)

// Client 表示一个WebSocket客户端连接
type Client struct {
	Conn     *websocket.Conn
	Type     ClientType
	RemoteIP string
	Send     chan OutMessage
	mu       sync.Mutex
}

// OutMessage WebSocket 输出消息，携带帧类型（Text/Binary）
type OutMessage struct {
	Type int
	Data []byte
}

// ControlCommand 控制命令结构
// X/Y/Dx/Dy 用指针表示：区分「未携带」与「数值为 0」，避免 omitempty 吞掉 0 坐标
type ControlCommand struct {
	Action    string   `json:"action"`
	Key       string   `json:"key,omitempty"`
	State     string   `json:"state,omitempty"`
	Timestamp float64  `json:"timestamp,omitempty"`
	Type      string   `json:"type,omitempty"`
	X         *float64 `json:"x,omitempty"`
	Y         *float64 `json:"y,omitempty"`
	Dx        *float64 `json:"dx,omitempty"`
	Dy        *float64 `json:"dy,omitempty"`
	Button    string   `json:"button,omitempty"`
	Amount    int      `json:"amount,omitempty"`
	Clicks    int      `json:"clicks,omitempty"`
}

// quietAction 判定高频静默流：不打日志、不回 ack，防止鼠标移动刷爆控制台
func quietAction(action string) bool {
	return action == "mouse_move"
}

// IdentityMessage 客户端标识消息
type IdentityMessage struct {
	Type         string  `json:"type"`
	Client       string  `json:"client,omitempty"`
	HasPyautogui bool    `json:"has_pyautogui,omitempty"`
	Platform     string  `json:"platform,omitempty"`
	Timestamp    float64 `json:"timestamp,omitempty"`
}

// Stats 统计信息
type Stats struct {
	FramesSent    int64
	ControlsSent  int64
	LastStatsTime time.Time
	mu            sync.RWMutex
}

// WebSocketServer WebSocket 服务器
type WebSocketServer struct {
	Port       int
	Clients    map[*Client]bool
	Broadcast  chan []byte
	Register   chan *Client
	Unregister chan *Client
	Stats      *Stats
	mu         sync.RWMutex
	upgrader   websocket.Upgrader
	listener   net.Listener
	server     *http.Server
	wg         sync.WaitGroup
	stopChan   chan struct{}
}

// NewWebSocketServer 创建新的 WebSocket 服务器
func NewWebSocketServer(port int) *WebSocketServer {
	return &WebSocketServer{
		Port:       port,
		Clients:    make(map[*Client]bool),
		Broadcast:  make(chan []byte, 256),
		Register:   make(chan *Client),
		Unregister: make(chan *Client),
		Stats: &Stats{
			LastStatsTime: time.Now(),
		},
		upgrader: websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool {
				return true // 允许所有跨域请求
			},
			ReadBufferSize:  1024,
			WriteBufferSize: 1024,
		},
		stopChan: make(chan struct{}),
	}
}

// Start 启动 WebSocket 服务器
func (s *WebSocketServer) Start() error {
	addr := fmt.Sprintf(":%d", s.Port)

	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleWebSocket)

	// 添加 CORS 支持
	handler := cors.New(cors.Options{
		AllowedOrigins:   []string{"*"},
		AllowedMethods:   []string{"GET", "POST", "OPTIONS"},
		AllowedHeaders:   []string{"Content-Type"},
		AllowCredentials: true,
	}).Handler(mux)

	s.server = &http.Server{
		Addr:    addr,
		Handler: handler,
	}

	// 启动 TCP 监听
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("监听端口失败: %v", err)
	}
	s.listener = listener

	// 启动消息处理协程
	s.wg.Add(1)
	go s.run()

	// 启动统计输出协程
	s.wg.Add(1)
	go s.printStats()

	log.Printf("WebSocket服务器正在监听%s\n", addr)
	return s.server.Serve(s.listener)
}

func (s *WebSocketServer) run() {
	defer s.wg.Done()

	for {
		select {
		case client := <-s.Register:
			s.mu.Lock()
			s.Clients[client] = true
			s.mu.Unlock()
			log.Printf("[新连接] 客户端已连接 (IP: %s)\n", client.RemoteIP)

			// 发送欢迎消息
			welcomeMsg := map[string]interface{}{
				"type":      "welcome",
				"message":   "连接成功",
				"timestamp": time.Now().Format(time.RFC3339),
			}
			if data, err := json.Marshal(welcomeMsg); err == nil {
				client.Send <- OutMessage{Type: websocket.TextMessage, Data: data}
			}

		case client := <-s.Unregister:
			s.mu.Lock()
			if _, ok := s.Clients[client]; ok {
				delete(s.Clients, client)
				close(client.Send)
				log.Printf("[断开] 客户端已断开 (类型: %s)\n", client.Type)
			}
			s.mu.Unlock()

		case message := <-s.Broadcast:
			s.mu.RLock()
			clients := make([]*Client, 0, len(s.Clients))
			for client := range s.Clients {
				clients = append(clients, client)
			}
			s.mu.RUnlock()

			for _, client := range clients {
				select {
				case client.Send <- OutMessage{Type: websocket.TextMessage, Data: message}:
				default:
					close(client.Send)
					s.mu.Lock()
					delete(s.Clients, client)
					s.mu.Unlock()
				}
			}

		case <-s.stopChan:
			return
		}
	}
}

func (s *WebSocketServer) printStats() {
	defer s.wg.Done()

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			s.Stats.mu.RLock()
			frames := s.Stats.FramesSent
			controls := s.Stats.ControlsSent
			s.Stats.FramesSent = 0
			s.Stats.ControlsSent = 0
			s.Stats.LastStatsTime = time.Now()
			s.Stats.mu.RUnlock()

			if frames > 0 || controls > 0 {
				log.Printf("[统计] 过去5秒发送%d帧 %d个控制指令\n", frames, controls)
			}

		case <-s.stopChan:
			return
		}
	}
}

func (s *WebSocketServer) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := s.upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket升级失败: %v\n", err)
		return
	}

	client := &Client{
		Conn:     conn,
		Type:     ClientTypeUnknown,
		RemoteIP: r.RemoteAddr,
		Send:     make(chan OutMessage, 256),
	}

	s.Register <- client

	// 启动写协程
	go s.writePump(client)

	// 读协程
	s.readPump(client)
}

func (s *WebSocketServer) readPump(client *Client) {
	defer func() {
		s.Unregister <- client
		client.Conn.Close()
	}()

	for {
		messageType, message, err := client.Conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Printf("读取错误: %v\n", err)
			}
			break
		}

		s.handleMessage(client, messageType, message)
	}
}

func (s *WebSocketServer) writePump(client *Client) {
	defer func() {
		client.Conn.Close()
	}()

	for {
		select {
		case message, ok := <-client.Send:
			if !ok {
				client.Conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			client.mu.Lock()
			err := client.Conn.WriteMessage(message.Type, message.Data)
			client.mu.Unlock()

			if err != nil {
				return
			}
		}
	}
}

func (s *WebSocketServer) handleMessage(client *Client, messageType int, message []byte) {
	// 尝试解析为JSON控制命令（优先处理）
	if len(message) > 0 && message[0] == '{' {
		var cmd ControlCommand
		if err := json.Unmarshal(message, &cmd); err == nil {
			// 如果有action字段，优先作为控制命令处理
			if cmd.Action != "" {
				quiet := quietAction(cmd.Action)
				if !quiet {
					log.Printf("[调试] 控制命令: Action='%s', 发送者类型: %s, 长度: %d\n", cmd.Action, client.Type, len(message))
				}
				s.handleControlCommand(client, cmd, quiet)
				return
			}

			// 如果没有action但有type字段，作为身份标识处理
			if cmd.Type == "browser" || cmd.Type == "capture" {
				client.Type = ClientType(cmd.Type)
				log.Printf("[标识] 客户端类型已设置: %s\n", client.Type)
				return
			}
		} else {
			log.Printf("[调试] JSON解析失败: %v\n", err)
		}
	}

	// 尝试解析为标识消息
	var identityMsg IdentityMessage
	if len(message) > 0 && message[0] == '{' {
		if err := json.Unmarshal(message, &identityMsg); err == nil {
			// 只有当消息没有action字段时才作为身份消息处理
			if identityMsg.Type == "browser" || identityMsg.Type == "capture" {
				// 检查是否已经设置过类型
				if client.Type == ClientTypeUnknown {
					client.Type = ClientType(identityMsg.Type)
					log.Printf("[标识] 客户端类型已设置: %s\n", client.Type)
					log.Printf("[标识] 客户端信息: %+v\n", identityMsg)
				}
				return
			}
		}
	}

	// 如果是图片数据，广播给浏览器客户端
	if len(message) > 1000 {
		log.Printf("[调试] 检测到图片数据，长度: %d\n", len(message))
		s.broadcastToBrowsers(messageType, message, client)
	} else if len(message) > 0 && message[0] == '{' {
		log.Printf("[警告] 未知的JSON消息格式: %q\n", message)
	}
}

func (s *WebSocketServer) handleControlCommand(client *Client, cmd ControlCommand, quiet bool) {
	if !quiet {
		if cmd.Action == "keyboard" {
			log.Printf("[键盘] %s - %s\n", cmd.Key, cmd.State)
		} else {
			log.Printf("[控制] 收到指令: %s\n", cmd.Action)
		}

		// 统计当前capture客户端数量
		s.mu.RLock()
		captureCount := 0
		for c := range s.Clients {
			if c.Type == ClientTypeCapture {
				captureCount++
				log.Printf("[调试] Capture客户端: %s\n", c.RemoteIP)
			}
		}
		s.mu.RUnlock()
		log.Printf("[调试] 当前Capture客户端总数: %d\n", captureCount)
	}

	// 转发控制命令给所有capture客户端
	s.broadcastToCaptureClients(cmd, client, quiet)

	// 发送确认（高频静默流不回 ack）
	if !quiet {
		ack := map[string]interface{}{
			"status":    "ok",
			"received":  map[string]interface{}{"action": cmd.Action, "key": cmd.Key},
			"timestamp": time.Now().Format(time.RFC3339),
		}
		if data, err := json.Marshal(ack); err == nil {
			client.Send <- OutMessage{Type: websocket.TextMessage, Data: data}
		}
	}

	s.Stats.mu.Lock()
	s.Stats.ControlsSent++
	s.Stats.mu.Unlock()
}

func (s *WebSocketServer) broadcastToBrowsers(messageType int, data []byte, sender *Client) {
	broadcastCount := 0

	s.mu.RLock()
	defer s.mu.RUnlock()

	for client := range s.Clients {
		if client != sender && client.Type == ClientTypeBrowser {
			select {
			case client.Send <- OutMessage{Type: messageType, Data: data}:
				broadcastCount++
			default:
				// 发送失败，关闭连接
				close(client.Send)
				delete(s.Clients, client)
			}
		}
	}

	s.Stats.mu.Lock()
	s.Stats.FramesSent++
	s.Stats.mu.Unlock()
}

func (s *WebSocketServer) broadcastToCaptureClients(cmd ControlCommand, sender *Client, quiet bool) {
	sendCount := 0

	cmdData, err := json.Marshal(cmd)
	if err != nil {
		log.Printf("[错误] 序列化命令失败: %v\n", err)
		return
	}

	s.mu.RLock()
	defer s.mu.RUnlock()

	for client := range s.Clients {
		if client != sender && client.Type == ClientTypeCapture {
			if !quiet {
				log.Printf("[控制] 发送给Capture客户端: %s", client.RemoteIP)
			}
			select {
			case client.Send <- OutMessage{Type: websocket.TextMessage, Data: cmdData}:
				sendCount++
				if !quiet {
					log.Printf("[控制] 发送成功: %s", client.RemoteIP)
				}
			default:
				log.Printf("[警告] 发送失败，关闭连接: %s", client.RemoteIP)
				close(client.Send)
				delete(s.Clients, client)
			}
		}
	}

	if quiet {
		return
	}

	if sendCount > 0 {
		log.Printf("[控制] 已转发给%d个capture客户端\n", sendCount)
	} else {
		log.Printf("[警告] 没有capture客户端可发送命令！\n")
		s.mu.RLock()
		log.Printf("[调试] 当前所有客户端:")
		for c := range s.Clients {
			log.Printf("  - %s (类型: %s)", c.RemoteIP, c.Type)
		}
		s.mu.RUnlock()
	}
}

// Stop 停止WebSocket服务器
func (s *WebSocketServer) Stop() {
	close(s.stopChan)

	if s.listener != nil {
		s.listener.Close()
	}

	if s.server != nil {
		s.server.Close()
	}

	s.wg.Wait()

	// 关闭所有客户端连接
	s.mu.Lock()
	for client := range s.Clients {
		close(client.Send)
		client.Conn.Close()
	}
	s.Clients = make(map[*Client]bool)
	s.mu.Unlock()

	log.Println("WebSocket服务器已停止")
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
