# Barnacle

基于浏览器插件的智能隐匿爬虫，通过 MCP 协议为 AI Agent 提供网页抓取能力。

## 概述

Barnacle 是一个基于浏览器扩展的爬虫，完美绕过登录限制和反爬检测。结合 ONNX 模型的智能内容检测，自动提取页面核心内容，减少 token 消耗。

### 核心优势

- **隐匿抓取**: 通过浏览器扩展在用户真实浏览器中执行，继承所有登录状态和 cookies
- **智能过滤**: 使用 distilgpt2 ONNX 模型计算困惑度，自动识别并提取主要内容区域
- **MCP 协议**: 原生支持 Model Context Protocol，可直接作为 AI Agent 工具使用
- **多格式输出**: 支持 Markdown、HTML、纯文本三种提取格式

## 架构

```plain
┌─────────────┐      MCP Protocol      ┌─────────────────┐
│   AI Agent  │ ◄───────────────────► │   MCP Server    │
└─────────────┘                        │  (FastMCP)      │
                                       └────────┬────────┘
                                                │ WebSocket
                                       ┌────────▼────────┐
                                       │ Extension Bridge │
                                       │  (ws://:9877)   │
                                       └────────┬────────┘
                                                │
                                       ┌────────▼────────┐
                                       │ Chrome Extension │
                                       │ (Barnacle Bridge)│
                                       └────────┬────────┘
                                                │
                                       ┌────────▼────────┐
                                       │  User's Browser │
                                       │  (登录状态/cookies)│
                                       └─────────────────┘
```

## 安装

### 1. 安装 Python 依赖

```bash
# 创建虚拟环境并安装依赖
uv venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# 安装依赖
uv pip install mcp websockets lxml markdownify "optimum[onnxruntime]" transformers torch
```

### 2. 下载并导出 ONNX 模型

```bash
uv run python export_onnx.py
```

这会将 distilgpt2 模型导出到 `onnx-models/distilgpt2/` 目录。

### 3. 安装浏览器扩展

1. 打开 Chrome，访问 `chrome://extensions/`
2. 启用「开发者模式」
3. 点击「加载未打包的扩展程序」
4. 选择 `extension/` 目录

## 使用方法

### 启动 MCP Server

```bash
uv run python -m server.server
```

### 作为 MCP 工具使用

在你的 MCP 客户端配置中添加：

```json
{
  "mcpServers": {
    "barnacle": {
      "command": "uv",
      "args": ["run", "python", "-m", "server.server"],
      "cwd": "C:/workspace/barnacle"
    }
  }
}
```

### 可用工具

#### `fetch` - 抓取网页

| 参数 | 类型 | 默认值 | 描述 |
| ------ | ------ | -------- | ------ |
| `url` | string | 必填 | 目标 URL |
| `extraction_type` | string | "markdown" | 提取格式: markdown / html / text |
| `auto_filter` | bool | true | 启用智能内容检测 |
| `timeout` | int | 60000 | 超时时间（毫秒） |
| `wait` | int | 0 | 页面加载后等待时间（毫秒） |
| `css_selector` | string | null | 手动指定 CSS 选择器 |
| `active` | bool | true | 以活动标签页打开 |
| `keep_open` | bool | false | 抓取后保持标签页打开 |

#### `close` - 关闭连接

关闭与浏览器扩展的 WebSocket 连接。

#### `clear_cache` - 清除缓存

清除内容检测器的内部缓存。

### 测试

```bash
# 运行测试
uv run pytest

# 测试 MCP 客户端（抓取微博热搜）
uv run python test_mcp_client.py
```

## 项目结构

```plain
barnacle/
├── server/                    # MCP Server 模块
│   ├── server.py            # FastMCP 服务入口
│   ├── extension_bridge.py  # WebSocket 桥接服务
│   ├── content_detector.py  # ONNX 智能内容检测
│   ├── extractor.py         # HTML 内容提取
│   └── types.py             # 类型定义
├── extension/                 # Chrome 扩展
│   ├── manifest.json        # 扩展配置
│   ├── background.js        # Service Worker
│   ├── content.js           # 内容脚本
│   ├── popup.html/js        # 弹窗界面
│   └── icons/               # 图标资源
├── onnx-models/              # ONNX 模型目录
│   └── distilgpt2/          # distilgpt2 模型
├── export_onnx.py            # 模型导出脚本
├── test_mcp_client.py        # MCP 客户端测试
└── tests/                    # 单元测试
```

## 智能内容检测

Barnacle 使用基于困惑度的智能内容检测算法：

1. **语义标签优先**: 自动识别 `<article>`, `<main>` 等语义标签
2. **模式匹配**: 通过 class/id 属性匹配常见内容区域命名
3. **困惑度评分**: 使用 ONNX 模型计算文本困惑度，高困惑度内容更可能是正文
4. **噪声过滤**: 自动移除导航、侧边栏、广告等噪声区域

## 开发

```bash
# 安装开发依赖
uv pip install -r requirements-test.txt

# 运行测试
uv run pytest -v

# 运行 lint
uv run ruff check .
```

## 注意事项

- 确保浏览器扩展已安装并启用
- 首次抓取时需要等待扩展连接（约 2 秒）
- 模型会在后台异步加载，不影响服务启动
- WebSocket 服务默认监听 `ws://localhost:9877`
