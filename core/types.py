"""Core data types for the AI Text Adventure game."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any, Protocol


# ── 路线七 阶段一：WorldCanon + InventoryItem ──────────────────────
# ── 路线七 阶段二：ImprovisedItem ─────────────────────────────────
# ── 路线八：Affordance（物品方法，替换 ItemUse 表）─────────────────

IMPROVISED_CATEGORIES = {
    "fragment":   "碎片/布条/碎纸/木屑——从场景剥离的小块",
    "consumable": "食物/饮料/药水/火柴——一次性消耗品",
    "trinket":    "硬币/钮扣/小石子/护身符——可携带的小物件",
    "tool":       "绳子/铁丝/钉子/小刀——临时凑合的工具",
    "clue":       "纸条/标记/印记——单纯的信息载体",
    "trace":      "脚印/血迹/气味——附着于场景的痕迹（不入背包）",
}

IMPROVISED_SIZES = ["tiny", "small", "medium"]

MAX_IMPROVISED_IN_INVENTORY = 4
MAX_IMPROVISED_PER_TURN = 2
IMPROVISED_DEFAULT_TTL = 3
IMPROVISED_MAX_TTL = 5


@dataclass
class Affordance:
    """物品的一个可调用方法。替代 ItemUse 查找表。

    verb       — 动词，如 "read" / "tear" / "unlock"
    desc       — 给 LLM 看的一行说明
    requires_item — 执行时必须持有的背包物品 ID（可选）
    requires_flag — 执行时必须已设置的 flag（可选）
    effect     — 与旧 ItemUse.effect 相同结构：
                   unlock_exit, flags, clues, message, narrative
    consume_self  — 执行后物品自身是否消耗（从背包/场景移除）
    consume_item  — 执行后 requires_item 是否消耗
    """
    verb: str
    desc: str = ""
    requires_item: Optional[str] = None   # 背包物品 ID
    requires_flag: Optional[str] = None   # state.flags key
    effect: dict = field(default_factory=dict)
    consume_self: bool = False
    consume_item: bool = False


ITEM_KIND_DEFS = {
    "item": {
        "desc": "普通可携带物品，具体用途由上下文或 affordance 决定。",
        "base_methods": ["inspect", "take", "show"],
    },
    "scenery": {
        "desc": "固定场景物，通常不能拾取，用于观察、遮蔽或气氛。",
        "base_methods": ["inspect"],
    },
    "document": {
        "desc": "可承载文字信息的文书、信件、清单或告示。",
        "base_methods": ["inspect", "read", "copy", "tear", "burn"],
    },
    "key": {
        "desc": "用于证明身份、解锁出口或触发许可的钥匙/凭证。",
        "base_methods": ["inspect", "take", "show", "unlock"],
    },
    "clue": {
        "desc": "线索性物品，本身的价值主要在信息和指向性。",
        "base_methods": ["inspect", "take", "show", "connect"],
    },
    "tool": {
        "desc": "可携带工具，可用于撬、钩、照明、固定或临时处理障碍。",
        "base_methods": ["inspect", "take", "use"],
    },
    "consumable": {
        "desc": "可消耗物品，例如火柴、药剂、食物或一次性材料。",
        "base_methods": ["inspect", "take", "use", "consume"],
    },
    "npc": {
        "desc": "可对话角色，适合询问、展示物品、观察反应。",
        "base_methods": ["inspect", "talk", "question", "show"],
    },
    "trace": {
        "desc": "痕迹或环境证据，通常不入背包，只能观察、分析或记录。",
        "base_methods": ["inspect", "analyze", "record"],
    },
    "container": {
        "desc": "容器或可翻找对象，可能揭示隐藏物体。",
        "base_methods": ["inspect", "open", "search"],
    },
}


ITEM_NAMED_TAG_DEFS = {
    "quest_item": {
        "desc": "关键物品，和主线、任务、解锁或重要证据有关。",
        "base_methods": ["protect", "remember"],
        "prompt_priority": 90,
        "prompt_hint": "优先提醒 GM：这是关键物品，不要轻易忽略、遗失或消耗。",
    },
    "evidence": {
        "desc": "证据物，可用于质询、交换情报或推进推理。",
        "base_methods": ["show", "compare", "confront"],
        "prompt_priority": 70,
        "prompt_hint": "适合展示给 NPC、和其他线索交叉验证，或作为剧情证据。",
    },
    "dock_access": {
        "desc": "码头/仓库通行凭证或门禁相关物。",
        "base_methods": ["show", "unlock"],
        "prompt_priority": 80,
        "prompt_hint": "和码头7号、仓库通行、联络人识别强相关。",
    },
    "payment": {
        "desc": "报酬、定金或交易筹码。",
        "base_methods": ["count", "offer", "hide"],
        "prompt_priority": 60,
        "prompt_hint": "可作为交易筹码，也可能带来被盯上的风险。",
    },
    "contraband": {
        "desc": "违禁品或走私证据。",
        "base_methods": ["inspect", "expose", "hide"],
        "prompt_priority": 80,
        "prompt_hint": "这是危险证据，公开或隐瞒都会影响局势。",
    },
}


ITEM_MODIFIER_DEFS = {
    "small": {
        "desc": "小物件，便于藏匿、递交、投掷或制造声响。",
        "base_methods": ["palm", "hide", "throw", "drop"],
        "prompt_hint": "可作为小型即兴道具，例如丢出去制造声响或转移注意。",
    },
    "concealable": {
        "desc": "易藏匿物，可放入口袋、袖口或暗处。",
        "base_methods": ["palm", "hide", "smuggle"],
        "prompt_hint": "适合偷偷携带、藏起或在社交场景中隐蔽使用。",
    },
    "noisy": {
        "desc": "可制造声音的物件。",
        "base_methods": ["throw", "tap", "rattle"],
        "prompt_hint": "可用于制造声响、引开视线或测试空间回音。",
    },
    "fragile": {
        "desc": "易损物，粗暴使用可能损坏或留下痕迹。",
        "base_methods": ["handle_carefully"],
        "prompt_hint": "如果玩家粗暴处理，应考虑损坏、噪音或痕迹代价。",
    },
    "heavy": {
        "desc": "沉重物，投掷/搬动会制造更大声响或需要力气。",
        "base_methods": ["drag", "drop", "lever"],
        "prompt_hint": "可制造明显动静，也可能难以悄悄处理。",
    },
    "wet": {
        "desc": "潮湿物或处于雨水环境，可能打滑、洇湿、留下水痕。",
        "base_methods": ["wring", "mark"],
        "prompt_hint": "潮湿状态会影响点火、书写、足迹和手感。",
    },
}


@dataclass
class ImprovisedItem:
    """LLM 即兴生成的临时物品，带 TTL，不入 canon。"""
    id: str
    name: str
    desc: str = ""
    category: str = "trinket"
    size: str = "small"
    ttl: int = IMPROVISED_DEFAULT_TTL
    tags: List[str] = field(default_factory=list)

    def to_inventory_item(self) -> "InventoryItem":
        kind = self.category if self.category in ITEM_KIND_DEFS else "item"
        return InventoryItem(
            id=self.id,
            name=self.name,
            desc=self.desc,
            tags=self.tags + [f"即兴:{self.category}", f"尺寸:{self.size}"],
            ttl=self.ttl,
            kind=kind,
            modifiers=["small"] if self.size in {"tiny", "small"} else [],
        )


@dataclass
class WorldCanon:
    """世界观锚句 —— 用 prompt 工程换数据工程。"""
    setting_blurb: str = ""
    forbidden: List[str] = field(default_factory=list)
    aesthetic_tags: List[str] = field(default_factory=list)
    name_style: str = ""

    def to_prompt_block(self) -> str:
        lines = ["【世界观锚句（叙事须遵守此约束）】"]
        if self.setting_blurb:
            lines.append(f"设定：{self.setting_blurb}")
        if self.forbidden:
            lines.append(f"禁止元素：{'、'.join(self.forbidden)}")
        if self.aesthetic_tags:
            lines.append(f"美学标签：{'、'.join(self.aesthetic_tags)}")
        if self.name_style:
            lines.append(f"命名风格：{self.name_style}")
        return "\n".join(lines)


@dataclass
class InventoryItem:
    """Rich inventory item — AI 可见，支持 TTL 自动过期。"""
    id: str
    name: str
    desc: str = ""
    tags: List[str] = field(default_factory=list)
    ttl: int = -1
    kind: str = "item"
    named_tags: List[str] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)
    # 装备字段（§11 RPG 数值骨架）
    equip_slot: str = ""            # 槽位 key，空=不可装备
    damage_expr: str = ""           # 武器伤害表达式 "1d8"
    damage_type: str = "blunt"      # 武器伤害类型
    scaling: dict = field(default_factory=dict)      # {"str":1.0,"dex":0.5}
    defense: int = 0                # AC 加成
    resist: dict = field(default_factory=dict)       # {"fire":0.5}
    attr_bonus: dict = field(default_factory=dict)   # {attr_key: +N}
    use_effect: dict = field(default_factory=dict)   # 消耗品效果，如 {"heal":10,"restore_sp":3}

    @classmethod
    def from_object(cls, obj: "GameObject") -> "InventoryItem":
        return cls(
            id=obj.id,
            name=obj.name,
            desc=obj.description,
            kind=obj.kind,
            named_tags=list(obj.named_tags),
            modifiers=list(obj.modifiers),
            # 装备/消耗品数据随拾取迁移——否则场景里捡到的武器永远不可装备
            equip_slot=obj.equip_slot,
            damage_expr=obj.damage_expr,
            damage_type=obj.damage_type,
            scaling=dict(obj.scaling),
            defense=obj.defense,
            resist=dict(obj.resist),
            attr_bonus=dict(obj.attr_bonus),
            use_effect=dict(obj.use_effect),
        )


@dataclass
class ActorProfile:
    """Player-facing identity. Kept light; detailed character sheets can come later."""
    name: str = "你"
    role: str = "受雇者"
    background: str = "接下雨夜暗杀委托的外来者"


@dataclass
class VitalStats:
    """Minimal player resources that need deterministic bookkeeping."""
    hp: int = 10
    max_hp: int = 10
    gold: int = 0
    reputation: int = 0
    ac: int = 10                                    # 被攻击 DC 基线，靠 Modifier 加
    speed: int = 10                                 # initiative 用
    stamina: int = 0
    max_stamina: int = 0
    damage_types_resist: dict = field(default_factory=dict)  # {"fire":0.5,...}
    # RPG 数值骨架 (§11)
    level: int = 1
    exp: int = 0
    attributes: dict = field(default_factory=dict)  # {attr_key: value}，key 由 RuleBook 定义
    pending_attr_points: int = 0  # 待分配属性点


@dataclass
class WorldTime:
    """In-world clock separate from mechanical turn count."""
    calendar: str = "王国历302年 雨季"
    day: int = 17
    phase: str = "deep_night"
    minute: int = 0
    weather: str = "heavy_rain"


@dataclass
class QuestEntry:
    """Structured quest progress for GM and future content-generation agents."""
    id: str
    title: str
    stage: str
    summary: str = ""
    deadline: str = ""
    known_facts: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)




# ── 路线九 Phase 2：Buff 引擎 ────────────────────────────────────────

BUFF_POLARITIES = {"buff", "debuff", "neutral"}
BUFF_TICK_TIMINGS = {"turn_start", "turn_end", "on_check", "scene_leave"}
IMPROVISED_BUFF_TARGETS = {"roll", "dc", "hp", "narrative_tag"}  # 不许动 gold/reputation
IMPROVISED_BUFF_MAX_PER_TURN = 1
IMPROVISED_BUFF_MAX_ACTIVE = 3
IMPROVISED_BUFF_MAX_VALUE = 5
IMPROVISED_BUFF_MAX_DURATION = 5


@dataclass
class BuffTick:
    """buff 在某个时机做的事——可以发射 modifier。run_steps 保留给 Phase 4。"""
    emit_modifiers: List["Modifier"] = field(default_factory=list)
    run_steps: List[dict] = field(default_factory=list)


@dataclass
class Buff:
    """带 TTL 的 Modifier 容器 + 触发钩子。

    ticks 的 key 来自 BUFF_TICK_TIMINGS。
    expire_on 是 OR 条件列表，例如 [{"turns": 3}] 或 [{"turns": 3}, {"flag": "dried_off"}]。
    """
    id: str
    name: str
    desc: str
    polarity: str = "neutral"            # buff / debuff / neutral
    source_kind: str = "improvised"      # skill / item / scene / npc / improvised
    source_id: str = ""
    tags: List[str] = field(default_factory=list)
    stacks: int = 1
    max_stacks: int = 1
    ticks: Dict[str, BuffTick] = field(default_factory=dict)
    expire_on: List[dict] = field(default_factory=list)
    visible: str = "result"              # full / result / hidden


# ── 路线九 §8：长程记忆（冷热分层 + Recall）───────────────────────


@dataclass
class Clue:
    """结构化线索，替代 plain str。"""
    text: str
    tags: List[str] = field(default_factory=list)
    turn: int = 0
    cold: bool = False


@dataclass
class DialogueEntry:
    """NPC 对话摘要，Codex 写入，不下原文。"""
    turn: int
    npc_id: str
    summary: str
    tags: List[str] = field(default_factory=list)
    cold: bool = False


@dataclass
class RoomSnapshot:
    """离开房间时序列化，回到房间时优先读取以恢复状态。"""
    room_id: str
    last_visited_turn: int
    objects_state: Dict[str, dict] = field(default_factory=dict)  # object_id → {taken, inspected, opened}
    flags_set_here: List[str] = field(default_factory=list)


@dataclass
class GameState:
    """The complete state of the game at a point in time."""
    position: str
    inventory: List[InventoryItem] = field(default_factory=list)
    flags: Dict[str, bool] = field(default_factory=dict)
    alertness: int = 0
    clues: List[Clue] = field(default_factory=list)
    turn: int = 0
    profile: ActorProfile = field(default_factory=ActorProfile)
    vitals: VitalStats = field(default_factory=VitalStats)
    conditions: List[str] = field(default_factory=list)
    relationships: Dict[str, str] = field(default_factory=dict)
    world_time: WorldTime = field(default_factory=WorldTime)
    quest_log: List[QuestEntry] = field(default_factory=list)
    player_attrs: Dict[str, dict] = field(default_factory=dict)
    world_attrs: Dict[str, dict] = field(default_factory=dict)
    dialogue_log: List[DialogueEntry] = field(default_factory=list)
    room_snapshots: Dict[str, RoomSnapshot] = field(default_factory=dict)
    buffs: List[Buff] = field(default_factory=list)
    skills: List["Skill"] = field(default_factory=list)
    improvised_buff_count_this_turn: int = 0
    equipped: dict = field(default_factory=dict)   # {slot: item_id}，§11 RPG 数值骨架

    def has_item(self, item_id: str) -> bool:
        return any(i.id == item_id for i in self.inventory)

    def get_item(self, item_id: str) -> Optional[InventoryItem]:
        for i in self.inventory:
            if i.id == item_id:
                return i
        return None

    def add_item(self, item: InventoryItem):
        if not self.has_item(item.id):
            self.inventory.append(item)

    def remove_item(self, item_id: str):
        self.inventory = [i for i in self.inventory if i.id != item_id]

    def has_clue(self, text: str) -> bool:
        return any(c.text == text for c in self.clues)

    def add_clue(self, text: str, tags: List[str] | None = None, turn: int | None = None):
        if not self.has_clue(text):
            self.clues.append(Clue(text=text, tags=tags or [], turn=turn or self.turn))

    def tick_ttl(self):
        expired = []
        for item in self.inventory:
            if item.ttl > 0:
                item.ttl -= 1
                if item.ttl == 0:
                    expired.append(item.id)
        self.inventory = [i for i in self.inventory if i.ttl != 0]
        return expired


@dataclass
class Room:
    """A room/location in the game world."""
    id: str
    name: str
    base_description: str
    exits: Dict[str, str] = field(default_factory=dict)
    objects: List[str] = field(default_factory=list)
    locked_exits: Dict[str, str] = field(default_factory=dict)
    area: str = ""
    zone: str = ""
    coords: Tuple[int, int] = (0, 0)
    tags: List[str] = field(default_factory=list)
    enemies: List[str] = field(default_factory=list)
    on_first_enter: List[Dict[str, Any]] = field(default_factory=list)
    refresh_policy: str = "snapshot"   # snapshot / regenerate / static


@dataclass
class GameObject:
    """An object in the game world with its own affordances (methods).

    §9 实体能力（BG3 式：万物皆可破坏，属性默认冻结）：
    每个 GameObject 都有 hp/ac/resist —— 牛粪、信、酒杯天生能被炸/烧/砸，
    不搞"有/无 Damageable"二分，也不需要即兴授予。只有标了 indestructible
    的（墙、大地）才打不动。这些战斗属性默认【不进 get_scene】，玩家做出
    破坏意图时才解冻（见 mcp_server 的伤害结算），平时零 token 负担。
    """
    id: str
    name: str
    description: str
    kind: str = "scenery"
    named_tags: List[str] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)
    traits: List[str] = field(default_factory=list)
    takable: bool = False
    hidden: bool = False
    hidden_clue: Optional[str] = None
    hidden_flag: Optional[str] = None
    reveals_objects: List[str] = field(default_factory=list)
    # Route 8: per-object affordances, keyed by verb
    affordances: Dict[str, Affordance] = field(default_factory=dict)
    # §9：万物皆有 hp/ac/resist（默认冻结，不进 get_scene）。
    # 耐久度建议：fragile=1 / 默认=5 / sturdy=15。indestructible=True 时打不动（墙/大地）。
    hp: int = 5
    max_hp: int = 5
    ac: int = 5                                    # 死物易命中，默认低
    indestructible: bool = False                   # 墙/大门/大地标 True
    damage_types_resist: Dict[str, float] = field(default_factory=dict)  # 空=全 1.0
    on_destroyed: List[Dict[str, Any]] = field(default_factory=list)     # list[Step]，hp 归零触发
    buffs: List["Buff"] = field(default_factory=list)                    # 着火/中毒等持续效应
    # §11 装备/消耗品数据——拾取时由 InventoryItem.from_object 迁移到背包物
    equip_slot: str = ""            # 槽位 key（weapon/armor/...），空=不可装备
    damage_expr: str = ""           # 武器伤害表达式 "1d8"
    damage_type: str = "blunt"      # 武器伤害类型
    scaling: dict = field(default_factory=dict)      # {"str":1.0,"dex":0.5}
    defense: int = 0                # 护甲 AC 加成
    resist: dict = field(default_factory=dict)       # 护甲属性减伤 {"fire":0.5}
    attr_bonus: dict = field(default_factory=dict)   # 属性加成 {attr_key:+N}
    use_effect: dict = field(default_factory=dict)   # 消耗品效果 {"heal":10,"restore_sp":3}


# ── §11 RPG 数值骨架：RuleBook + 常量 ────────────────────────────

@dataclass
class RuleBook:
    """世界的数值规则书。属性集合 + 机制锚点指派。content 提供，引擎读取。

    attributes   — {属性key: 显示名}，如 {"str":"力量","int":"智力"}
    roles        — 机制锚点 → 属性key 的指派
    equip_slots  — 该世界的装备槽
    level_curve  — 升级曲线选择（引擎内置几条，选一条）
    """
    attributes: Dict[str, str] = field(default_factory=lambda: {"str": "力量", "dex": "敏捷", "con": "体质", "int": "智力"})
    roles: Dict[str, str] = field(default_factory=lambda: {"accuracy": "dex", "hp_growth": "con", "stamina_pool": "int"})
    equip_slots: Dict[str, str] = field(default_factory=lambda: {"weapon": "主手", "armor": "护甲", "accessory": "饰品", "boots": "鞋"})
    level_curve: str = "quadratic"
    attr_per_level: int = 2      # 每升一级给的可分配属性点数


def exp_to_reach(level: int) -> int:
    """升级所需经验: 50*(L-1)*L → L2=100, L3=300, L4=600, ..."""
    if level <= 1:
        return 0
    return 50 * (level - 1) * level


HP_PER_LEVEL = 5       # 每级 max_hp 基础成长
HP_PER_HPGROWTH = 2    # hp_growth 属性每点额外 +N max_hp 成长

CHAR_XP_BY_ARCHETYPE = {
    "brute_low": 30,
    "brute_mid": 60,
    "scout": 40,
    "caster_low": 50,
    "caster_mid": 80,
    "boss": 200,
}


# ── 路线九：Modifier / Skill / Buff 数学系统 ──────────────────────

MODIFIER_OPS = {"add", "mul", "set", "clamp", "advantage", "disadvantage", "reroll"}
MODIFIER_TARGETS = {"roll", "dc", "damage", "hp", "gold", "narrative_tag", "ac"}
MODIFIER_VISIBILITY = {"full", "result", "hidden"}
MODIFIER_OP_PRIORITY = ["clamp", "set", "mul", "add", "advantage", "disadvantage", "reroll"]


@dataclass
class Modifier:
    """对一次掷骰/伤害/数值/叙事提示的单次修正。Skill/Buff/Item/Scene 都生产它。

    target  — 修正什么：roll / dc / damage / hp / gold / narrative_tag
    selector — 何时生效，例 {"reason_includes":["撬锁"]} 或 {} 永远生效
    op      — add / mul / set / clamp / advantage / disadvantage / reroll
    value   — 数值或字符串（advantage/disadvantage 时可为空字符串）
    """
    id: str                          # 自动生成
    source_kind: str                 # skill / buff / item / scene / improvised
    source_id: str = ""              # 上溯到具体来源 id
    target: str = "roll"             # roll / dc / damage / hp / gold / narrative_tag
    selector: dict = field(default_factory=dict)  # {"reason_includes":[...]}
    op: str = "add"
    value: float = 0.0
    reason: str = ""                 # 给玩家看的来源说明
    visible: str = "result"          # full / result / hidden


# ── 路线九 Phase 3-5：Skill 技能树 ────────────────────────────────
# 三层职责（见 §6.1）：
#   Modifier — 原子修正（已有）
#   Skill    — 修正的语义包装：passive(常驻) / active(主动声明) / reactive(触发)
#   Step     — 复合动作的流程脚本，走 verb 白名单
# Skill 不重复实现命中/合算逻辑——passive 注入 Modifier 池，active/reactive
# 的 recipe 调现有工具（roll_check / apply_buff 等），数学始终落在 Modifier 那层。

# Step verb 白名单（Phase 4：不含战斗 verb；战斗 step 由 B4 单独扩张）
SKILL_STEP_VERBS = {
    "apply_buff",        # 挂一个已构造的 Buff（args: buff dict 或 improvised buff 字段）
    "spawn_improvised",  # 生成临时物品（args: improvised item 字段）
    "narrative_tag",     # 加一个叙事 condition 标签（args: {"tag": str}）
    "roll_check",        # 跑一次检定（args: {"reason","sides","dc","modifier"}）
    "emit_modifier",     # 向池中加一个 Modifier（args: Modifier 字段）
}

SKILL_TRIGGERS = {"before_roll", "on_take_damage", "on_scene_enter"}


@dataclass
class Step:
    """复合动作里的单步。verb 走 SKILL_STEP_VERBS 白名单。

    on_success/on_failure 只对会产生成败的 verb（roll_check）有意义——其余
    verb 视为恒成功，走 on_success 分支。
    """
    verb: str
    args: dict = field(default_factory=dict)
    on_success: List["Step"] = field(default_factory=list)
    on_failure: List["Step"] = field(default_factory=list)


@dataclass
class ActiveSkill:
    """主动技能：资源消耗 + 冷却 + 动作流程。"""
    cost: dict = field(default_factory=dict)          # {"stamina":3,"hp":0,"gold":0,"item":"id"}
    cooldown: int = 0
    remaining_cooldown: int = 0
    recipe: List[Step] = field(default_factory=list)


@dataclass
class ReactiveSkill:
    """被动响应：某事件触发时自动跑 recipe。"""
    trigger: str                                      # SKILL_TRIGGERS 之一
    condition: dict = field(default_factory=dict)     # selector，匹配 trigger 事件
    recipe: List[Step] = field(default_factory=list)


@dataclass
class Skill:
    """三种参与方式可同时存在（passive/active/reactive，不是单选 kind）。

    rank/xp 是成长循环：grant_xp 累积 xp，跨过 rank_thresholds 自动升 rank。
    passive_modifiers 在掌握期间常驻注入 Modifier 池（rank 可放大其效果，留待后续）。
    """
    id: str
    name: str
    desc: str = ""
    passive_modifiers: List[Modifier] = field(default_factory=list)
    active: Optional[ActiveSkill] = None
    reactive: Optional[ReactiveSkill] = None
    rank: int = 1
    xp: int = 0
    rank_thresholds: List[int] = field(default_factory=lambda: [3, 10, 25])
    obtained_from: str = ""           # background:detective / npc:Alma / improvised


# ── 路线九：战斗系统 (Encounter) ─────────────────────────────────

ENEMY_ARCHETYPES = {
    "brute_low": {
        "label": "低级打手",
        "hp_range": [5, 8], "ac": 10, "speed": 8,
        "damage_expr": "1d6", "damage_type": "blunt",
        "behavior_profile": "aggressive", "skills": [],
        "flavor": "莽撞但威胁有限的路边打手。",
    },
    "brute_mid": {
        "label": "中级打手",
        "hp_range": [10, 15], "ac": 12, "speed": 8,
        "damage_expr": "1d6+2", "damage_type": "slash",
        "behavior_profile": "aggressive", "skills": [],
        "flavor": "装备更好、出手更狠的雇工。",
    },
    "scout": {
        "label": "侦察型",
        "hp_range": [4, 7], "ac": 13, "speed": 12,
        "damage_expr": "1d6", "damage_type": "pierce",
        "behavior_profile": "cautious", "skills": [],
        "flavor": "身手敏捷、惯于游斗。",
    },
    "caster_low": {
        "label": "低级术者",
        "hp_range": [3, 6], "ac": 10, "speed": 10,
        "damage_expr": "1d4+2", "damage_type": "arcane",
        "behavior_profile": "opportunist", "skills": [],
        "flavor": "能驱使低级奥术，身躯孱弱。",
    },
    "boss": {
        "label": "首领",
        "hp_range": [18, 25], "ac": 14, "speed": 10,
        "damage_expr": "2d6", "damage_type": "slash",
        "behavior_profile": "aggressive", "skills": [],
        "flavor": "威胁突出的头目级存在。",
    },
}

COMBAT_BEHAVIOR_PROFILES = {"aggressive", "cautious", "opportunist", "support"}
COMBAT_DAMAGE_EXPRS_WHITELIST = {"1d4", "1d6", "1d8", "2d4", "1d4+1", "1d6+1", "1d8+1", "1d4+2", "1d6+2", "2d6", "2d4+1"}
COMBAT_SIDES = {"player", "enemy", "neutral"}


@dataclass
class EnemyTemplate:
    """预定义敌人——内容文件写入 ENEMIES dict，MCP 读取。"""
    id: str
    name: str
    archetype: str = ""
    hp: int = 8
    max_hp: int = 8
    ac: int = 10
    speed: int = 10
    damage_expr: str = "1d6"
    damage_type: str = "blunt"
    damage_types_resist: dict = field(default_factory=dict)
    behavior_profile: str = "aggressive"
    skills: list[str] = field(default_factory=list)
    loot: list[str] = field(default_factory=list)
    flavor: str = ""


@dataclass
class Combatant:
    """Encounter 中的作战单元——战斗期间的运行时对象。"""
    id: str
    name: str
    side: str                       # "player" / "enemy" / "neutral"
    hp: int
    max_hp: int
    ac: int
    speed: int
    damage_expr: str = "1d4"
    damage_type: str = "blunt"
    damage_types_resist: dict = field(default_factory=dict)
    behavior_profile: str = "aggressive"
    skills: list[str] = field(default_factory=list)
    buffs: List["Buff"] = field(default_factory=list)
    stamina: int = 0
    max_stamina: int = 0
    is_dead: bool = False
    archetype: str = ""             # 来源原型，用于击败后按 CHAR_XP_BY_ARCHETYPE 给经验
    # ── §14 战斗结构层（加法式：默认值=现有"无结构"行为，旧战斗不变）──
    rank: int = 0                   # 列阵位：0=最前排，越大越靠后
    reach: int = 99                 # 基础攻击触及的排数差（默认 99=无限，即现状"谁都能打谁"）
    windup: Optional[dict] = None   # 蓄力中的待结算动作 {turns_left,name,intent,target}；None=未蓄力
    poise: int = 0                  # 当前削韧累积
    max_poise: int = 0              # 破防阈值（0=无破防条，杂兵默认无；精英/首领才设）
    staggered: bool = False         # 是否破防（爆发窗口）


@dataclass
class CombatEvent:
    """战斗回合中产生的单条事件——Codex 的叙事素材。"""
    kind: str                       # attack / miss / hit / damage / kill / flee / buff_applied / skill_used / combat_end
    actor: str
    target: str = ""
    detail: dict = field(default_factory=dict)     # 例 {"damage":5, "damage_type":"slash", "attack_roll":17, "ac":12}
    roll_audit: dict | None = None                 # 引用 last_roll_audit


@dataclass
class Encounter:
    """战斗遭遇状态机。Session 层持有，不替换 Room。"""
    id: str
    combatants: dict[str, Combatant] = field(default_factory=dict)
    turn_order: list[str] = field(default_factory=list)
    round: int = 1
    active_idx: int = 0
    log: list[CombatEvent] = field(default_factory=list)
    rank_depth: int = 2             # §14：每方列阵档数（默认 2=前/后；可设 3=前/中/后）


# ── 路线九 §9：实体能力契约 ────────────────────────────────────────
# 实体不是一个类，是三种正交能力。对象按需"点亮"字段即获得对应能力。
# 引擎逻辑写成吃 bearer 的自由函数（见 mcp_server.py），不绑对象方法 —— 与
# data-oriented 风格一致。
#
# 两层用法，分工明确：
#   1. Protocol（下方）—— 给函数签名做静态类型标注（mypy/pyright），表达
#      "这个函数吃任何能被打的东西"。不用于运行期 isinstance。
#   2. is_*() helper —— 运行期按【值】判定能力。Protocol 的 runtime_checkable
#      只看属性名存在、不看值，会把 hp=None 的信也判为 Damageable，故不可靠。
#
# 注意 GameState 不是实体：hp 在 vitals 里，buffs 虽在但玩家通过【投影成
# Combatant】参战/受击。GameState 是快照，不是 bearer。


class Damageable(Protocol):
    """能被打/烧/炸、会'坏'的东西。Combatant、带 hp 的 GameObject。"""
    id: str
    hp: int
    max_hp: int
    damage_types_resist: Dict[str, float]
    on_destroyed: List[Dict[str, Any]]


class BuffBearer(Protocol):
    """能挂 buff/debuff、受持续效应影响的东西。Combatant、被点燃的 GameObject。"""
    id: str
    buffs: List["Buff"]


class Actor(Protocol):
    """有回合、能主动声明行动的东西。必然也满足 Damageable + BuffBearer。"""
    id: str
    speed: int
    behavior_profile: str


def is_damageable(obj: Any) -> bool:
    """运行期判定：能不能被伤害系统作为 target。

    BG3 式：万物皆可破坏，默认 True。只有标了 indestructible 的（墙/大地）
    或没有 hp 字段的才 False。不再用"hp 是否 None"做有/无能力的二分。
    """
    if getattr(obj, "indestructible", False):
        return False
    return getattr(obj, "hp", None) is not None


def is_buff_bearer(obj: Any) -> bool:
    """运行期判定：能不能挂 buff。有 buffs 列表即可。"""
    return isinstance(getattr(obj, "buffs", None), list)


def is_actor(obj: Any) -> bool:
    """运行期判定：有没有回合、能不能主动行动。"""
    return getattr(obj, "speed", None) is not None and bool(getattr(obj, "behavior_profile", ""))


# Container 第四能力（弹夹/书架/啤酒架：持有一组同类物品 + 容量）暂不实现。
# 当前 kind="container" + affordance 的 open/search 已够用；等"弹药剩 N 发、
# 开枪 -1"这类程序化数量玩法出现，再加 Container Protocol。见 §9.7。
