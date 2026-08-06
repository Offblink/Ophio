# test_connection.py
import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8889"
    
    print(f"尝试连接到: {uri}")
    print("="*50)
    
    try:
        # 尝试连接
        async with websockets.connect(uri, timeout=5) as websocket:
            print("✓ 连接成功!")
            
            # 发送测试消息
            test_message = {
                "type": "test",
                "message": "测试连接",
                "timestamp": "2024-01-01T00:00:00Z"
            }
            await websocket.send(json.dumps(test_message))
            print("✓ 测试消息已发送")
            
            # 等待响应
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3)
                print(f"✓ 收到响应: {response}")
            except asyncio.TimeoutError:
                print("⚠ 未收到响应，但连接正常")
                
    except ConnectionRefusedError:
        print("✗ 连接被拒绝")
        print("可能原因:")
        print("1. WebSocket服务器未运行")
        print("2. 端口8889被占用")
        print("3. 防火墙阻止了连接")
        
    except Exception as e:
        print(f"✗ 连接失败: {e}")
        print(f"错误类型: {type(e).__name__}")
        
    print("="*50)

if __name__ == "__main__":
    asyncio.run(test_websocket())