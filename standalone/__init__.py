"""独立运行层：把游戏从 Claude Code 宿主里抽离，自带 LLM + agent loop。

宿主（Claude Code）一直替我们做三件事：当 GM 的 LLM、play prompt、执行工具调用。
这一层接管它们：
  config  —— 读 .env，OpenAI 兼容配置（base_url/key/model），全 LLM 通吃
  tools   —— 工具桥：从引擎自己的 FastMCP 注册表生成 tool spec + 进程内派发
  prompt  —— 把 play/SKILL.md 当 system prompt
  agent   —— agent loop：LLM ↔ 工具 ↔ 引擎，跑完一个玩家回合
  cli     —— 无界面入口（验证 loop）；tui 后续

引擎（mcp_server）是纯 Python，直接 import 当库调，不走 MCP 协议——单进程红利。
"""
