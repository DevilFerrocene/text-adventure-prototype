# 文字冒险原型 · Text Adventure Prototype

一个 **TRPG 文字冒险引擎**：有状态的游戏引擎（房间、物品、骰子、战斗、技能、等级、存档全在这里，确定性、可计算）+ 一个 LLM 当 GM（调用引擎工具、写沉浸式叙事）。

**两种玩法：**
- **独立运行**（`standalone/`）——自带 LLM + agent loop + 流式 TUI，配好 `.env` 里的 API key 就能在终端单独跑，不依赖任何宿主。
- **作为 MCP 后端**——把引擎挂进支持 [MCP](https://modelcontextprotocol.io) 的宿主（Claude Code / Codex），由宿主的 LLM 当 GM。

引擎是同一个；区别只是"谁来当 GM、从哪里玩"。

> **设计北极星：算得清，玩得开。** 数值、状态、判定由引擎裁定，绝不脑补；叙事自由、氛围细腻、即兴创意尽情发挥。

---

## 特性

- **数学系统**：原子化 `Modifier`（修正）→ `Buff`（带 TTL 的修正容器）→ `Skill`（被动/主动/反应三类技能）。一处合算，处处复用。每次掷骰附带**明骰加值链**（`d20=12 +2(察知) +4(敏) ×-2(雾寒侵体) = 16 vs DC14`），让玩家"看得见命运为何如此"。
- **RPG 数值骨架**：角色等级/经验、四属性（力/敏/体/智）、多装备槽。**属性表是 content（`RuleBook`）不是引擎写死**——每个世界自定义有哪些属性。伤害由武器/技能声明吃哪个属性（混属性带权重），不绑死"力定伤害"。
- **战斗系统**：回合制 Encounter 状态机，敌人原型表 + 行为画像，命中/伤害/抗性/buff/死亡全走统一管线。打怪给经验、升级长血。
- **万物皆可破坏**（BG3 式）：场景里的高草丛、宝箱、陷阱地砖天生有 hp/抗性（默认冻结、零 token 负担），玩家做出破坏意图时解冻结算，`on_destroyed` 可揭示隐藏物、触发剧情。
- **技能树**：被动常驻 / 主动施放（消耗 + 冷却）/ 反应触发（被偷袭前自动加感知），XP 成长自动升 rank。
- **战术战斗（可选）**：硬仗可开战术模式——列阵区位（rank）、武器触及（reach，近战须顶前排/远程点后排）、行动经济（每回合 1 大动 + 1 小动），让近战/远程/走位 build 真正分化，而非脸贴脸互砍。
- **HUD 前台**：引擎吐出权威状态条、骰子卡、场景清单、战斗血条，GM 直接渲染。独立 TUI 里 HUD 常驻顶栏、叙事流式输出。
- **GM 裁定权**：玩家用了预设之外的创意解法时，GM 可裁定并落到引擎（`gm_set_flag`），世界状态真正认可——不强迫套预设动作。
- **自动存档**：每次状态变更静默落盘，进程重启无缝续上（根治"玩到一半状态丢了"）。
- **示例世界「苍穹回廊」**：日式异世界逐层攻略——剑技 / 炎霜雷影属性克制 / 等级成长 / 逐层 Boss 攻略。

当前规模：40 个引擎工具，1 个世界（第一层完整可玩），190 个回归测试。

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

### 方式一：独立运行（自带 LLM + 流式 TUI，推荐先试）

配好上面的 `.env` 后：

```bash
python -m standalone.tui     # 富界面 TUI：状态栏顶 + 叙事流式 + 输入底
python -m standalone.cli     # 纯命令行一问一答
python -m standalone.cli --check   # 不调 LLM 的自检（验证工具桥/配置）
```

GM 会先问你玩哪个世界，然后用自然语言行动即可：

```
> 玩苍穹回廊
> 我去找剑技教官学一招
> 我装备那把淬钢直剑，往北走进雾语草原
> 我用鞭炮炸开角落那堆牛粪
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

## 架构一览

```
mcp_server.py          # 游戏引擎 + 40 个工具（核心）
core/types.py          # 数据模型：Modifier/Buff/Skill/RuleBook/Combatant/GameObject…
runtime/game_world.py  # 世界容器：房间/物体/敌人/技能/规则书注册表
content/aincrad.py     # 示例世界「苍穹回廊」（逐层攻略）
standalone/            # 独立运行层：config / tools(工具桥) / agent(loop) / prompt / tui / cli
.claude/skills/play/   # GM skill（导演 prompt，与 .agents/ 同步）
.agents/skills/play/
tests/                 # 206 个回归测试
```

**分层与依赖**：
- 引擎层（`mcp_server` + `core` + `runtime`）确定性、可计算，是唯一的状态权威。
- content 层（`content/*.py`）是纯数据。**加新世界 = 写一份 `content/<world>.py`，引擎不动。**
- 独立层（`standalone/`）只是引擎之上的一层"自带 GM"——工具桥从引擎自己的注册表自动暴露 40 个工具，进程内直调（不走 MCP 协议）。
- 单向依赖：Modifier 不知道 Skill/Buff 存在；引擎不知道 content 长什么样；content 不知道谁在当 GM。

---

## 测试

```bash
source venv/bin/activate
python -m pytest tests/ -q
```

---

## 写你自己的世界

content 是纯数据。照着 `content/aincrad.py` 写一份新模块——房间 `Room`、物体 `GameObject`、敌人 `EnemyTemplate`、技能 `Skill`、任务 `QuestEntry`，可选一份 `RuleBook`（自定义该世界的属性表/装备槽，不写就用默认四属性）——然后在 `mcp_server.py` 的 `WORLDS` 字典里注册即可。物体的 `on_destroyed`、affordance 的 `effect`、武器的 `scaling` 都复用同一套数据 DSL，无需改引擎。

---

## 许可证

[MIT License](LICENSE)。
