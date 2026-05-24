# 文字冒险原型 · Text Adventure Prototype

一个 **TRPG 文字冒险引擎**：有状态的游戏引擎（房间、物品、骰子、战斗、技能、等级、存档全在这里，确定性、可计算）+ 一个 LLM 当 GM（调用引擎工具、写沉浸式叙事）。

**两种玩法：**
- **独立运行**（`standalone/`）——自带 LLM + agent loop + Web 富界面（含世界编辑器），配好 `.env` 里的 API key 就能单独跑，不依赖任何宿主。
- **作为 MCP 后端**——把引擎挂进支持 [MCP](https://modelcontextprotocol.io) 的宿主（Claude Code / Codex），由宿主的 LLM 当 GM。

引擎是同一个；区别只是"谁来当 GM、从哪里玩"。

> **设计北极星：算得清，玩得开。** 数值、状态、判定由引擎裁定，绝不脑补；叙事自由、氛围细腻、即兴创意尽情发挥。

---

## 安装

需要 **Python 3.10+**（开发于 3.11）。

```bash
git clone https://github.com/DevilFerrocene/text-adventure-prototype
cd "Text Adventure Prototype"

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

复制环境变量模板：

```bash
cp .env.example .env
```

**独立运行**需要在 `.env` 里填一个 OpenAI 兼容的 LLM 端点（DeepSeek / OpenAI / 本地 Ollama 等皆可）：

```
OPENAI_API_KEY=你的key
OPENAI_BASE_URL=https://api.deepseek.com   # 或 https://api.openai.com/v1 等
LLM_MODEL=deepseek-chat                    # 你端点上的模型名
```

（只把引擎当 MCP 后端、由宿主提供 LLM 时，`.env` 可不填。）

---

## 怎么玩

### 方式一：独立运行（自带 LLM + Web 富界面，推荐先试）

配好上面的 `.env` 后：

```bash
python -m standalone.web     # Web 富界面（三栏 game-client）→ http://127.0.0.1:8000
                             #   顶栏「世界编辑器」入口 / 直接访问 /editor 改世界、一键试玩
python -m standalone.cli     # 纯命令行一问一答（无界面）
python -m standalone.cli --check   # 不调 LLM 的自检（验证工具桥/配置/世界完整性）
```

### 方式二：作为 MCP 后端接进宿主（Claude Code / Codex）

1. 复制 MCP 配置并填**绝对路径**：

   ```bash
   cp .mcp.json.example .mcp.json
   ```

   编辑 `.mcp.json`，把 `/ABSOLUTE/PATH/TO/REPO` 换成本仓库真实路径：

   ```json
   {
     "mcpServers": {
       "text-adventure": {
         "command": "/你的/路径/Text Adventure Prototype/venv/bin/python3",
         "args": ["/你的/路径/Text Adventure Prototype/mcp_server.py"]
       }
     }
   }
   ```

   > `.mcp.json` 含本机绝对路径，已 `.gitignore` 忽略——每台机器各自从 `.mcp.json.example` 复制。
   > **Codex 用户**：改用 `.codex/config.toml`（从 `.codex/config.toml.example` 复制）。

2. 在宿主里调用 `play` skill（输入 `/play` 或说"开始游戏"），由宿主的 LLM 当 GM。

---

## 许可证

[MIT License](LICENSE)。
