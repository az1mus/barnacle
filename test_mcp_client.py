# -*- coding: utf-8 -*-
"""
MCP Client 测试脚本 - 模拟 Agent 调用 Barnacle MCP Server
查询微博热搜
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_weibo_hot_search():
    """测试调用微博热搜"""
    
    # MCP Server 启动参数
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.server"],
        cwd=str(Path(__file__).parent),
    )
    
    print("=" * 60)
    print("Barnacle MCP Client - 微博热搜查询测试")
    print("=" * 60)
    print()
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 初始化连接
            await session.initialize()
            print("[✓] 已连接到 MCP Server")
            print()
            
            # 列出可用工具
            tools = await session.list_tools()
            print(f"可用工具: {[t.name for t in tools.tools]}")
            print()
            
            # 调用 fetch 工具查询微博热搜
            print("[→] 正在调用 fetch 工具查询微博热搜...")
            print()
            
            result = await session.call_tool(
                "fetch",
                arguments={
                    "url": "https://s.weibo.com/top/summary",
                    "extraction_type": "text",
                    "auto_filter": True,
                    "timeout": 60000,
                    "wait": 2000,  # 等待2秒让页面加载完成
                    "css_selector": None,
                    "active": False,
                    "keep_open": False,
                }
            )
            
            # 处理结果
            print("=" * 60)
            print("查询结果:")
            print("=" * 60)
            
            for content_item in result.content:
                if hasattr(content_item, 'text'):
                    print(content_item.text)
                elif isinstance(content_item, str):
                    print(content_item)
                elif isinstance(content_item, dict):
                    print(content_item.get('content', ''))
                else:
                    print(str(content_item))
            
            print()
            print("=" * 60)
            print("测试完成!")
            print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(test_weibo_hot_search())
    except KeyboardInterrupt:
        print("\n测试已取消")
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
