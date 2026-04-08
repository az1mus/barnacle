# -*- coding: utf-8 -*-
"""
Barnacle MCP Server 单元测试。

测试范围：
1. 模拟 Chrome Extension WebSocket 服务器
2. 模拟 MCP Client 与 MCP Server 通信
3. ExtensionBridge WebSocket 客户端测试
4. MCP Tools (fetch, close, clear_cache) 功能测试
5. 内容提取器测试
6. 错误处理和边界情况

使用生产端口：
- WebSocket: 9877 (Extension Bridge)
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import websockets

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.extension_bridge import ExtensionBridge, TaskResult, FetchTask
from server.types import ResponseResult
from server.extractor import extract_content

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 生产环境端口
WS_PORT = 9877
WS_URL = f"ws://localhost:{WS_PORT}"


# ============================================================================
# 模拟 Chrome Extension WebSocket 服务器
# ============================================================================

class MockExtensionClient:
    """
    模拟 Chrome Extension WebSocket 客户端。
    
    用于连接到 ExtensionBridge WebSocket 服务器并模拟扩展行为。
    """

    def __init__(self, ws_url: str = WS_URL):
        self.ws_url = ws_url
        self.ws = None
        self.received_messages = []
        self._task_results: Dict[str, Dict[str, Any]] = {}
        self._should_respond = True
        self._response_delay = 0.0
        self._running = False

    async def connect(self):
        """连接到 ExtensionBridge 服务器。"""
        self.ws = await websockets.connect(self.ws_url)
        self._running = True
        # 发送 ready 消息
        await self.ws.send(json.dumps({"type": "ready"}))
        logger.info(f"Mock extension connected to {self.ws_url}")

    async def disconnect(self):
        """断开连接。"""
        if self.ws:
            await self.ws.close()
            self.ws = None
        self._running = False
        logger.info("Mock extension disconnected")

    async def listen_and_respond(self, timeout: float = 5.0):
        """监听任务并响应。"""
        try:
            message = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            self.received_messages.append(message)
            data = json.loads(message)
            
            if data.get("type") == "task":
                task = data["task"]
                task_id = task["id"]
                url = task["url"]
                options = task.get("options", {})
                
                logger.info(f"Extension received task: {task_id} for {url}")
                
                if self._response_delay > 0:
                    await asyncio.sleep(self._response_delay)
                
                if self._should_respond:
                    result = self._task_results.get(task_id)
                    if result is None:
                        result = {
                            "type": "result",
                            "taskId": task_id,
                            "success": True,
                            "url": url,
                            "finalUrl": url,
                            "status": 200,
                            "content": [
                                {
                                    "content": "<html><body><article><h1>Test Page</h1><p>This is test content.</p></article></body></html>",
                                    "type": "html"
                                }
                            ],
                            "error": None,
                            "duration": 1000.0
                        }
                    
                    await self.ws.send(json.dumps(result))
                    logger.info(f"Extension sent result for task: {task_id}")
        except asyncio.TimeoutError:
            pass
        except websockets.exceptions.ConnectionClosed:
            pass

    def set_task_result(self, task_id: str, result: Dict[str, Any]):
        """预设特定任务的返回结果。"""
        self._task_results[task_id] = result

    def set_should_respond(self, should: bool):
        """设置是否自动响应。"""
        self._should_respond = should

    def set_response_delay(self, delay: float):
        """设置响应延迟（模拟慢速响应）。"""
        self._response_delay = delay

    def clear_messages(self):
        """清除接收的消息记录。"""
        self.received_messages.clear()


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def bridge():
    """创建并启动 ExtensionBridge 服务器。"""
    import server.extension_bridge as bridge_module
    bridge_module._bridge = None
    
    bridge_instance = ExtensionBridge(host="localhost", port=WS_PORT)
    await bridge_instance.start()
    
    # 设置全局实例
    bridge_module._bridge = bridge_instance
    
    yield bridge_instance
    await bridge_instance.stop()
    bridge_module._bridge = None


@pytest_asyncio.fixture
async def mock_extension(bridge):
    """启动模拟扩展客户端。"""
    client = MockExtensionClient(ws_url=WS_URL)
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
def sample_html():
    """示例 HTML 内容。"""
    return """
    <html>
        <body>
            <nav>Navigation Menu</nav>
            <header>Site Header</header>
            <article>
                <h1>Main Title</h1>
                <p>This is the main content paragraph.</p>
                <p>Another paragraph with more text.</p>
            </article>
            <footer>Site Footer</footer>
            <script>alert('noise');</script>
        </body>
    </html>
    """


@pytest.fixture
def sample_mcp_response():
    """示例 MCP fetch 响应。"""
    return {
        "success": True,
        "url": "https://example.com",
        "status": 200,
        "content": ["# Main Title\n\nThis is the main content paragraph.\n\nAnother paragraph with more text."],
        "selector": None,
        "error": None
    }


# ============================================================================
# 测试 ExtensionBridge WebSocket 通信
# ============================================================================

class TestExtensionBridge:
    """测试 ExtensionBridge 与扩展的 WebSocket 通信。"""

    @pytest.mark.asyncio
    async def test_bridge_connect_and_ready(self, bridge, mock_extension):
        """测试桥接连接并收到 ready 消息。"""
        assert bridge.is_connected
        assert len(bridge.ws_clients) > 0

    @pytest.mark.asyncio
    async def test_bridge_fetch_success(self, bridge, mock_extension):
        """测试成功获取页面内容。"""
        # 启动后台监听
        listen_task = asyncio.create_task(mock_extension.listen_and_respond())
        
        url = "https://example.com"
        options = {"timeout": 60000, "wait": 0, "cssSelector": None, "autoFilter": True}
        
        result = await bridge.fetch(url=url, options=options, timeout=10.0)
        
        # 等待监听完成
        await listen_task
        
        assert result.success is True
        assert result.url == url
        assert result.status == 200
        assert len(result.content) > 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_bridge_fetch_timeout(self, bridge, mock_extension):
        """测试获取超时。"""
        # 设置扩展不响应
        mock_extension.set_should_respond(False)
        
        url = "https://slow-example.com"
        options = {"timeout": 60000, "wait": 0}
        
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await bridge.fetch(url=url, options=options, timeout=0.5)

    @pytest.mark.asyncio
    async def test_bridge_connection_status(self, bridge, mock_extension):
        """测试连接状态检查。"""
        assert bridge.is_connected is True
        
        await mock_extension.disconnect()
        await asyncio.sleep(0.5)  # Wait for disconnect
        # Bridge server still running but no clients
        assert bridge.is_connected is False

    @pytest.mark.asyncio
    async def test_bridge_reconnect(self, bridge):
        """测试重新连接。"""
        # First connection
        client1 = MockExtensionClient()
        await client1.connect()
        assert bridge.is_connected
        
        await client1.disconnect()
        await asyncio.sleep(0.3)
        
        # Second connection
        client2 = MockExtensionClient()
        await client2.connect()
        assert bridge.is_connected
        
        await client2.disconnect()


# ============================================================================
# 测试 MCP Server Tools
# ============================================================================

class TestMCPTools:
    """测试 MCP Server 的工具功能。"""

    @pytest.mark.asyncio
    async def test_fetch_tool_success(self, bridge, mock_extension):
        """测试 fetch 工具成功场景。"""
        from server.server import fetch
        
        # 启动后台监听
        listen_task = asyncio.create_task(mock_extension.listen_and_respond())
        
        url = "https://example.com"
        result = await fetch(
            url=url,
            extraction_type="markdown",
            auto_filter=True,
            timeout=60000,
            wait=0,
            css_selector=None,
            active=True,
            keep_open=False,
        )
        
        await listen_task
        
        assert isinstance(result, dict)
        assert "success" in result
        assert "url" in result
        assert "content" in result

    @pytest.mark.asyncio
    async def test_fetch_tool_with_css_selector(self, bridge, mock_extension):
        """测试 fetch 工具使用 CSS 选择器。"""
        from server.server import fetch
        
        listen_task = asyncio.create_task(mock_extension.listen_and_respond())
        
        url = "https://example.com/article"
        css_selector = "article.main"
        
        result = await fetch(
            url=url,
            extraction_type="markdown",
            auto_filter=False,
            css_selector=css_selector,
        )
        
        await listen_task
        
        assert isinstance(result, dict)
        assert result["selector"] == css_selector

    @pytest.mark.asyncio
    async def test_fetch_tool_timeout_handling(self, bridge):
        """测试 fetch 工具超时处理。"""
        from server.server import fetch
        
        # 断开支所有扩展连接
        for ws in bridge.ws_clients.copy():
            await ws.close()
        bridge.ws_clients.clear()
        await asyncio.sleep(0.3)
        
        result = await fetch(url="https://example.com")
        
        assert result["success"] is False
        assert "No extension connected" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_tool_exception_handling(self, bridge, mock_extension):
        """测试 fetch 工具异常处理。"""
        from server.server import fetch
        
        # 设置扩展不响应导致超时
        mock_extension.set_should_respond(False)
        
        result = await fetch(url="https://example.com", timeout=500)
        
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_tool(self, bridge, mock_extension):
        """测试 close 工具。"""
        from server.server import close
        
        # bridge 已连接
        assert bridge.is_connected
        
        result = await close()
        
        assert isinstance(result, str)
        # close_bridge 会关闭全局实例
        import server.extension_bridge as bridge_module
        assert bridge_module._bridge is None

    @pytest.mark.asyncio
    async def test_clear_cache_tool(self, bridge):
        """测试 clear_cache 工具。"""
        from server.server import clear_cache
        
        result = clear_cache()
        
        assert isinstance(result, str)
        assert "cache" in result.lower() or "缓存" in result


# ============================================================================
# 测试内容提取器
# ============================================================================

class TestContentExtractor:
    """测试内容提取功能。"""

    def test_extract_markdown(self, sample_html):
        """测试提取 Markdown 格式。"""
        result = extract_content(
            sample_html,
            extraction_type="markdown",
            auto_filter=True,
        )
        
        assert isinstance(result, list)
        assert len(result) > 0
        # 应该包含标题和段落内容
        combined = " ".join(result)
        assert "Main Title" in combined or "main content" in combined.lower()

    def test_extract_html(self, sample_html):
        """测试提取 HTML 格式。"""
        result = extract_content(
            sample_html,
            extraction_type="html",
            auto_filter=True,
        )
        
        assert isinstance(result, list)
        assert len(result) > 0
        # HTML 提取应保留标签
        combined = " ".join(result)
        assert "<" in combined

    def test_extract_text(self, sample_html):
        """测试提取纯文本格式。"""
        result = extract_content(
            sample_html,
            extraction_type="text",
            auto_filter=True,
        )
        
        assert isinstance(result, list)
        assert len(result) > 0
        # 文本提取不应包含 HTML 标签
        combined = " ".join(result)
        assert "<" not in combined

    def test_extract_with_css_selector(self, sample_html):
        """测试使用 CSS 选择器提取。"""
        result = extract_content(
            sample_html,
            extraction_type="markdown",
            auto_filter=False,
            css_selector="article",
        )
        
        assert isinstance(result, list)
        # 应该提取 article 标签内容
        combined = " ".join(result)
        assert "Main Title" in combined

    def test_extract_empty_html(self):
        """测试空 HTML 处理。"""
        result = extract_content(
            "",
            extraction_type="markdown",
            auto_filter=True,
        )
        
        assert isinstance(result, list)
        # 空 HTML 可能返回空列表或包含空字符串
        assert all(item.strip() == "" or item.strip() is None for item in result if result)

    def test_extract_invalid_html(self):
        """测试无效 HTML 处理。"""
        result = extract_content(
            "This is not HTML at all",
            extraction_type="markdown",
            auto_filter=True,
        )
        
        # 应该不会崩溃，可能返回空或原文
        assert isinstance(result, list)


# ============================================================================
# 测试类型定义
# ============================================================================

class TestTypes:
    """测试类型定义。"""

    def test_response_result_structure(self):
        """测试 ResponseResult 结构。"""
        result: ResponseResult = {
            "success": True,
            "url": "https://example.com",
            "status": 200,
            "content": ["content"],
            "selector": None,
            "error": None
        }
        
        assert result["success"] is True
        assert result["url"] == "https://example.com"
        assert result["status"] == 200
        assert isinstance(result["content"], list)

    def test_fetch_task_structure(self):
        """测试 FetchTask 结构。"""
        task = FetchTask(
            id="test123",
            url="https://example.com",
            options={"timeout": 60000}
        )
        
        assert task.id == "test123"
        assert task.url == "https://example.com"
        assert task.options["timeout"] == 60000

    def test_task_result_structure(self):
        """测试 TaskResult 结构。"""
        result = TaskResult(
            task_id="test123",
            success=True,
            url="https://example.com",
            final_url="https://example.com/final",
            status=200,
            content=["content"]
        )
        
        assert result.task_id == "test123"
        assert result.success is True
        assert result.status == 200


# ============================================================================
# 集成测试：模拟完整 MCP Client ↔ Server ↔ Extension 流程
# ============================================================================

class TestIntegrationMCPClientServer:
    """
    集成测试：模拟 MCP Client 与 MCP Server 的完整通信流程。
    """

    @pytest.mark.asyncio
    async def test_full_fetch_workflow(self, bridge, mock_extension):
        """测试完整的 fetch 工作流程。"""
        from server.server import fetch
        
        listen_task = asyncio.create_task(mock_extension.listen_and_respond())
        
        url = "https://example.com/test"
        result = await fetch(
            url=url,
            extraction_type="markdown",
            auto_filter=True,
        )
        
        await listen_task
        
        assert isinstance(result, dict)
        assert "success" in result
        assert "url" in result
        assert "status" in result
        assert "content" in result
        assert "selector" in result
        assert "error" in result
        
        if result["success"]:
            assert result["status"] == 200
            assert isinstance(result["content"], list)
            assert result["error"] is None

    @pytest.mark.asyncio
    async def test_multiple_sequential_fetch_calls(self, bridge, mock_extension):
        """测试多个顺序 fetch 调用。"""
        from server.server import fetch
        
        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        ]
        
        results = []
        for url in urls:
            listen_task = asyncio.create_task(mock_extension.listen_and_respond())
            result = await fetch(url=url, extraction_type="text")
            await listen_task
            results.append(result)
            assert result["success"] is True
        
        assert len(results) == 3
        assert all(r["success"] for r in results)

    @pytest.mark.asyncio
    async def test_fetch_with_different_extraction_types(self, bridge, mock_extension):
        """测试不同的提取类型。"""
        from server.server import fetch
        
        extraction_types = ["markdown", "html", "text"]
        
        for ext_type in extraction_types:
            listen_task = asyncio.create_task(mock_extension.listen_and_respond())
            result = await fetch(
                url="https://example.com",
                extraction_type=ext_type,
            )
            await listen_task
            
            assert result["success"] is True
            assert isinstance(result["content"], list)

    @pytest.mark.asyncio
    async def test_bridge_message_protocol(self, bridge, mock_extension):
        """测试 WebSocket 消息协议格式。"""
        # 直接发送任务消息
        task_id = "test12345"
        url = "https://example.com/protocol-test"
        
        # 通过扩展客户端发送原始消息
        await mock_extension.ws.send(json.dumps({
            "type": "task",
            "task": {
                "id": task_id,
                "url": url,
                "options": {"timeout": 60000},
            }
        }))
        
        # Bridge server 应该收到消息（通过广播机制）
        await asyncio.sleep(0.3)
        
        # 验证桥接服务器在运行
        assert bridge._running
        assert len(bridge.ws_clients) > 0


# ============================================================================
# 边缘情况和错误处理测试
# ============================================================================

class TestEdgeCases:
    """测试边缘情况和错误处理。"""

    @pytest.mark.asyncio
    async def test_bridge_not_started(self):
        """测试未启动时尝试 fetch。"""
        bridge = ExtensionBridge(host="localhost", port=9878)
        
        with pytest.raises(RuntimeError, match="not started"):
            await bridge.fetch(url="https://example.com", options={})

    @pytest.mark.asyncio
    async def test_no_extension_connected(self, bridge):
        """测试没有扩展连接时尝试 fetch。"""
        from server.server import fetch
        
        # Bridge 已启动但没有扩展连接（不使用 mock_extension fixture）
        # 确保没有客户端
        for ws in bridge.ws_clients.copy():
            await ws.close()
        bridge.ws_clients.clear()
        await asyncio.sleep(0.3)
        
        result = await fetch(url="https://example.com")
        
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "No extension connected" in result["error"]

    @pytest.mark.asyncio
    async def test_concurrent_bridge_instances(self):
        """测试多个 bridge 实例（应该共享同一个连接）。"""
        import server.extension_bridge as bridge_module
        bridge_module._bridge = None
        
        from server.extension_bridge import get_bridge
        
        bridge1 = await get_bridge()
        bridge2 = await get_bridge()
        
        # 应该是同一个实例（单例模式）
        assert bridge1 is bridge2
        
        await bridge1.stop()
        bridge_module._bridge = None

    def test_response_result_error_cases(self):
        """测试 ResponseResult 错误情况。"""
        result: ResponseResult = {
            "success": False,
            "url": "https://example.com",
            "status": 0,
            "content": [],
            "selector": None,
            "error": "Connection refused"
        }
        
        assert result["success"] is False
        assert result["error"] is not None
        assert len(result["content"]) == 0


# ============================================================================
# 运行测试
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
