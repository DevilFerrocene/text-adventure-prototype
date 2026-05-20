# 文字冒险原型 · Text Adventure Prototype

一个 **TRPG 文字冒险引擎**，跑在 [MCP](https://modelcontextprotocol.io)（Model Context Protocol）之上。

架构很简单：一个有状态的 **MCP 服务器**当游戏引擎（房间、物品、骰子、战斗、技能、存档全在这里，确定性、可计算），一份 **GM skill** 当导演（让宿主 LLM——Claude Code / Codex——扮演 GM，调用工具、写沉浸式叙事）。

> **设计北极星：算得清，玩得开。** 数值、状态、判定由引擎裁定，绝不脑补；叙事自由、氛围细腻、即兴创意尽情发挥。

---

## 特性

- **数学系统**：原子化 `Modifier`（修正）→ `Buff`（带 TTL 的修正容器）→ `Skill`（被动/主动/反应三类技能）。一处合算，处处复用。每次掷骰附带**明骰加值链**（`d20=12 +2(潜行训练) ×-2(雨夜湿冷) = 11 vs DC14`），让玩家"看得见命运为何如此"。
- **战斗系统**：回合制 Encounter 状态机，敌人原型表 + 行为画像，命中/伤害/抗性/buff/死亡全走统一管线。
- **万物皆可破坏**（BG3 式）：场景里的牛粪、酒坛、油桶天生有 hp/抗性（默认冻结、零 token 负担），玩家做出破坏意图时解冻结算，`on_destroyed` 可揭示隐藏物、触发剧情。
- **技能树**：被动常驻 / 主动施放（消耗 + 冷却）/ 反应触发（被偷袭前自动加感知），XP 成长自动升 rank。
- **HUD 前台**：聊天框即前台。引擎吐出权威状态条、骰子卡、场景清单、战斗血条，GM 直接渲染。
- **GM 裁定权**：玩家用了预设之外的创意解法时，GM 可裁定并落到引擎（`gm_set_flag`），世界状态真正认可——不强迫套预设动作。
- **完整示例世界**：「亚楠·雨夜委托」——一桩雨夜暗杀，从接委托到了结目标，提供**正面战斗 / 潜行绞杀 / 嫁祸谋略**三种解法分支。

当前规模：33 个 MCP 工具，6 个房间的完整主线，131 个回归测试。

---

## 安装

需要 **Python 3.10+**（开发于 3.11）。

```bash
git clone <repo-url>
cd "Text Adventure Prototype"

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

复制环境变量模板（当前 MCP 架构下 LLM 由宿主提供，`.env` 主要留给未来的独立客户端，可按需填写）：

```bash
cp .env.example .env
```

---

## 怎么玩

游戏通过 MCP 接入支持它的宿主（如 Claude Code、Codex）。

1. **配置 MCP 服务器**：复制示例配置并填入你的**绝对路径**——

   ```bash
   cp .mcp.json.example .mcp.json
   ```

   编辑 `.mcp.json`，把 `/ABSOLUTE/PATH/TO/REPO` 换成本仓库的真实路径：

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

   > `.mcp.json` 含本机绝对路径，已被 `.gitignore` 忽略——每台机器各自从 `.mcp.json.example` 复制。
   >
   > **Codex 用户**：改用 `.codex/config.toml`（从 `.codex/config.toml.example` 复制，同样填绝对路径）。

2. **开始游戏**：在宿主里调用 `play` skill（输入 `/play` 或说"开始游戏"）。GM 会立即开局，等你用自然语言行动。

```
> 我拆开那封猩红封蜡的信。
> 我撬开仓库的锁。
> 我用鞭炮炸开角落那堆牛粪。
> 我潜行绕过守卫，从背后接近领主。
```

---

## 架构一览

```
mcp_server.py          # 游戏引擎 + 33 个 MCP 工具（核心，约 3000 行）
core/types.py          # 数据模型：Modifier/Buff/Skill/Combatant/GameObject…
runtime/game_world.py  # 世界容器：房间/物体/敌人/技能注册表
content/yanan.py       # 示例世界「亚楠·雨夜委托」（房间/物品/敌人/技能/任务）
.claude/skills/play/   # GM skill（导演 prompt，与 .agents/ 同步）
.agents/skills/play/
tests/                 # 131 个回归测试
AGENTS.md              # 完整设计文档（深度阅读）
```

**单向依赖**：Modifier 不知道 Skill/Buff 存在；引擎不知道 content 长什么样。加新世界 = 写一份 `content/<world>.py`，引擎不动。

---

## 测试

```bash
source venv/bin/activate
python -m pytest tests/ -q
```

---

## 写你自己的世界

content 是纯数据。照着 `content/yanan.py` 写一份新模块（房间 `Room`、物体 `GameObject`、敌人 `EnemyTemplate`、技能 `Skill`、任务 `QuestEntry`），在 `mcp_server.py` 的 `WORLDS` 字典里注册即可。物体的 `on_destroyed`、affordance 的 `effect` 复用同一套 DSL，无需改引擎。详见 `AGENTS.md`。

---

## 许可证

[Apache License 2.0](LICENSE)。
