// server.js
const WebSocket = require('ws');
const express = require('express');
const http = require('http');

// 配置
const CONFIG = {
    HTTP_PORT: 8888,
    WEBSOCKET_PORT: 8889
};

// 创建HTTP服务器用于提供前端页面
const app = express();
const server = http.createServer(app);

// 静态文件服务
app.use(express.static('public'));

// 创建WebSocket服务器
const wss = new WebSocket.Server({ port: CONFIG.WEBSOCKET_PORT });

// 存储所有连接的客户端
let clients = [];

// 启动信息
console.log('='.repeat(60));
console.log('屏幕共享服务器已启动');
console.log('='.repeat(60));
console.log(`HTTP 服务器: http://localhost:${CONFIG.HTTP_PORT}`);
console.log(`WebSocket 服务器: ws://localhost:${CONFIG.WEBSOCKET_PORT}`);
console.log('='.repeat(60));
console.log('等待客户端连接...\n');

// 统计信息
let stats = {
    framesSent: 0,
    controlsSent: 0,
    lastStatsTime: Date.now()
};

// WebSocket服务器事件处理
wss.on('connection', (ws, req) => {
    console.log(`[新连接] 客户端已连接 (IP: ${req.socket.remoteAddress})`);
    
    ws.clientType = 'unknown';
    clients.push(ws);
    
    // 发送欢迎消息
    setTimeout(() => {
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'welcome',
                message: '连接成功',
                timestamp: new Date().toISOString()
            }));
        }
    }, 100);
    
    // 接收消息
    ws.on('message', (message) => {
        try {
            const messageString = message.toString();
            
            // 检查是否是JSON（控制命令）
            if (messageString.startsWith('{')) {
                try {
                    const data = JSON.parse(messageString);
                    
                    // 如果是客户端标识
                    if (data.type === 'browser' || data.type === 'capture') {
                        ws.clientType = data.type;
                        console.log(`[标识] 客户端类型: ${ws.clientType}`);
                        return;
                    }
                    
                    // 如果是控制命令
                    if (data.action) {
                        if (data.action === 'keyboard') {
                            console.log(`[键盘] ${data.key} - ${data.state}`);
                        } else {
                            console.log(`[控制] 收到指令: ${data.action}`);
                        }
                        
                        // 转发控制命令给所有capture客户端
                        broadcastToCaptureClients(data, ws);
                        
                        ws.send(JSON.stringify({ 
                            status: 'ok', 
                            received: { action: data.action, key: data.key },
                            timestamp: new Date().toISOString()
                        }));
                        
                        stats.controlsSent++;
                        return;
                    }
                } catch (jsonError) {
                    // 忽略JSON解析错误
                }
            }
            
            // 如果是图片数据，广播给浏览器客户端
            if (messageString.length > 1000) {
                broadcastToBrowsers(messageString, ws);
            }
            
        } catch (error) {
            // 静默处理错误
        }
    });
    
    ws.on('close', () => {
        console.log(`[断开] 客户端已断开 (类型: ${ws.clientType})`);
        clients = clients.filter(client => client !== ws);
    });
    
    ws.on('error', () => {
        // 静默处理错误
    });
});

// 广播给浏览器客户端
function broadcastToBrowsers(data, sender) {
    let broadcastCount = 0;
    
    clients.forEach(client => {
        if (client !== sender && 
            client.clientType === 'browser' && 
            client.readyState === WebSocket.OPEN) {
            try {
                client.send(data);
                broadcastCount++;
            } catch (error) {
                // 静默处理发送错误
            }
        }
    });
    
    stats.framesSent++;
    
    // 每5秒输出一次统计信息
    const now = Date.now();
    if (now - stats.lastStatsTime > 5000) {
        console.log(`[统计] 过去5秒发送 ${stats.framesSent} 帧, ${stats.controlsSent} 控制指令`);
        stats.framesSent = 0;
        stats.controlsSent = 0;
        stats.lastStatsTime = now;
    }
}

// 广播控制命令给capture客户端
function broadcastToCaptureClients(command, sender) {
    let sendCount = 0;
    
    clients.forEach(client => {
        if (client !== sender && 
            client.clientType === 'capture' && 
            client.readyState === WebSocket.OPEN) {
            try {
                client.send(JSON.stringify(command));
                sendCount++;
            } catch (error) {
                // 静默处理发送错误
            }
        }
    });
    
    if (sendCount > 0) {
        console.log(`[控制] 已转发给 ${sendCount} 个capture客户端`);
    }
}

// 启动HTTP服务器
server.listen(CONFIG.HTTP_PORT, () => {
    const os = require('os');
    const networkInterfaces = os.networkInterfaces();
    let localIp = 'localhost';
    
    Object.keys(networkInterfaces).forEach((interfaceName) => {
        networkInterfaces[interfaceName].forEach((iface) => {
            if (iface.family === 'IPv4' && !iface.internal) {
                localIp = iface.address;
            }
        });
    });
    
    console.log(`[信息] 服务器IP: ${localIp}`);
    console.log(`[信息] 手机访问: http://${localIp}:${CONFIG.HTTP_PORT}`);
    console.log('='.repeat(60) + '\n');
});

// 优雅关闭
process.on('SIGINT', () => {
    console.log('\n[关闭] 正在停止服务器...');
    wss.close();
    server.close();
    process.exit();
});