# 文字冒险原型 · Text Adventure Prototype

一个 **TRPG 文字冒险引擎**：有状态的游戏引擎（房间、物品、骰子、战斗、技能、等级、存档全在这里，确定性、可计算）+ 一个 LLM 当 GM（调用引擎工具、写沉浸式叙事）。

**两种玩法：**
- **独立运行**（`standalone/`）——自带 LLM + agent loop + Web 富界面（含世界编辑器），配好 `.env` 里的 API key 就能单独跑，不依赖任何宿主。
- **作为 MCP 后端**——把引擎挂进支持 [MCP](https://modelcontextprotocol.io) 的宿主（Claude Code / Codex），由宿主的 LLM 当 GM。

引擎是同一个；区别只是"谁来当 GM、从哪里玩"。

> **设计北极星：算得清，玩得开。** 数值、状态、判定由引擎裁定，绝不脑补；叙事自由、氛围细腻、即兴创意尽情发挥。

---

## 特性

**算得清（引擎）**
- **数学系统**：`Modifier` → `Buff` → `Skill`（被动/主动/反应）一处合算、处处复用；每次掷骰附**明骰加值链**（`d20=12 +2(察知) +4(敏) = 16 vs DC14`）。
- **RPG 骨架**：等级/经验/属性/装备槽，**属性表是 content（`RuleBook`）不是引擎写死**；伤害声明吃哪个属性，不绑死"力定伤害"。
- **战斗**：回合制 Encounter，敌人原型 + 行为画像，命中/伤害/抗性/buff/死亡统一管线，打怪升级。可选**战术模式**（列阵/触及/行动经济）与**危机合约**（自定难度换确定性奖励）。
- **万物可破坏 + 冷物体**：场景物天生有 hp（默认冻结、零成本），碰它才解冻；一行 `ambient` 铺满场景密度，就地抓酒瓶砸过去到处可行。

**空间感（二维棋盘）**
- 房间可挂 `RoomGrid`，**引擎独占坐标与寻路，对外只给方位 + 距离**（省 token、防 GM 编坐标）；没挂的房间隐式"满屋皆在手边"。
- **敌人在棋盘上带视野/仇恨**：默认在你视野外，走进它视野才被发现、自动进战；不踏进就能潜行绕过。
- **战斗就在同一张棋盘打**：触及=格距，走位吃借机攻击，敌人位置 AI（近战逼近、远程放风筝、多怪包抄）。
- **探索点「?」**：棋盘埋未探明点，谜底锁在引擎里、GM 也看不到，走到跟前才揭示（战利品/线索/陷阱/伏击）。

**玩得开（前台 / 工具）**
- **Web 三栏 game-client**（`python -m standalone.web`）：左角色状态 + 中 GM 叙事流/输入 + 右场景对象，叠加 **背包/技能/任务/地图/场地** 看板，HUD 全由引擎渲染。
- **世界编辑器**（`/editor`）：房间/物体/敌人/技能/任务**全实体表单 CRUD + 棋盘可视化编辑 + 实时校验 + 一键试玩**——把世界当数据改，不用写 Python。
- **GM 裁定权** / **自动存档 + 会话管理**（连对话一起恢复、可存多局切换）/ **软重生**（死亡掉半数金币拽回营地，鼓励试错）。

**示例世界「苍穹回廊」**：日式异世界逐层攻略（剑技 / 炎霜雷影克制 / 升级 / Boss）。冷开局是一场**"破局"**——6 点血、空手（1d1）、0 金、0 人脉，连城外的杀人兔都打不死，第一件事是靠脑子挣出活路。

当前规模：46 个引擎工具，1 个世界（破局开场 + 第一层），434 个回归测试。

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

### 方式一：独立运行（自带 LLM + Web 富界面，推荐先试）

配好上面的 `.env` 后：

```bash
python -m standalone.web     # Web 富界面（三栏 game-client）→ http://127.0.0.1:8000
                             #   顶栏「世界编辑器」入口 / 直接访问 /editor 改世界、一键试玩
python -m standalone.cli     # 纯命令行一问一答（无界面）
python -m standalone.cli --check   # 不调 LLM 的自检（验证工具桥/配置/世界完整性）
```

GM 会带你进入苍穹回廊的营地——6 点血、空着两手、一个铜板都没有。然后用自然语言破局：

```
> 开始游戏
> 我去东边那间酒馆看看在吵什么
> 那群人打起来了，我帮冒险者那边搭把手
> 往北出镇，我掰下枯树上一根硬枝当棍子
> 我攥紧木棍，扑上去揍那只杀人兔
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
mcp_server.py          # 游戏引擎 + 46 个工具（核心）
core/types.py          # 数据模型：Modifier/Buff/Skill/RuleBook/Combatant/GameObject…
runtime/game_world.py  # 世界容器：房间/物体/敌人/技能/规则书注册表
content/aincrad/       # 示例世界「苍穹回廊」（拆包：canon/enemies/skills/rooms/objects/state）
standalone/            # 独立运行层：config / tools(工具桥) / agent(loop) / prompt / web(+编辑器) / cli
.claude/skills/play/   # GM skill（导演 prompt，与 .agents/ 同步）
.agents/skills/play/
worlds/                # JSON 世界（编辑器存盘地；同名 JSON 覆盖内置，删掉即还原）
tests/                 # 434 个回归测试
```

**分层与依赖**：
- 引擎层（`mcp_server` + `core` + `runtime`）确定性、可计算，是唯一的状态权威。
- content 层（`content/*.py`）是纯数据。**加新世界 = 写一份 `content/<world>.py`，引擎不动。**
- 独立层（`standalone/`）只是引擎之上的一层"自带 GM"——工具桥从引擎自己的注册表自动暴露 46 个工具，进程内直调（不走 MCP 协议）。
- 单向依赖：Modifier 不知道 Skill/Buff 存在；引擎不知道 content 长什么样；content 不知道谁在当 GM。

---

## 测试

```bash
source venv/bin/activate
python -m unittest discover -s tests -q
```

---

## 写你自己的世界

两条路，引擎同一个：

- **可视化（不写代码）**：开 `python -m standalone.web`，进 `/editor`——房间/物体/敌人/技能/任务全表单增删改、棋盘点格子摆、实时校验、一键试玩，存成 `worlds/<name>.json`。改内置世界 = 存一份同名 JSON 覆盖层（删掉即还原）。
- **写代码（content 是纯数据）**：照着 `content/aincrad/` 写一份 `content/<world>.py`（或像 aincrad 拆成包），引擎只认 `register(world)` 一个入口，写好后在 `mcp_server.py` 的 `WORLDS` 注册。

零件：`Room` / `GameObject` / `EnemyTemplate` / `Skill` / `QuestEntry`，可选 `RuleBook`（自定义属性表/装备槽/徒手伤害）、可选 `RoomGrid`（二维棋盘）。`on_destroyed`/affordance `effect`/武器 `scaling` 复用同一套数据 DSL，无需改引擎。

**改完先校验**：编辑器实时跑校验；命令行用 `python -m standalone.cli --check` 跑 `GameWorld.validate()`——把"id 拼错""棋盘越界/叠格/走不到"在作者期就人话报出来，不必等玩到那里才崩。

---

## 许可证

[MIT License](LICENSE)。
