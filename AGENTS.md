# AI Text Adventure - Project Guide

## 项目定义

一个基于 LLM 的纯文字冒险游戏 Runtime。玩家用自然语言输入行动，Codex 担任 GM 即兴叙事，MCP Server 担任账房先生记账判定。

**定位：单人 TRPG + Codex 作为即兴 GM + Python MCP Server 作为账本与裁判**

---

## 架构：Skill + MCP Server

```
┌─ Codex ─────────────────────────────┐
│  .Codex/skills/play/SKILL.md             │
│  Codex = GM（叙事、决策、提议检定）        │
│        │                                   │
│        │ MCP 工具调用（stdio）              │
│        ▼                                   │
│  mcp_server.py                             │
│  Python = 账房（状态、判定的确定性执行）     │
│        │                                   │
│        ├── core/types.py   数据模型         │
│        ├── content/*.py    世界定义         │
│        ├── runtime/game_world.py  查询      │
│        └── runtime/rule_engine.py  执行     │
└────────────────────────────────────────────┘
```

**Codex 取代了旧架构中的**：`game_agent.py`、`engine.py`、`llm_client.py`、`repl.py`、`tui.py`——这些全部不再需要。Codex 自身就是 game engine + agentic loop + 前端。

**Python MCP Server 只做**：暴露确定性工具，维护 GameState 内存，执行判定、存档。不碰叙事，不调 LLM。

**为什么不是"一个 skill"而是 skill + MCP**：Codex 的 skill 是纯 prompt 模板，无法持久化状态、无法调用 Python。MCP server 填补了"有状态后端 + 自定义工具"的缺口——恰好是游戏引擎的完美用例。

---

## 北极星（North Star）

> **做一个聪明的 GM：算得清，玩得开。**

| 谁负责 | 干什么 |
|---|---|
| **MCP Server（账房）** | 永久状态、affordance 执行、骰子、世界观底线、即兴物品 7 关验证、存档 |
| **Codex（GM）** | 即兴叙事、生成临时细节、提议检定 DC、申请 improvised 物品、人物语气 |

**禁区**：MCP Server 不擅自编故事；Codex 不脑补数值、不绕过工具改状态。

---

## 核心设计

### 1. 双层世界状态（Canon vs Improvised）

```
Canon（金本位，Runtime 权威）              Improvised（即兴，Codex 提议 + MCP 限流）
────────────────────────────────         ──────────────────────────────────
- 主线剧情节点                            - 临时物品（撕下的布条、抄写的字条）
- 命名 NPC                               - 氛围细节（桌上空酒杯数）
- 永久状态变更（门已开、钥匙已得）         - 场景内的小动作回响
- 属性 / flag / clue                    
                                         
存活：永久                                存活：N 回合 TTL / 离开场景即清空
谁能改：MCP 工具 + 内容定义                谁能改：Codex 提议 → MCP 7 关验证后入背包
```

### 2. 世界观锚句（WorldCanon）

不穷举"这个世界有什么"，只描述"这个世界的味道是什么"。每个世界模块定义自己的 `WorldCanon`（setting_blurb、forbidden、aesthetic_tags、name_style），`start_game` 时喂给 Codex 作为叙事约束。

### 3. Affordance 系统

不再使用全局 ItemUse 查找表。每个 GameObject 自带 `affordances: Dict[str, Affordance]`——物体自己声明"我能被做什么"。`get_scene()` 返回当前场景的物体列表，每个物体带可用方法菜单。Codex 根据菜单决定调用哪个方法。

```python
@dataclass
class Affordance:
    verb: str                  # "read" / "unlock" / "pull" / "tear" ...
    desc: str = ""             # 给 Codex 看的说明
    requires_item: str | None  # 执行时必须持有的物品
    requires_flag: str | None  # 执行时必须已设置的 flag
    effect: dict               # unlock_exit, flags, clues, reveals_objects
    consume_self: bool         # 执行后自身是否消耗
    consume_item: bool         # 执行后 requires_item 是否消耗
```

### 4. 即兴物品（Improvised Items）

Codex 可提议临时物品，经 MCP Server 7 关验证后入背包：`imp_` 前缀、name 非空、不重复、category 合法、trace 不入包、size 自动修正、TTL 1-5。每回合上限 2 个，背包上限 4 个，换房全部清空。

### 5. 骰子

Codex 提议检定 → MCP `roll_check` 执行 1d20 + modifier vs DC → 返回 critical_success/success/failure/critical_failure → Codex 据此叙事。骰子是叙事扰动器，不是动作合法性判定。

### 6. 数学系统：Modifier / Skill / Buff / Action（账房最难做的一层）

> **核心洞察**：技能、buff、装备加值都是同一件事的不同包装——**对掷骰/伤害/状态/叙事的可计算修正**。所以底层只造一个原子 `Modifier`，Skill/Buff 都是它的"发射源"。复合动作（攻击两次+挂debuff）走另一层 `Action.recipe`。**不要让 Modifier 试图描述动作流程，也不要让 Skill/Buff 各自重复实现"持续时间+修正合算"。**

#### 6.1 三层分工

```
┌─ Action / Recipe ────────────────────────────────────────┐
│  复合动作的流程脚本。"不死斩 = 攻击 → 攻击 → 挂濒死"           │
│  由若干 Step 组成，按序执行                                  │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌─ Step / Verb ────────────────────────────────────────────┐
│  单步原子动作，白名单 verb，禁止裸 dict                       │
│  attack / damage / heal / flee / move / apply_buff /       │
│  consume / spawn_improvised / narrative_tag / roll_check   │
│  每个 Step 执行时会去 Modifier 池里查"我该被怎么修正"          │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌─ Modifier（原子）─────────────────────────────────────────┐
│  对一次掷骰/伤害/数值/叙事提示的单次修正                       │
│  Skill.passive / Buff.ticks / Item / Scene 都生产它          │
│  自动产生 audit trail，玩家可查"为什么是这个数"                │
└──────────────────────────────────────────────────────────┘
```

**铁律**：
1. 修正合算只有一个地方（Modifier 池），不允许 Skill / Buff / Item 各算各的
2. Step verb 必须走白名单枚举，禁止 `dict` 兜底——这是路线八之前 ItemUse 的坑，不许重犯
3. Modifier 不知道 Skill/Buff 存在；Skill/Buff 不知道 Action 存在——单向依赖
4. 战斗类 Step（attack / damage / flee）单独立项，见 §6.8（已随 B1+B2 上线）

#### 6.2 数据模型

```python
@dataclass
class Modifier:
    """所有修正的原子形态。"""
    id: str                          # 自动生成
    source_kind: str                 # skill / buff / item / scene / improvised
    source_id: str                   # 上溯到具体来源
    target: str                      # roll / dc / damage / hp / gold / narrative_tag
    selector: dict                   # 何时生效，例 {"reason_includes":["撬锁"]} / {"verb":"unlock"}
    op: str                          # add / mul / set / clamp / advantage / disadvantage / reroll
    value: float | str
    reason: str                      # 给玩家看的来源说明，例 "潜行训练"
    visible: str = "result"          # full / result / hidden


@dataclass
class Skill:
    """三种参与方式可同时存在（不是 kind 单选）。"""
    id: str
    name: str
    desc: str
    passive_modifiers: list[Modifier] = field(default_factory=list)   # 掌握期间常驻
    active: ActiveSkill | None = None                                   # 玩家主动声明
    reactive: ReactiveSkill | None = None                               # 触发器条件
    rank: int = 1
    xp: int = 0
    rank_thresholds: list[int] = field(default_factory=lambda: [3, 10, 25])
    obtained_from: str = ""          # background:detective / npc:Alma / improvised


@dataclass
class ActiveSkill:
    """主动技能的资源消耗 + 动作流程。"""
    cost: dict = field(default_factory=dict)         # stamina / hp / gold / item
    cooldown: int = 0
    remaining_cooldown: int = 0
    recipe: list[Step] = field(default_factory=list) # 按序执行的 Step 链


@dataclass
class ReactiveSkill:
    """被动响应。"""
    trigger: str                     # before_roll / on_take_damage / on_scene_enter ...
    condition: dict                  # selector，匹配 trigger 事件
    recipe: list[Step] = field(default_factory=list)


@dataclass
class Step:
    """单步动作。verb 走白名单。"""
    verb: str                        # attack / damage / heal / flee / move /
                                     # apply_buff / consume / spawn_improvised /
                                     # narrative_tag / roll_check / emit_modifier
    args: dict                       # verb-specific 字段，每个 verb 有自己的 schema
    on_success: list[Step] = field(default_factory=list)  # 子步骤
    on_failure: list[Step] = field(default_factory=list)


@dataclass
class Buff:
    """带 TTL 的 Modifier 容器 + 触发钩子。"""
    id: str
    name: str
    desc: str
    polarity: str                    # buff / debuff / neutral
    source_kind: str                 # skill / item / scene / npc / improvised
    source_id: str
    tags: list[str] = field(default_factory=list)
    stacks: int = 1
    max_stacks: int = 1
    ticks: dict[str, BuffTick] = field(default_factory=dict)   # 多时机：turn_start/turn_end/on_check/scene_leave
    expire_on: list[dict] = field(default_factory=list)         # 退场条件 OR 列表，例 [{"turns":3},{"flag":"dried_off"}]
    visible: str = "result"          # full / result / hidden


@dataclass
class BuffTick:
    """buff 在某个时机做的事——可以发射 modifier 或执行 step。"""
    emit_modifiers: list[Modifier] = field(default_factory=list)
    run_steps: list[Step] = field(default_factory=list)
```

#### 6.3 修正合算 & Audit Trail

`roll_check` 内部流程：

```
1. 收集触发: 收集所有 target=roll 且 selector 匹配本次掷骰的 Modifier
   - 来源：Skill.passive_modifiers + 当前 Buff.ticks(on_check).emit_modifiers + 装备 / 场景
2. 按 op 顺序合算：clamp → set → mul → add → advantage/disadvantage → reroll
3. 写入 last_roll 日志（含每个 modifier 的来源、值、可见性）
4. 玩家可调 explain_last_roll() 查 audit trail
```

输出范例（玩家可见部分）：

```
撬锁敏捷检定 d20=12
  +2 (潜行训练 [skill:stealth])         [full]
  +1 (锈钥匙顺手 [item:rusty_key])      [result]   ← 看见加值，但不知道来源细节
  -2 (雨夜湿冷 [buff:rain_soaked])      [full]
  = 13 vs DC14 → failure
```

这是"算得清"北极星的具象化。

#### 6.4 复合技能示例：不死斩

```python
Skill(
    id="undying_slash", name="不死斩",
    desc="一击两斩，重伤者更难愈合",
    active=ActiveSkill(
        cost={"stamina": 3},
        cooldown=5,
        recipe=[
            Step(verb="attack", args={"check": {"sides":20, "target":"enemy_ac"},
                                      "damage": "1d8+str"}),
            Step(verb="attack", args={"check": {"sides":20, "target":"enemy_ac"},
                                      "damage": "1d8+str"},
                 on_success=[
                     Step(verb="apply_buff",
                          args={"buff_id":"dying", "target":"enemy"})
                 ]),
        ],
    ),
)

Buff(
    id="dying", name="濒死", desc="伤口流血不止", polarity="debuff",
    source_kind="skill", source_id="undying_slash",
    ticks={
        "turn_start": BuffTick(emit_modifiers=[
            Modifier(id="auto", source_kind="buff", source_id="dying",
                     target="hp", selector={}, op="add", value=-2,
                     reason="濒死流血", visible="full"),
        ]),
    },
    expire_on=[{"turns": 3}],
)
```

**注意**：`attack` step 内部仍然走 `roll_check` 流程，所以场上一切对掷骰的 modifier（武器加值、潜行 buff、敌人弱点）会自然合进每一刀。技能本身不重复实现命中逻辑。

#### 6.5 Improvised Buff（GM 即兴 debuff 的合法路径）

Codex 想说"你被淋成落汤鸡，撬锁 -2 持续 3 回合"——必须走 `add_improvised_buff` 工具，**与 improvised item 同等的 7 关验证**：

1. name 非空、不重复
2. polarity ∈ {buff, debuff, neutral}
3. target ∈ 白名单 {roll, dc, hp, narrative_tag}（**不许动 gold/reputation 等敏感字段**）
4. value ∈ ±5 内（不允许碾压性修正）
5. duration ≤ 5 回合
6. 每回合最多 1 个 improvised buff
7. 玩家身上同时最多 3 个 improvised buff

这条防线确保 Codex 不会每回合往玩家身上挂奇怪 debuff 把游戏玩坏。

#### 6.6 与 conditions / custom_attrs 的边界

| 用什么 | 何时 | 例子 |
|---|---|---|
| `conditions` | 纯叙事标签，不影响掷骰 | "湿透了"（只用来写气氛） |
| `custom.player_attrs` | GM 临场记的数值，**不直接进 Modifier 池** | "暴击率 0.15"（要生效得包成 Modifier） |
| `Buff` | 影响掷骰/HP/叙事提示，有持续时间 | "雨夜湿冷 -2"、"濒死流血" |
| `Skill.passive_modifiers` | 角色长期常驻能力 | "潜行训练 +2" |

判定规则：**会影响一个或多个 `roll_check` 结果的，就得是 Modifier**——要么走 Skill.passive，要么走 Buff.ticks，要么走 improvised_buff。

#### 6.7 实施路线（分阶段）

| 阶段 | 内容 | 验证标准 |
|---|---|---|
| **Phase 1** | ~~Modifier 数据模型 + `roll_check` 接入合算 + `explain_last_roll` 工具~~ | ✅ 已完成 — `add_modifier` / `remove_modifier` / `explain_last_roll` 3 工具已上线 |
| **Phase 2** | ~~Buff 数据模型 + ticks/expire_on 引擎 + `apply_buff/remove_buff` 工具 + `add_improvised_buff` 7 关验证~~ | ✅ 已完成 — "雨夜湿冷"挂 3 回合自动消，撬锁掷骰自动 -2；turn_start/on_check/scene_leave 四时机 tick；7 关验证防滥用 |
| **Phase 3** | ~~Skill 数据模型，先只支持 `passive_modifiers`；XP/rank 成长循环；`learn_skill / grant_xp` 工具~~ | ✅ 已完成 — Skill/ActiveSkill/ReactiveSkill/Step 模型落地；`learn_skill / grant_xp` 工具上线；passive_modifiers 经一次性注入进 roll_check + audit trail；xp 跨 rank_thresholds 自动升 rank；skills 进 save/load。"潜行训练"被动 +2 |
| **Phase 4** | ~~`ActiveSkill.recipe` + 白名单 Step（不含战斗）：apply_buff / spawn_improvised / narrative_tag / roll_check / emit_modifier~~ | ✅ 已完成 — `use_skill` 工具 + Step 执行器（5 verb 白名单 + on_success/on_failure 分支）；cost(stamina/hp/gold/item) + cooldown（随叙事回合递减）。"潜行术"扣 2 耐力挂 +5 潜行 buff |
| **Phase 5** | ~~`ReactiveSkill` 触发器系统：before_roll / on_take_damage / on_scene_enter~~ | ✅ 已完成 — 三钩子接入 roll_check / deal_damage(玩家受击) / move(进房间)；before_roll 注入的 modifier 用完即清（不跨轮累积）；带再入守卫防递归。"街头直觉"偷袭前 +3 |
| **战斗子系统** | ~~敌人建模、ac/hp/伤害类型/抗性、attack/damage step~~ | ✅ 已完成 — B1+B2 上线（`start_combat` / `request_combat` / `declare_intent` / `enemy_suggest` / `end_combat` 5 工具），见 §6.8 |

**为什么先 Modifier 再 Skill/Buff**：底层定下来后 Skill/Buff 都是它的语义包装；Skill 设计未来要改，Modifier 那层不动。

#### 6.8 战斗子系统（Encounter）

> **核心定位**：战斗是 **Encounter 状态机**，由 MCP 拥有，叠在当前 Room 之上的临时层。不是一种"特殊场景"，战斗结束后场景照常。
>
> **设计取舍**：选择 **Intent 级粒度** + **MCP 提议敌人决策 + Codex 演绎** + **工具表面精简（5 个新工具）**。复杂度全部藏在 MCP 内部，Codex 只表达"我想干嘛"。

##### 6.8.1 数据模型（加到 `core/types.py`）

```python
@dataclass
class Combatant:
    id: str                          # "player" / "enemy_thug_01"
    name: str
    side: str                        # "player" / "enemy" / "neutral"
    hp: int
    max_hp: int
    ac: int                          # 被攻击 DC 基线
    speed: int                       # initiative 排序用
    damage_types_resist: dict[str, float]   # {"fire": 0.5, "slash": 1.0}
    behavior_profile: str            # "aggressive" / "cautious" / "opportunist" / ...
    skills: list[str]                # 可用技能 id
    buffs: list[Buff]                # 复用现有 Buff
    stamina: int = 0
    max_stamina: int = 0
    is_dead: bool = False


@dataclass
class Encounter:
    id: str
    combatants: dict[str, Combatant]
    turn_order: list[str]            # 按 speed 排好的 id 列表
    round: int = 1
    active_idx: int = 0              # turn_order 的指针
    zone_map: dict[str, str] = field(default_factory=dict)   # combatant_id → "front"/"back"，留给将来
    log: list[CombatEvent] = field(default_factory=list)     # 结构化事件流，供 audit & 叙事


@dataclass
class CombatEvent:
    """每个 Step 执行后产生一条，作为 Codex 叙事素材。"""
    kind: str                        # attack / miss / damage / death / buff_applied / skill_used
    actor: str
    target: str | None
    detail: dict                     # verb-specific 数据
    roll_audit: dict | None          # 引用 last_roll 那套
```

##### 6.8.2 新 Step verb（战斗专用，白名单扩展）

```
attack     args: {target, weapon?, damage_expr}   内部走 roll_check vs target.ac
damage     args: {target, amount, damage_type}    直接扣 hp（绕过命中）
heal       args: {target, amount}                 已存在，复用
flee       args: {direction?}                     判定脱离，成功则结束 encounter
```

每个 verb 走现有 Modifier 池合算 —— 武器加值、buff、抗性都自然进来，技能本身不重复实现命中逻辑（与 §6.4 "不死斩"示例一致）。

##### 6.8.3 新 MCP 工具（5 个）

| 工具 | 用途 |
|---|---|
| `start_combat(canon, improvised)` | 开战：`canon` 引用 `ENEMIES` 表的 id 列表；`improvised` 是 `{name, archetype, count}` 列表走 archetype 表生成。MCP 建 Encounter，投影玩家，roll initiative，返回首回合行动者 + 战场快照 |
| `request_combat(reason, canon, improvised, initiative_advantage?)` | Codex 或玩家提议开战。MCP 做合法性校验（敌人在场景里 / alertness 阈值 / 目标存在），通过则等效于 `start_combat` |
| `declare_intent(actor, intent, target?, skill_id?, weapon?)` | **核心工具**。当前行动者声明意图，MCP 内部跑完整意图链（命中 → 伤害 → buff → 死亡判定），返回 `list[CombatEvent]` + 下一行动者 + 新快照 |
| `enemy_suggest(enemy_id)` | 轮到敌人时，MCP 根据 `behavior_profile` 返回"建议意图"。Codex 看后调 `declare_intent` 执行 —— 可微调措辞但**不能改数值** |
| `end_combat(reason)` | 结束（全员死亡 / 玩家逃跑 / 和平解决）。把 player Combatant 的最终 hp/buff 写回 GameState，返回 loot、xp、留下的 buff |

`get_state()` 自动把 encounter 信息塞进去，不再增加额外工具。

##### 6.8.4 回合循环（Intent 级粒度示例）

```
Codex: start_combat(improvised=[{name:"码头流氓", archetype:"brute_low", count:1}])
MCP  : 按 brute_low 表生成 thug_01(hp=12, ac=13, profile=aggressive, skills=[...])
       返回 turn_order=[player, thug_01], 当前=player, snapshot

Codex: （叙事氛围）declare_intent(actor="player", intent="attack", target="thug_01")
MCP  : 跑 attack step → roll_check d20+mod vs 13 → 命中 → roll damage → 扣 hp
       返回 events=[attack, hit, damage(5), thug_01.hp 12→7], 下一行动者=thug_01

Codex: 叙事"你一刀划开他的外套，血涌出来"
Codex: enemy_suggest("thug_01")
MCP  : 返回 {intent:"attack", target:"player", reason:"aggressive + 玩家是唯一敌人"}

Codex: 演绎"流氓嘶吼着挥棒砸下"，然后 declare_intent(actor="thug_01", intent="attack", target="player")
...
```

##### 6.8.4b 三个核心问题的解法（数据源 / 过渡 / 玩家）

###### A. 敌人数据从哪来？（数值权收回 MCP）

不让 Codex 自由塞 stats —— 那是路线七要消灭的"LLM 胡编数值"。走 **Canon 表 + Improvised archetype** 双轨：

| 路径 | 来源 | 谁定 stats |
|---|---|---|
| **Canon 敌人** | `content/<world>.py` 里的 `ENEMIES: dict[str, EnemyTemplate]`，命名敌人（`thug_dock_01`、`steam_hound`） | 内容文件写死，MCP 读取 |
| **Improvised 敌人** | Codex 调 `start_combat(improvised=[{name, archetype, count}])` | MCP 按 `archetype` 查表生成 stats，Codex 只能改 `name` / flavor |

Archetype 白名单（初版）：`brute_low / brute_mid / scout / caster_low / caster_mid / boss`。每个 archetype 在 `core/types.py` 里有固定 stats 模板（hp/ac/speed/damage_expr/skills/profile）。这跟 improvised item 的 7 关验证同源：**Codex 描述风味，MCP 决定数值**。

```python
@dataclass
class EnemyTemplate:
    id: str
    name: str
    archetype: str               # 索引到 archetype 表，或 "canon" 表示自定义
    hp: int
    max_hp: int
    ac: int
    speed: int
    damage_expr: str             # "1d6+1"
    damage_type: str             # "slash" / "blunt" / "fire" / ...
    damage_types_resist: dict[str, float] = field(default_factory=dict)
    behavior_profile: str = "aggressive"
    skills: list[str] = field(default_factory=list)
    loot: list[str] = field(default_factory=list)
    flavor: str = ""             # Codex 叙事用
```

`start_combat` 改签名为：

```
start_combat(
    canon: list[str] = [],                          # 引用 ENEMIES 表的 id
    improvised: list[{name, archetype, count}] = [] # 走 archetype 表生成
)
```

###### B. 探索 → 战斗的过渡（三种合法触发路径）

| 触发路径 | 谁主导 | 如何调用 | 防滥用 |
|---|---|---|---|
| **Canon 触发** | Affordance 的 effect | effect 字段加 `start_combat: <encounter_def_id>`，`call_affordance` 执行时自动开战 | 内容文件预定义，无运行时漏洞 |
| **Codex 提议** | GM 判断局势升温（玩家拔刀 / NPC 翻脸） | `request_combat(reason, canon=[], improvised=[])` | MCP 校验：场景里必须有合法敌方对象（NPC kind + hostile 关系），或者 reason 描述对应当前 alertness ≥ 阈值 —— 防止凭空召唤敌人 |
| **玩家声明** | 玩家说"我突袭那个守卫" | Codex 调 `request_combat(initiative_advantage="player")` | MCP 给玩家第一轮 + initiative modifier；目标必须是当前场景物体 |

战斗结束后玩家回原 Room，幸存 buff 在叙事回合继续 tick（§6.8.5 已述）。`Encounter` 不替换 Room，是叠加层。

###### C. 玩家 Combatant 从 GameState 投影（不另存一份）

玩家不是"战斗时才生成的 Combatant"，而是 GameState 的**战斗视图**：

- `start_combat` 时 MCP 把玩家 `vitals` / `skills` / `buffs` / `inventory` 投影成 `Combatant(id="player", ...)` 写进 Encounter
- 战斗中对 `player` Combatant 的修改（扣 hp、加 buff）**直接写回 GameState**，Combatant 不是独立账本
- 武器加成不进 Combatant 字段，而是 Modifier 池 —— "穿皮甲"= `Modifier(target="ac", op="add", value=+2, source_kind="item", source_id="leather_armor")`，跟 §6.3 一致

为此需要在 `VitalStats` 补字段（Phase 2 之前）：

```python
@dataclass
class VitalStats:
    hp: int
    max_hp: int
    gold: int
    reputation: int
    # —— 新增 ——
    ac: int = 10                                    # 被攻击 DC 基线，靠 Modifier 加
    speed: int = 10                                 # initiative 用
    stamina: int = 0
    max_stamina: int = 0
    damage_types_resist: dict[str, float] = field(default_factory=dict)  # 默认空=全 1.0
```

副收益：平时叙事掷骰也能用 ac（被偷袭 DC）、speed（追逃判定）—— 不只是战斗资源。

##### 6.8.5 与现有系统的对接

- **Modifier 池**：战斗中的 attack/damage step 跟 `roll_check` 走同一套合算 —— 武器、buff、技能 passive 全部自动生效，零重复。
- **Buff**：复用。`BuffTick` 的 `turn_start` / `turn_end` 时机在战斗回合自然触发（之前是 narrative turn，现在战斗内同样是 turn）。
- **Improvised**：战斗中 Codex 想"抓起酒瓶砸过去" —— 走 `add_improvised`（item）→ 然后 `declare_intent(intent="attack", weapon="imp_bottle")`。不开特殊通道。
- **死亡 / 逃跑 / 和平**：`end_combat` 统一收口，写 quest_log，把幸存 buff 留给场景。

##### 6.8.6 敌人 AI：profile 表（MCP 提议层）

`enemy_suggest` 内部按 `behavior_profile` 决策，初版枚举：

| profile | 目标选择 | 行动倾向 |
|---|---|---|
| `aggressive` | 血最少的敌方 | 优先攻击；冷却时压上 |
| `cautious` | 离自己最近、威胁最低的 | 血 < 50% 时尝试 flee 或 heal |
| `opportunist` | 有 debuff 的敌方 | 优先利用对方虚弱状态 |
| `support` | 友方血最少者 | 优先 heal / buff，自卫时才攻击 |

Codex 拿到 suggest 后可改叙事措辞、改目标（同等合法目标内），但**数值/技能 cost 不能改**。

##### 6.8.7 为什么这个设计高扩展 + LLM 友好

1. **扩展性**：新敌人 = 一份数据；新战斗技能 = 一个 `ActiveSkill.recipe`；新伤害类型 = 一个 resist key。都是数据，不动引擎。
2. **LLM 友好**：Codex 战斗中只看 5 个新工具，且 `declare_intent` 承担 90%。意图层抽象贴近"我想 X"的自然表达，Codex 不需要理解 dice 数学。
3. **审计可见**：每个 `declare_intent` 返回的 `CombatEvent[]` 就是当回合"账单"，玩家可调 `explain_last_roll` 看任何一刀的来源。
4. **不破坏现有架构**：Modifier / Buff / Skill 继续运作，战斗只是 Step verb 一次扩张 + Encounter 容器。

##### 6.8.8 实施顺序

| 步骤 | 内容 | 验证标准 |
|---|---|---|
| **B1** | ~~`Combatant` + `Encounter` 模型；`EnemyTemplate` + archetype 表；`VitalStats` 补 ac/speed/stamina；`content/yanan.py` 加 `ENEMIES`；玩家投影；`start_combat` / `end_combat` 工具~~ | ✅ 已完成 |
| **B2** | ~~`attack` / `damage` Step + 接入 Modifier 池；`declare_intent` 工具；`request_combat`；`enemy_suggest`；`call_affordance` 的 `start_combat` effect；后台日志 `logs/combat.jsonl`~~ | ✅ 已完成 |
| **B3** | 多敌人 + initiative；`turn_start` / `turn_end` 时机让现有 Buff 在战斗内 tick | "濒死流血"在战斗回合每轮 -2hp |
| **B4** | 战斗复合技能：`ActiveSkill.recipe` 在战斗中执行 | "不死斩"两段攻击+挂濒死 buff 跑通 |
| **B5** | 抗性表、伤害类型分流、状态免疫 | 火怪对火抗 0.0，普通敌人对火抗 1.0 |
| **B6** | （可选）front/back zone，远近概念 | 弓箭手在 back，近战必须先到 front 才能打 |

**MVP 是 B1 + B2** —— 能跑"玩家 1v1 流氓"。其余按需推进。

### 7. 待实现：抓锚（Promote to Canon）

即兴对象在满足条件后自动晋升为 Canon（玩家互动超 N 回合、Codex 主动标记）。当前未实现。

### 8. 长程记忆：冷热分层 + Recall（✅ 已完成）

> **要解决的问题**：玩多了 context 会爆炸 / Codex 叙事记忆会丢 / 旧区域回不去原状态。
>
> **核心洞察**：提示词爆炸只能靠压缩；但**注入侧**可以做"冷热分层" —— 每回合该看到的（位置、当前 quest、最近对话）直接展开，其余只给"可调取的索引"，Codex 提到时再 `recall` 调出。
>
> **设计取舍**：不造新存储系统，扩展现有 `GameState` 字段 + 单个 `recall` 工具。冷热是 `get_state()` **输出端**的事，底层存储永远全量。

#### 8.1 三类长程记忆（数据源）

| 类 | 字段 | 状态 |
|---|---|---|
| 线索 | `GameState.clues: list[str]` | ✅ 已有，需要加 tag 索引 |
| 任务 | `GameState.quest_log: list[QuestEntry]` | ✅ 已有 stage / summary / known_facts / unresolved |
| 对话 | `GameState.dialogue_log: list[DialogueEntry]` | **新增** |
| 房间快照 | `GameState.room_snapshots: dict[room_id, RoomSnapshot]` | **新增** |

```python
@dataclass
class DialogueEntry:
    turn: int
    npc_id: str
    summary: str            # Codex 写的一句话总结，不存原文
    tags: list[str]         # ["码头", "走私", "Alma"]
    cold: bool = False      # 是否已转入冷区

@dataclass
class RoomSnapshot:
    """离开房间时序列化，回到房间时优先读取。"""
    room_id: str
    last_visited_turn: int
    objects_state: dict     # object_id → {taken, inspected, opened, modified_desc}
    flags_set_here: list[str]
```

`clues` 需要从纯字符串升级为带 tag 的结构（小改动，不破坏现有 API）：

```python
@dataclass
class Clue:
    text: str
    tags: list[str] = field(default_factory=list)
    turn: int = 0
    cold: bool = False
```

#### 8.2 热区 / 冷区分界规则

`get_state()` 改造为**分块返回**，热区直接展开，冷区只给计数索引：

| 数据 | 热区（每次注入） | 冷区（仅给索引） |
|---|---|---|
| `clues` | 最近 5 条 + tag 命中当前 quest 的 | 其余 → `"clues_cold": 12` |
| `quest_log` | `stage="active"` 的全部 | `stage="closed"` 的 summary 列表 |
| `dialogue_log` | 最近 3 轮 | 其余 → `"dialogue_cold": 24` |
| `room_snapshots` | 当前房间 + 上一个房间 | 其余房间 → `"rooms_visited": [...]` |

Codex 看到冷区索引就知道"有 12 条旧线索，需要时可调 recall"。

#### 8.3 唯一新工具：`recall`

```
recall(
    topic: str,                                              # 关键词，匹配 text + tags
    kind: "clue" | "quest" | "dialogue" | "room" | "any",
    limit: int = 5
) → list[匹配项]
```

实现就是**关键词 + tag 匹配**，不需要 embedding。一局游戏几百条记录，纯 Python 几十行搞定。

SKILL.md 加一段触发规则：**玩家提到某个 NPC / 地点 / 旧物 → 先调 `recall(topic=..., kind=...)` → 把结果纳入叙事**。

#### 8.4 房间状态持久化（"回到旧区域"问题）

`move()` 离开当前房间时：
1. 把当前房间的物品状态（哪些被取走、哪些容器被翻过、哪些 affordance 已用过）序列化进 `RoomSnapshot`
2. 写入 `GameState.room_snapshots[old_room_id]`
3. 清掉所有 `imp_` 前缀的即兴物品（既有行为）

`move()` 进入新房间时：
1. 如果 `room_snapshots[new_room_id]` 存在 → 读 snapshot，应用到 GameWorld 内存里的 Room 实例
2. 不存在 → 走 Room 的 `on_enter` 钩子（**新增字段**），可在首次进入时刷新一批 canon 物品

Room 需要补两个字段：

```python
@dataclass
class Room:
    ...existing...
    on_first_enter: list[Step] = field(default_factory=list)   # 首次进入触发
    refresh_policy: str = "snapshot"   # snapshot / regenerate / static
```

#### 8.5 Codex 侧的叙事记忆维护

光有存储不够，还得让 Codex **主动写入摘要**而不是依赖 context。SKILL.md 加规则：

- NPC 对话结束时，调 `log_dialogue(npc_id, summary, tags)` 工具（即兴扩展，落进 dialogue_log）
- 发现新线索时，调 `add_clue(text, tags)`（取代直接修改 clues 字符串）
- quest 推进时，调 `update_quest(quest_id, stage, known_facts, unresolved)`

这样**重要叙事在每回合就被持久化进 MCP**，不靠 LLM context 记。context 被压缩了也不丢。

#### 8.6 实施顺序

| 步骤 | 内容 | 验证标准 |
|---|---|---|
| **M1** | ~~`DialogueEntry` / `Clue` / `RoomSnapshot` 数据模型；`GameState` 加新字段；存档兼容~~ | ✅ 已完成 — 旧存档兼容，新字段默认空 |
| **M2** | ~~`get_state()` 改造为冷热分块返回；冷区给计数索引~~ | ✅ 已完成 — clues/quests/dialogues/rooms 四维冷热分层 |
| **M3** | ~~`recall(topic, kind, limit)` 工具 + 关键词/tag 匹配实现~~ | ✅ 已完成 — "码头"可召回所有相关线索/对话/任务 |
| **M4** | ~~`move()` 接入 `RoomSnapshot` 写入/读取；`Room.on_first_enter` 钩子~~ | ✅ 已完成 — 离开房间写快照，重回房间恢复状态 |
| **M5** | ~~`log_dialogue` / `add_clue` / `update_quest` 工具；SKILL.md 触发规则~~ | ✅ 已完成 — Codex 每场对话后调 log_dialogue，叙事持久化落账 |

**MVP M1–M5 全部完成** —— 长 session 不爆 context，旧线索可召回，房间状态可恢复，叙事记忆不丢失。

#### 8.7 与其他设计的关系

- **不替代 Claude Code 自带的 context 压缩** —— 压缩仍然会发生，但因为冷区不进 prompt，被压缩的内容少很多
- **不引入 RAG / embedding** —— 数据量小，关键词 + tag 足够
- **不破坏现有 declare 契约** —— `log_dialogue` 等新工具仍是声明型，由 Codex 提议、MCP 落账
- **与 §7 抓锚互补** —— 抓锚是把 improvised 升 canon，本节是把 canon 信息冷热分层；两者都为"长程一致性"服务

### 9. 实体能力模型：万物皆可破坏 + 属性冻结（E1/E2 ✅）

> **要解决的问题**：(a) "能被打/能挂 buff"的东西散在三个类里没统一抽象；(b) 敌人 buff 不 tick（引擎只遍历 `state.buffs`）；(c) GM 想炸牛粪/酒桶时，死物没法被伤害系统作为 target。
>
> **核心决策（学 BG3，被"冻结"洞察简化）**：**不做"有/无能力"的二分，万物皆可破坏。** 每个 `GameObject` 天生有 hp/ac/resist，牛粪、信、酒杯都能炸/烧/砸 —— 不需要"即兴授予 Damageable"那种概念。只有标 `indestructible` 的（墙、大地）才打不动。
>
> **省 token 靠冻结，不靠二分**：这些战斗属性默认**不进 `get_scene()`**（冻结）。Codex 平时看到的牛粪就是"一坨牛粪"，零负担；玩家做出破坏意图时引擎才解冻结算。这是 §8 冷热分层思路复用到实体属性上。

#### 9.1 万物皆实体，能力靠字段表达（不是二分开关）

D&D/BG3 的智慧：桶和史莱姆是同一种东西 —— 都是有 HP/AC 的 Entity，引擎不区分活物死物，所以你能炸桶、烧蛛网、推箱子砸人，全走同一套伤害管线。我们照此：

| 能力 | 怎么表达 | 是不是二分 |
|---|---|---|
| **可破坏** | 万物有 `hp`/`ac`，默认能打；`indestructible=True` 才打不动 | **否**，万物皆可（除墙/大地） |
| **可挂 buff** | 万物有 `buffs` 列表（默认空），着火/中毒都能挂 | **否**，万物皆可 |
| **能行动（Actor）** | 有 `speed`/`behavior_profile`、在 `turn_order` 里 | **是**，牛粪不会主动行动 |

之前纠结"信是不是实体""要不要给牛粪授予 Damageable"——**全是伪问题**。信是 hp=5 的 Entity，只是平时冻结、没人想烧。真问题只有"什么时候让模型知道它的属性"，答案是冻结+按需解冻。

#### 9.2 为什么 Protocol 而非多继承

| | 多继承 mixin | Protocol + 自由函数（选定） |
|---|---|---|
| 现有类要改继承链 | 是（高风险，`GameState`/`Combatant`/`GameObject` 不共祖先） | 否（已碰巧满足字段契约） |
| 组合爆炸（2³ 种） | 要预定义中间类 | 无，满足哪几个就是哪几个 |
| 共享逻辑放哪 | 对象方法里（OOP） | 自由函数里（data-oriented） |
| 契合现有风格 | ✗ | ✅ 账房 = 纯数据 + 引擎函数 |

决定性约束：`GameState` 根本不该 `is-a` 实体（它是游戏快照，玩家只是其一部分），多继承在这里语义就错了。

两层用法，分工明确（实现踩坑后定下）：

1. **Protocol** —— 只给函数签名做**静态类型标注**（mypy/pyright），表达"这函数吃任何能被打的东西"。**不用于运行期 `isinstance`**。
2. **`is_*()` helper** —— 运行期按**值**判定能力。`@runtime_checkable` 只看属性名存在、不看值，会把 `hp=None` 的信也判成 Damageable，故不可靠 —— 这是 dataclass 字段是实例属性、类上查不到导致的，是 Protocol 的已知局限。

```python
from typing import Protocol

class Damageable(Protocol):      # 仅作静态标注，不加 runtime_checkable
    id: str
    hp: int
    max_hp: int
    damage_types_resist: dict[str, float]
    on_destroyed: list           # list[Step]，hp 归零时触发

class BuffBearer(Protocol):
    id: str
    buffs: list                  # list[Buff]

class Actor(Protocol):           # 必然也满足 BuffBearer + Damageable
    id: str
    speed: int
    behavior_profile: str

def is_damageable(obj) -> bool:  # 运行期判定：看值（hp 非 None）
    return getattr(obj, "hp", None) is not None
def is_buff_bearer(obj) -> bool:
    return isinstance(getattr(obj, "buffs", None), list)
def is_actor(obj) -> bool:
    return getattr(obj, "speed", None) is not None and bool(getattr(obj, "behavior_profile", ""))
```

**逻辑走自由函数，不进对象方法**（沿用现有 `_emit_buff_modifiers` 等写法，只把参数从 `state` 泛化成 `bearer`）：

```python
def emit_buff_modifiers(bearer: BuffBearer, timing: str) -> list[Modifier]: ...
def purge_expired_buffs(bearer: BuffBearer): ...
def deal_damage(target: Damageable, amount, damage_type): ...
```

#### 9.3 字段默认值（万物皆有，按耐久度调）

`GameObject` 实际字段（E1 已落地）：

```python
hp: int = 5          # 耐久度建议：fragile=1 / 默认=5 / sturdy=15
max_hp: int = 5
ac: int = 5          # 死物易命中，默认低
indestructible: bool = False         # 墙/大门/大地标 True
damage_types_resist: Dict[str, float] = {}   # 空=全 1.0
on_destroyed: list[Step] = []        # hp 归零触发
buffs: list[Buff] = []               # 着火/中毒等持续效应
```

`is_damageable(obj)` = `not indestructible and hp 字段存在`。`deal_damage` 的 target 认任何 damageable，不认身份 —— 火球术不需要知道打的是活物还是死物（E3 实现统一伤害入口）。

`on_destroyed` 复用 Step 白名单，零新机制。酒桶炸了 = `[spawn_improvised(火焰), reveal_objects(桶底钥匙), narrative_tag(酒香四溢)]`。**安全约束**：探索中破坏死物时，`on_destroyed` 的 verb 应比战斗 Step 更窄（spawn_improvised / narrative_tag / reveal_objects），不许借炸牛粪偷偷 set flag 解锁主线门。

#### 9.4 内容作者只需调耐久度，不需判定"加不加能力"

旧版这里有张"该不该加 Damageable"的判定表 —— 万物皆可破坏后**作废了**。现在加内容时只有一个问题：**这东西多结实？** fragile/默认/sturdy 三档调 hp，真打不动的（墙、地面、天空）标 `indestructible=True`。不再纠结"信算不算实体"。

#### 9.5 顺带修掉的现存 bug（✅ E2 已修）

修复前 `Combatant.buffs` 是死字段 —— `_advance_turn` 只 tick `state.buffs`（玩家），没代码遍历 `Combatant.buffs`，"濒死流血每回合 -2"挂敌人身上不生效（§6.8.8 B3 实际未达标）。

E2 修复：buff 引擎泛化成 bearer-based，战斗每轮结束（`declare_intent` 内 round+1 处）调 `_tick_combat_round` 遍历所有存活 combatant 跑 tick。`add_improvised_buff` 加 `bearer_id` 参数可把 debuff 挂到敌人。实测濒死流血敌人 hp 每轮 -2、归零标死。**分层**：玩家 roll buff 仍刷进全局 modifier 池影响掷骰；敌人 buff 只作用自身 hp、不进全局池（避免污染玩家检定）。

#### 9.6 实施顺序

| 步骤 | 内容 | 验证标准 |
|---|---|---|
| **E1** | ~~Protocol（静态标注）+ `is_*()` helper；`GameObject` 万物皆有 hp/ac/resist/on_destroyed/buffs，indestructible 标记~~ | ✅ 已完成 — 信/牛粪默认可破坏，墙不可破坏 |
| **E2** | ~~buff 引擎泛化成 bearer-based；`add_improvised_buff` 加 `bearer_id`；战斗每轮 `_tick_combat_round`~~ | ✅ 已完成 — 玩家 buff 无回归；敌人濒死流血每轮 -2hp |
| **E3** | `deal_damage(target)` 统一伤害入口（探索+战斗共用，不需开 Encounter）；`on_destroyed` Step 执行；属性"解冻"（破坏意图时才把 hp/ac 吐给 Codex） | 鞭炮炸牛粪 / 火球打酒桶：hp 归零 → 触发臭气/起火/掉落；平时 get_scene 不含战斗属性 |
| **E4** | （依赖 E1-E3）Aura 环境光环：buff 绑条件而非实体，每回合对满足条件的 bearer 挂/撤 | "雨天室外所有 bearer 自动湿冷，进室内自动消" |

**E1+E2 已落地**（抽象 + 修 bug）。E3 是关键的统一伤害入口 —— "鞭炮炸牛粪""火球打酒桶""椅子砸窗"都走它，配合属性冻结/解冻。E4 才是 Aura。

#### 9.7 与 Aura（环境光环）的关系

Aura 是"buff 绑在**条件**上而非实体上，引擎每回合检查谁满足、动态挂/撤"。它**依赖本节的实体抽象** —— 没有统一的 bearer 可遍历，"对所有实体施加湿冷"就无从写起。

故 Aura 排在 E4（实体抽象之后）。**当前用 flag 方案替代**：进雨区 `add_improvised_buff(expire_on=[{flag:"sheltered"}])`，进室内 set flag `sheltered` → buff 自动过期。零新代码实现"离开雨区自动好"，等多实体环境效应需求出现再升级为正式 Aura。

---

## MCP 工具清单

共 28 个工具，定义在 `mcp_server.py`：

### 基础游戏工具（8 个）
| 工具 | 用途 |
|---|---|
| `start_game(world)` | 启动 yanan，返回 WorldCanon + 初始场景 |
| `get_scene()` | 当前房间 + 物体 + affordance 菜单 + enemy_profiles |
| `inspect_object(object_id)` | 检查物体，发现 hidden_clue / reveal objects |
| `call_affordance(object_id, verb)` | 执行物体方法，支持 `start_combat` effect，推进回合 |
| `move(direction)` | 移动，尊重 locked_exits，换房清 imp_ 物品 |
| `take_item(object_id)` | 拾取，尊重 takable 标记 |
| `add_improvised(items)` | 即兴物品 7 关验证入包 |
| `get_state()` | 完整状态快照 + encounter（战斗中） |

### GM 扩展工具（2 个）
| 工具 | 用途 |
|---|---|
| `set_custom_attribute(scope, key, value, value_type, label, note)` | 添加/更新 GM 自定义玩家或世界属性 |
| `remove_custom_attribute(scope, key)` | 删除 GM 自定义属性 |

### Modifier 工具（4 个）✅ Phase 1
| 工具 | 用途 |
|---|---|
| `roll_check(reason, sides, modifier, dc)` | 骰子检定，1d20 + modifier vs DC，自动合算 Modifier 池 + Buff on_check tick，返回 critical_success/success/failure/critical_failure |
| `add_modifier(source_kind, target, op, ...)` | 向 Modifier 池添加修正，selector 匹配掷骰理由 |
| `remove_modifier(modifier_id?, source_kind?, source_id?)` | 精确或批量移除修正 |
| `explain_last_roll()` | 返回上次掷骰的完整 audit trail（含 full/result/hidden 分级） |

### Buff 工具（3 个）✅ Phase 2
| 工具 | 用途 |
|---|---|
| `add_improvised_buff(name, desc, polarity, target, op, value, duration, timing?, reason?, visible?, tags?)` | Codex 提议即兴 buff/debuff，经 7 关验证后生效：name 非空/不重复、polarity 合法、target 白名单（roll/dc/hp/narrative_tag）、value ±5、duration 1-5、每回合 1 个、身上最多 3 个 |
| `apply_buff(buff_id)` | 手动应用预定义 buff（Phase 3+ 扩展） |
| `remove_buff(buff_id)` | 移除 buff 及其关联 modifier |

### 战斗工具（5 个）✅ B1+B2
| 工具 | 用途 |
|---|---|
| `start_combat(canon, improvised)` | Canon 命名敌人 + archetype 即兴敌人生成，建 Encounter |
| `request_combat(reason, canon, improvised, initiative_advantage?)` | Codex/玩家提议开战，MCP 校验合法性后等效 start_combat |
| `declare_intent(actor, intent, target?, skill_id?, weapon?)` | 核心战斗动作：attack/defend/flee/use_item，走 roll_check + Modifier 池 |
| `enemy_suggest(enemy_id)` | MCP 按 behavior_profile 建议敌人意图，Codex 可微调措辞 |
| `end_combat(reason)` | 结束战斗，player HP 写回 GameState，返回战利品/击败列表 |

### 长程记忆工具（4 个）✅ §8
| 工具 | 用途 |
|---|---|
| `recall(topic, kind, limit)` | 关键词+tag 检索冷区线索/任务/对话/房间快照 |
| `log_dialogue(npc_id, summary, tags)` | Codex 在 NPC 对话结束后写入一句话摘要 |
| `add_clue(text, tags)` | Codex 发现新线索时写入结构化 Clue |
| `update_quest(quest_id, stage?, known_facts?, unresolved?)` | 推进任务阶段/已知事实/未解问题 |

### 持久化工具（2 个）
| 工具 | 用途 |
|---|---|
| `save_game(slot)` | 存档到 `saves/`（JSON，含 VitalStats.ac/speed/stamina） |
| `load_game(slot)` | 从 `saves/` 读档 |

---

## 项目文件

```
Text Adventure Prototype/
├── AGENTS.md                  # 本文件
├── .mcp.json                  # MCP 配置 → Codex 启动 mcp_server.py
├── .env / .env.example        # [legacy] LLM 配置（MCP 模式不需要）
├── requirements.txt           # mcp, openai
│
├── mcp_server.py              # ★ 唯一入口：MCP 服务器，28 个工具
│
├── .Codex/skills/play/
│   └── SKILL.md               # /play 技能：GM 行为指南
│
├── core/
│   └── types.py               # 所有数据模型（GameState, InventoryItem, Affordance, ...）
│
├── content/
│   └── yanan.py               # 《亚楠·雨夜委托》4 房间，蒸汽朋克
│
├── runtime/
│   ├── game_world.py          # 世界容器：房间/物体/affordance 注册与查询
│   └── rule_engine.py         # affordance 执行 + improvised 验证
│
├── saves/                     # 存档目录（JSON）
│
├── logs/
│   └── combat.jsonl           # 战斗后台日志（§6.8.8 B2）
│
└── tests/
    └── test_yanan_flow.py     # yanan 流程测试
```

> 路线一～八的遗留文件（`main.py` / `engine.py` / `game_agent.py` / `repl.py` / `tui.py` / `llm_client.py` / `config.py` 等）已于文档整理时删除。需要历史参考查 git history。

### 数据模型（`core/types.py`）

完整字段定义见对应设计章节，此处仅作速查索引。

| 模型 | 状态 | 定义 |
|---|---|---|
| `GameState` | 核心 | 全局状态快照容器（position/inventory/flags/vitals/quest_log/buffs/clues/dialogue_log/room_snapshots…） |
| `ActorProfile` / `VitalStats` / `WorldTime` / `QuestEntry` | 核心 | 玩家身份 / 可落账属性 / 世界时间 / 任务日志 |
| `Room` / `GameObject` / `Affordance` | 核心 | 房间 / 物体 / 物体方法（见 §3 Affordance、物品语义节） |
| `InventoryItem` / `ImprovisedItem` | 核心 | 背包物品 / 即兴物品（见 §4） |
| `WorldCanon` | 核心 | 世界观锚句（见 §2） |
| `Modifier` | ✅ Phase 1 | 修正原子（见 §6.2） |
| `Buff` / `BuffTick` | ✅ Phase 2 | Modifier 容器 + 时机钩子（见 §6.2、§6.8.1） |
| `Skill` / `ActiveSkill` / `ReactiveSkill` / `Step` | Phase 3-5 | 技能与复合动作（见 §6.2） |
| `EnemyTemplate` / `Combatant` / `Encounter` / `CombatEvent` / `ENEMY_ARCHETYPES` | ✅ B1 | 战斗模型（见 §6.8.1、§6.8.4b-A） |
| `Clue` / `DialogueEntry` / `RoomSnapshot` | ✅ §8 | 长程记忆三件套（见 §8.1） |
| `Damageable` / `BuffBearer` / `Actor` | 待实现 §9 | 实体能力 Protocol（见 §9.2） |

### 世界模型（角色 / 时间 / 地理）

`start_game()`、`get_scene()`、`get_state()` 都会返回 `state_context`，作为 GM 的权威上下文：

- `profile`：玩家角色身份，不决定数值，但约束叙事口吻。
- `vitals`：血量、金币、声望等可计算属性。Codex 不应自行增减，后续需要通过工具效果或专门规则落账。
- `conditions`：纯叙事状态标签，如 `rain-soaked`。**不影响掷骰**——任何会影响掷骰的状态必须建模成 Buff（见 §6）。
- `relationships`：NPC/势力对玩家的关系标签。
- `world_time`：日期、时段、天气、分钟数。每个确定性回合默认推进 5 分钟。
- `quest_log`：任务阶段、已知事实、未解问题，供 GM 和未来内容生成 agent 接续剧情。
- `custom.player_attrs` / `custom.world_attrs`：GM 临场扩展字段，例如 `crit_rate`、`celestial_omen`。通过 `set_custom_attribute` 写入，支持 text / int / float / bool / json，并随存档保存。

房间带 `area` / `zone` / `coords` / `tags`。`coords` 是轻量相对坐标，不做寻路引擎；它让后台或 GM 能知道"公寓北/南/码头东侧"这类空间关系，避免凭空接错场景。

### 物品语义（三层，不做继承）

物品不使用 Python 继承树，而是拆成三层语义：`kind` 表达"物品类型"，`named_tags` 表达"具名身份/剧情锚点"，`modifiers` 表达"修饰词/物理特性"。`get_scene()` 会返回 `kind`、`named_tags`、`modifiers`、`traits`、`semantic_methods`、`prompt_hints`、`prompt_priority`，供 Codex 判断自然语言动作；真正改变状态仍必须走 `inspect_object`、`take_item`、`call_affordance` 等工具。

| kind | 用途 | 基类方法 |
|---|---|---|
| `item` | 普通可携带物品 | inspect, take, show |
| `scenery` | 固定场景物 | inspect |
| `document` | 信件、清单、告示 | inspect, read, copy, tear, burn |
| `key` | 钥匙、凭证、许可物 | inspect, take, show, unlock |
| `clue` | 线索性物品 | inspect, take, show, connect |
| `tool` | 工具或临时器具 | inspect, take, use |
| `consumable` | 一次性消耗品 | inspect, take, use, consume |
| `npc` | 可对话角色 | inspect, talk, question, show |
| `trace` | 痕迹、环境证据 | inspect, analyze, record |
| `container` | 容器或可翻找对象 | inspect, open, search |

常用 `named_tags`：

| named_tag | 用途 | 追加语义 |
|---|---|---|
| `quest_item` | 关键物品，优先注入 GM 注意 | protect, remember |
| `evidence` | 证据，可展示、比对、质询 | show, compare, confront |
| `dock_access` | 码头/仓库通行凭证 | show, unlock |
| `payment` | 报酬、定金、交易筹码 | count, offer, hide |
| `contraband` | 违禁品或走私证据 | inspect, expose, hide |

常用 `modifiers`：

| modifier | 用途 | 追加语义 |
|---|---|---|
| `small` | 小物件，可藏匿/投掷/丢弃 | palm, hide, throw, drop |
| `concealable` | 易藏匿物 | palm, hide, smuggle |
| `noisy` | 可制造声响 | throw, tap, rattle |
| `fragile` | 易损物，粗暴使用有代价 | handle_carefully |
| `heavy` | 沉重物，搬动/投掷动静大 | drag, drop, lever |
| `wet` | 潮湿物，受雨水/水痕影响 | wring, mark |

例：`dock_key` 是 `kind="key"`，同时有 `named_tags=["quest_item", "dock_access"]` 和 `modifiers=["small", "concealable", "noisy"]`。它可以被 GM 视作关键钥匙，也可以作为小物件制造声响；但丢弃或投掷关键物品应产生风险，而不能静默改状态。

### 世界

| 世界 | 文件 | 房间 | 风格 |
|---|---|---|---|
| yanan | `content/yanan.py` | 4 | 蒸汽朋克，暗杀委托 |

---

## 架构探索历程

设计沿革的细节见 git history，此处只留每条路线的一句结论。

| 路线 | 结论 |
|---|---|
| 一～五 | 已否决：两层 LLM 串行 / 酒馆集成等，因速度慢、耦合深、生态依赖被弃 |
| 六：约束注入 + Structured Output | ✅ 实现后废弃。JSON Schema strict + 合法动作清单解决了胡编问题，但仍是"Python 自跑 agentic loop" |
| 七：GM 化转型 | ✅ 核心设计保留。双层世界状态、WorldCanon、即兴物品 TTL、骰子作叙事扰动器——全部沿用至今 |
| 八：Affordance 系统 | ✅ 保留。物体自带方法表取代 ItemUse 全局查找表，`call_affordance` 直接执行 |
| 九：Skill + MCP Server | ★ 当前架构。Codex 接管 agentic loop（自带 LLM/TUI/session），Python 退为纯状态服务器 |

```
旧：main.py → GameEngine → GameAgent → LLMClient → API → 解析 → RuleEngine → REPL 显示
新：Codex ↔ MCP tools ↔ Python state + rules
```

---

## 启动方式

唯一入口：在 Codex 中输入 `/play` 或说"开始游戏"。

`.mcp.json` 已配置好 `mcp_server.py` 路径，Codex 自动拉起 MCP Server 进程，session 期间常驻内存。`/play` 触发 SKILL.md → 调用 `start_game` → 返回场景 + WorldCanon → Codex 开始叙事。
