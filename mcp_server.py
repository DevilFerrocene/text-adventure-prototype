"""生产版 MCP 服务器 —— 完整游戏引擎包装。

包含：
  - 全 Affordance 系统（路线八）
  - 双层世界状态（Canon + Improvised，路线七）
  - WorldCanon 世界观锚句
  - 7 关 improvised 验证
  - yanan 单世界支持

工具：
  start_game(world)   启动游戏，重置状态
  get_scene()         当前房间详情（含可用 affordance）
  inspect_object(object_id)  检查物体，发现隐藏线索/揭示物体
  call_affordance(object_id, verb)  执行物品方法
  roll_check(reason, sides, modifier, dc)  骰子检定
  move(direction)     移动
  take_item(object_id)  拾取物品
  add_improvised(items)  即兴添加临时物品（7关验证）
  get_state()         完整游戏状态
  save_game(slot)     存档到文件
  load_game(slot)     从文件载入
  set_custom_attribute(scope, key, value, value_type, label, note)  添加/更新扩展属性
"""

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 路径修复：允许从任何目录启动 ──────────────────────────────────
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mcp.server.fastmcp import FastMCP

from core.types import (
    GameState, InventoryItem, ImprovisedItem, Affordance, Modifier,
    ActorProfile, VitalStats, WorldTime, QuestEntry,
    Combatant, Encounter, CombatEvent, EnemyTemplate,
    Clue, DialogueEntry, RoomSnapshot,
    Buff, BuffTick, GameObject,
    Skill, ActiveSkill, ReactiveSkill, Step,
    SKILL_STEP_VERBS, SKILL_TRIGGERS,
    is_damageable, is_buff_bearer, is_actor,
    BUFF_POLARITIES, BUFF_TICK_TIMINGS,
    IMPROVISED_BUFF_TARGETS, IMPROVISED_BUFF_MAX_PER_TURN,
    IMPROVISED_BUFF_MAX_ACTIVE, IMPROVISED_BUFF_MAX_VALUE, IMPROVISED_BUFF_MAX_DURATION,
    IMPROVISED_CATEGORIES, IMPROVISED_SIZES, IMPROVISED_MAX_TTL,
    MAX_IMPROVISED_IN_INVENTORY, MAX_IMPROVISED_PER_TURN, IMPROVISED_DEFAULT_TTL,
    ITEM_KIND_DEFS, ITEM_NAMED_TAG_DEFS, ITEM_MODIFIER_DEFS,
    MODIFIER_OPS, MODIFIER_TARGETS, MODIFIER_VISIBILITY, MODIFIER_OP_PRIORITY,
    ENEMY_ARCHETYPES, COMBAT_BEHAVIOR_PROFILES, COMBAT_DAMAGE_EXPRS_WHITELIST, COMBAT_SIDES,
)
from runtime.game_world import GameWorld
import content.yanan as yanan_module
import content.aincrad as aincrad_module


mcp = FastMCP("text-adventure")

SAVE_DIR = _HERE / "saves"
SAVE_DIR.mkdir(exist_ok=True)

WORLDS = {
    "yanan": yanan_module,
    "aincrad": aincrad_module,
}


# ── 全局状态 ──────────────────────────────────────────────────────

@dataclass
class Session:
    world_name: str = ""
    world: Optional[GameWorld] = None
    state: Optional[GameState] = None
    rolls_log: List[dict] = field(default_factory=list)
    modifiers: List[Modifier] = field(default_factory=list)
    last_roll_audit: Optional[dict] = None
    encounter: Optional[Encounter] = None

    @property
    def started(self) -> bool:
        return self.world is not None and self.state is not None

    @property
    def in_combat(self) -> bool:
        return self.encounter is not None


SESSION = Session()


# ── helpers ───────────────────────────────────────────────────────

def _require_started() -> Optional[dict]:
    if not SESSION.started:
        return {"ok": False, "error": "游戏尚未开始，请先调用 start_game()。"}
    return None


def _room_snapshot(world: GameWorld, state: GameState) -> dict:
    room = world.get_room(state.position)
    if not room:
        return {"error": f"未知房间 {state.position}"}

    objects_info = []
    priority_objects = []
    for oid in room.objects:
        obj = world.get_object(oid)
        if not obj or obj.hidden:
            continue
        available_affordances = world.get_callable_affordances(oid, state)
        semantics = _object_semantics(obj)
        if semantics["prompt_priority"] > 0:
            priority_objects.append({
                "id": oid,
                "name": obj.name,
                "kind": obj.kind,
                "named_tags": obj.named_tags,
                "modifiers": obj.modifiers,
                "prompt_priority": semantics["prompt_priority"],
                "prompt_hints": semantics["prompt_hints"],
            })
        objects_info.append({
            "id": oid,
            "name": obj.name,
            "desc": obj.description,
            "kind": obj.kind,
            "named_tags": obj.named_tags,
            "modifiers": obj.modifiers,
            "kind_desc": semantics["kind_desc"],
            "named_tag_descs": semantics["named_tag_descs"],
            "modifier_descs": semantics["modifier_descs"],
            "traits": obj.traits,
            # base_methods/semantic_methods 是【语义联想词】，不是可调动作——勿直接传给 call_affordance
            "base_methods": semantics["base_methods"],
            "semantic_methods": semantics["base_methods"],
            "prompt_hints": semantics["prompt_hints"],
            "prompt_priority": semantics["prompt_priority"],
            "takable": obj.takable,
            # callable_verbs：此刻【真正能调】的 verb（已过 requires_item/flag 校验）。
            # GM 用 call_affordance 时只从这里取 verb，不要从 base_methods 猜。
            # inspect 永远可用；takable 物可 take。
            "callable_verbs": (
                ["inspect"]
                + (["take"] if obj.takable else [])
                + [verb for verb, _ in available_affordances]
            ),
            "affordances": [
                {
                    "verb": verb,
                    "desc": aff.desc,
                    "requires_item": aff.requires_item,
                }
                for verb, aff in available_affordances
            ],
        })

    # exits: show locked status
    exits_info = {}
    for direction, target in room.exits.items():
        if direction in room.locked_exits:
            exits_info[direction] = {"target": target, "locked": True, "requires": room.locked_exits[direction]}
        else:
            exits_info[direction] = {"target": target, "locked": False}

    return {
        "room_id": state.position,
        "name": room.name,
        "description": room.base_description,
        "area": room.area,
        "zone": room.zone,
        "coords": list(room.coords),
        "tags": room.tags,
        "exits": exits_info,
        "objects": objects_info,
        "priority_objects": sorted(
            priority_objects,
            key=lambda item: item["prompt_priority"],
            reverse=True,
        ),
    }


def _merge_methods(*method_lists) -> list:
    methods = []
    for method_list in method_lists:
        for method in method_list:
            if method not in methods:
                methods.append(method)
    return methods


def _object_semantics(obj) -> dict:
    kind_def = ITEM_KIND_DEFS.get(obj.kind, ITEM_KIND_DEFS["item"])
    named_defs = [
        ITEM_NAMED_TAG_DEFS[tag]
        for tag in obj.named_tags
        if tag in ITEM_NAMED_TAG_DEFS
    ]
    modifier_defs = [
        ITEM_MODIFIER_DEFS[modifier]
        for modifier in obj.modifiers
        if modifier in ITEM_MODIFIER_DEFS
    ]
    return {
        "kind_desc": kind_def.get("desc", ""),
        "named_tag_descs": [named_def.get("desc", "") for named_def in named_defs],
        "modifier_descs": [modifier_def.get("desc", "") for modifier_def in modifier_defs],
        "base_methods": _merge_methods(
            kind_def.get("base_methods", ["inspect"]),
            *(named_def.get("base_methods", []) for named_def in named_defs),
            *(modifier_def.get("base_methods", []) for modifier_def in modifier_defs),
        ),
        "prompt_hints": [
            definition["prompt_hint"]
            for definition in [*named_defs, *modifier_defs]
            if definition.get("prompt_hint")
        ],
        "prompt_priority": max(
            [named_def.get("prompt_priority", 0) for named_def in named_defs] or [0]
        ),
    }


def _inventory_snapshot(state: GameState) -> list:
    items = []
    for item in state.inventory:
        semantics = _object_semantics(item)
        items.append({
            "id": item.id,
            "name": item.name,
            "desc": item.desc,
            "tags": item.tags,
            "ttl": item.ttl,
            "kind": item.kind,
            "named_tags": item.named_tags,
            "modifiers": item.modifiers,
            "base_methods": semantics["base_methods"],
            "prompt_hints": semantics["prompt_hints"],
            "prompt_priority": semantics["prompt_priority"],
        })
    return items


def _profile_snapshot(profile: ActorProfile) -> dict:
    return {
        "name": profile.name,
        "role": profile.role,
        "background": profile.background,
    }


def _vitals_snapshot(vitals: VitalStats) -> dict:
    return {
        "hp": vitals.hp,
        "max_hp": vitals.max_hp,
        "gold": vitals.gold,
        "reputation": vitals.reputation,
        "ac": vitals.ac,
        "speed": vitals.speed,
        "stamina": vitals.stamina,
        "max_stamina": vitals.max_stamina,
        "damage_types_resist": vitals.damage_types_resist,
    }


def _world_time_snapshot(world_time: WorldTime) -> dict:
    return {
        "calendar": world_time.calendar,
        "day": world_time.day,
        "phase": world_time.phase,
        "minute": world_time.minute,
        "weather": world_time.weather,
    }


def _quest_log_snapshot(quest_log: List[QuestEntry]) -> list:
    return [
        {
            "id": quest.id,
            "title": quest.title,
            "stage": quest.stage,
            "summary": quest.summary,
            "deadline": quest.deadline,
            "known_facts": quest.known_facts,
            "unresolved": quest.unresolved,
        }
        for quest in quest_log
    ]


def _clues_snapshot(clues: List[Clue]) -> list:
    return [
        {"text": c.text, "tags": c.tags, "turn": c.turn, "cold": c.cold}
        for c in clues
    ]


def _dialogue_log_snapshot(dialogue_log: List[DialogueEntry]) -> list:
    return [
        {"turn": d.turn, "npc_id": d.npc_id, "summary": d.summary,
         "tags": d.tags, "cold": d.cold}
        for d in dialogue_log
    ]


def _load_buffs(raw_buffs: list) -> List[Buff]:
    buffs = []
    for bd in raw_buffs:
        ticks = {}
        for t, td in bd.get("ticks", {}).items():
            mods = [
                Modifier(
                    id=md.get("id", "auto"), source_kind=md.get("source_kind", "buff"),
                    source_id=md.get("source_id", ""), target=md.get("target", "roll"),
                    selector=md.get("selector", {}), op=md.get("op", "add"),
                    value=md.get("value", 0.0), reason=md.get("reason", ""),
                    visible=md.get("visible", "result"),
                )
                for md in td.get("emit_modifiers", [])
            ]
            ticks[t] = BuffTick(emit_modifiers=mods)
        buffs.append(Buff(
            id=bd["id"], name=bd["name"], desc=bd.get("desc", ""),
            polarity=bd.get("polarity", "neutral"),
            source_kind=bd.get("source_kind", "improvised"),
            source_id=bd.get("source_id", ""),
            tags=bd.get("tags", []),
            stacks=bd.get("stacks", 1),
            max_stacks=bd.get("max_stacks", 1),
            ticks=ticks,
            expire_on=bd.get("expire_on", []),
            visible=bd.get("visible", "result"),
        ))
    return buffs


def _serialize_modifier(m: Modifier) -> dict:
    return {
        "id": m.id, "source_kind": m.source_kind, "source_id": m.source_id,
        "target": m.target, "selector": m.selector, "op": m.op,
        "value": m.value, "reason": m.reason, "visible": m.visible,
    }


def _serialize_step(s: Step) -> dict:
    return {
        "verb": s.verb, "args": s.args,
        "on_success": [_serialize_step(c) for c in s.on_success],
        "on_failure": [_serialize_step(c) for c in s.on_failure],
    }


def _serialize_skill(s: Skill) -> dict:
    """完整序列化技能（含成长状态 xp/rank 和 active/reactive recipe）。"""
    data = {
        "id": s.id, "name": s.name, "desc": s.desc,
        "passive_modifiers": [_serialize_modifier(m) for m in s.passive_modifiers],
        "rank": s.rank, "xp": s.xp, "rank_thresholds": s.rank_thresholds,
        "obtained_from": s.obtained_from,
        "active": None, "reactive": None,
    }
    if s.active:
        data["active"] = {
            "cost": s.active.cost, "cooldown": s.active.cooldown,
            "remaining_cooldown": s.active.remaining_cooldown,
            "recipe": [_serialize_step(st) for st in s.active.recipe],
        }
    if s.reactive:
        data["reactive"] = {
            "trigger": s.reactive.trigger, "condition": s.reactive.condition,
            "recipe": [_serialize_step(st) for st in s.reactive.recipe],
        }
    return data


def _load_modifier(md: dict) -> Modifier:
    return Modifier(
        id=md.get("id", "auto"), source_kind=md.get("source_kind", "skill"),
        source_id=md.get("source_id", ""), target=md.get("target", "roll"),
        selector=md.get("selector", {}), op=md.get("op", "add"),
        value=md.get("value", 0.0), reason=md.get("reason", ""),
        visible=md.get("visible", "result"),
    )


def _load_step(sd: dict) -> Step:
    return Step(
        verb=sd.get("verb", ""), args=sd.get("args", {}),
        on_success=[_load_step(c) for c in sd.get("on_success", [])],
        on_failure=[_load_step(c) for c in sd.get("on_failure", [])],
    )


def _load_skills(raw_skills: list) -> List[Skill]:
    skills = []
    for sd in raw_skills:
        active = None
        if sd.get("active"):
            a = sd["active"]
            active = ActiveSkill(
                cost=a.get("cost", {}), cooldown=a.get("cooldown", 0),
                remaining_cooldown=a.get("remaining_cooldown", 0),
                recipe=[_load_step(st) for st in a.get("recipe", [])],
            )
        reactive = None
        if sd.get("reactive"):
            r = sd["reactive"]
            reactive = ReactiveSkill(
                trigger=r.get("trigger", ""), condition=r.get("condition", {}),
                recipe=[_load_step(st) for st in r.get("recipe", [])],
            )
        skills.append(Skill(
            id=sd["id"], name=sd.get("name", sd["id"]), desc=sd.get("desc", ""),
            passive_modifiers=[_load_modifier(m) for m in sd.get("passive_modifiers", [])],
            active=active, reactive=reactive,
            rank=sd.get("rank", 1), xp=sd.get("xp", 0),
            rank_thresholds=sd.get("rank_thresholds", [3, 10, 25]),
            obtained_from=sd.get("obtained_from", ""),
        ))
    return skills


def _buffs_snapshot(state: GameState) -> list:
    return [
        {
            "id": b.id, "name": b.name, "desc": b.desc,
            "polarity": b.polarity, "source_kind": b.source_kind,
            "tags": b.tags, "stacks": b.stacks,
            "expire_on": b.expire_on, "visible": b.visible,
        }
        for b in state.buffs
    ]


# ── 前台 HUD：MCP 出权威字符串，skill 管排版 ──────────────────────
# phase/weather 是英文枚举，HUD 给玩家看中文+emoji。未知值回退原文。
_PHASE_LABELS = {
    "dawn": "🌅 黎明", "morning": "🌤️ 上午", "noon": "☀️ 正午",
    "afternoon": "🌇 午后", "dusk": "🌆 黄昏", "evening": "🌃 入夜",
    "night": "🌙 夜晚", "deep_night": "🌑 深夜", "midnight": "🕛 子夜",
}
_WEATHER_LABELS = {
    "clear": "晴", "cloudy": "多云", "overcast": "阴", "fog": "雾",
    "rain": "🌧️ 雨", "heavy_rain": "⛈️ 暴雨", "drizzle": "毛毛雨",
    "snow": "❄️ 雪", "storm": "🌪️ 风暴", "wind": "💨 大风",
}


def _fmt_clock(minute: int) -> str:
    """把累计分钟数转成 HH:MM 时钟（以 00:00 为基准）。"""
    minute = max(0, int(minute)) % (24 * 60)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _build_hud(state: GameState, world: GameWorld) -> str:
    """探索态权威状态条。数据全部来自 state，GM 直接贴、不脑补。"""
    v = state.vitals
    wt = state.world_time
    room = world.get_room(state.position)
    room_name = room.name if room else state.position

    phase = _PHASE_LABELS.get(wt.phase, wt.phase)
    weather = _WEATHER_LABELS.get(wt.weather, wt.weather)

    parts = [f"❤️ {v.hp}/{v.max_hp}"]
    if v.max_stamina > 0:
        parts.append(f"⚡ {v.stamina}/{v.max_stamina}")
    parts.append(f"💰 {v.gold}")
    parts.append(f"{phase}·{weather} {_fmt_clock(wt.minute)}")
    parts.append(f"📍 {room_name}")
    line = "  ".join(parts)

    # 当前任务阶段（取第一条进行中的）
    if state.quest_log:
        q = state.quest_log[0]
        line += f"\n🎯 {q.title} · {q.stage}"

    # 活跃 buff（只显示有名字的，紧凑）
    if state.buffs:
        names = "、".join(b.name for b in state.buffs)
        line += f"\n✨ {names}"
    return line


def _build_combat_hud(enc) -> str:
    """战斗态权威状态条：回合数、行动序、各 combatant 血条、当前行动者。"""
    active = enc.turn_order[enc.active_idx] if enc.turn_order and enc.active_idx < len(enc.turn_order) else "?"
    lines = [f"⚔️ 第 {enc.round} 回合"]
    for cid in enc.turn_order:
        c = enc.combatants.get(cid)
        if not c:
            continue
        marker = "▶" if cid == active else " "
        icon = "💀" if c.is_dead else ("🛡️" if c.side == "player" else "👹")
        bar = "已倒下" if c.is_dead else f"{c.hp}/{c.max_hp}"
        lines.append(f"{marker} {icon} {c.name} {bar}")
    return "\n".join(lines)


def _state_context(state: GameState) -> dict:
    return {
        "profile": _profile_snapshot(state.profile),
        "vitals": _vitals_snapshot(state.vitals),
        "conditions": state.conditions,
        "relationships": state.relationships,
        "world_time": _world_time_snapshot(state.world_time),
        "quest_log": _quest_log_snapshot(state.quest_log),
        "skills": [_skill_snapshot(s) for s in state.skills],
        "custom": {
            "player_attrs": state.player_attrs,
            "world_attrs": state.world_attrs,
        },
    }


def _parse_custom_value(value: str, value_type: str) -> Tuple[Any, Optional[str]]:
    value_type = value_type.strip().lower()
    if value_type == "text":
        return value, None
    if value_type == "int":
        try:
            return int(value), None
        except ValueError:
            return None, f"value={value!r} 不能解析为 int"
    if value_type == "float":
        try:
            return float(value), None
        except ValueError:
            return None, f"value={value!r} 不能解析为 float"
    if value_type == "bool":
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "是", "真"}:
            return True, None
        if lowered in {"false", "no", "0", "否", "假"}:
            return False, None
        return None, f"value={value!r} 不能解析为 bool"
    if value_type == "json":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            return None, f"value 不是合法 JSON: {exc.msg}"
        if not isinstance(parsed, (str, int, float, bool, list, dict)) and parsed is not None:
            return None, "json 值必须是字符串、数字、布尔、列表、对象或 null"
        return parsed, None
    return None, "value_type 必须是 text / int / float / bool / json"


def _clean_custom_attributes(raw_attrs: dict) -> dict:
    cleaned = {}
    if not isinstance(raw_attrs, dict):
        return cleaned
    for key, entry in raw_attrs.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        cleaned[key] = {
            "label": str(entry.get("label", key)),
            "value": entry.get("value"),
            "value_type": str(entry.get("value_type", "text")),
            "note": str(entry.get("note", "")),
        }
    return cleaned


def _validate_improvised(raw_items: list, state: GameState) -> Tuple[List[ImprovisedItem], List[str]]:
    """7-gate validation. Returns (accepted, rejection_reasons)."""
    existing_imp = sum(1 for i in state.inventory if i.id.startswith("imp_"))
    slots = MAX_IMPROVISED_IN_INVENTORY - existing_imp
    if slots <= 0:
        return [], ["即兴物品栏已满（上限4个）"]

    accepted = []
    reasons = []
    seen_ids = set()

    for raw in raw_items[:MAX_IMPROVISED_PER_TURN]:
        item_id = raw.get("id", "")
        name = raw.get("name", "").strip()
        category = raw.get("category", "")
        size = raw.get("size", "small")
        ttl_raw = raw.get("ttl", IMPROVISED_DEFAULT_TTL)
        desc = raw.get("desc", "").strip()
        tags = raw.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        if not item_id.startswith("imp_"):
            reasons.append(f"{item_id}: id 必须以 imp_ 开头")
            continue
        if not name:
            reasons.append(f"{item_id}: name 不能为空")
            continue
        if item_id in seen_ids or state.has_item(item_id):
            reasons.append(f"{item_id}: 重复或已在背包")
            continue
        if category not in IMPROVISED_CATEGORIES:
            reasons.append(f"{item_id}: 未知 category={category}，允许: {list(IMPROVISED_CATEGORIES.keys())}")
            continue
        if category == "trace":
            reasons.append(f"{item_id}: trace 类不入背包")
            continue
        if size not in IMPROVISED_SIZES:
            size = "small"
        try:
            ttl = max(1, min(int(ttl_raw), IMPROVISED_MAX_TTL))
        except (TypeError, ValueError):
            ttl = IMPROVISED_DEFAULT_TTL

        seen_ids.add(item_id)
        accepted.append(ImprovisedItem(
            id=item_id, name=name, desc=desc,
            category=category, size=size, ttl=ttl,
            tags=[t for t in tags if isinstance(t, str)],
        ))
        if len(accepted) >= slots:
            break

    return accepted, reasons


def _apply_effect(effect: dict, state: GameState, world: GameWorld) -> dict:
    """Apply an affordance effect dict, return summary of changes."""
    applied: dict = {"flags_set": {}, "clues_added": [], "items_removed": [], "revealed": [],
                     "skills_learned": []}
    room = world.get_room(state.position)

    if "unlock_exit" in effect and room:
        d = effect["unlock_exit"]
        if d in room.locked_exits:
            del room.locked_exits[d]
            applied["flags_set"][f"exit_{d}_unlocked"] = True

    applied["flags_set"].update(effect.get("flags", {}))
    applied["clues_added"].extend(effect.get("clues", []))

    applied["revealed"].extend(_reveal_objects(effect.get("reveals_objects", []), room, world))

    # learn_skills：从世界 SKILLS 注册表把技能真正装进 state.skills（不只是置 flag）。
    # 让 affordance（NPC 教学/技能书宝箱）能真正授予技能，与 learn_skill 工具同效。
    for sid in effect.get("learn_skills", []):
        if _get_skill(state, sid):
            continue  # 已掌握，跳过
        template = world.get_skill(sid)
        if template:
            state.skills.append(_clone_skill(template))
            applied["skills_learned"].append(sid)

    for flag, val in applied["flags_set"].items():
        state.flags[flag] = val
    for clue in applied["clues_added"]:
        state.add_clue(clue)

    return applied


# ── MCP Tools ─────────────────────────────────────────────────────

@mcp.tool()
def start_game(world: str = "yanan") -> dict:
    """启动一局新游戏。

    Args:
        world: 世界名称。当前仅支持 yanan（默认）
    """
    global SESSION

    if world not in WORLDS:
        return {"ok": False, "error": f"未知世界 {world!r}，可用: {list(WORLDS.keys())}"}

    module = WORLDS[world]
    new_world = GameWorld(content_module=module)
    new_state = (
        new_world.initial_state.__class__(
            position=new_world.initial_state.position,
            inventory=list(new_world.initial_state.inventory),
            flags=dict(new_world.initial_state.flags),
            alertness=new_world.initial_state.alertness,
            clues=list(new_world.initial_state.clues),
            turn=0,
            profile=ActorProfile(
                name=new_world.initial_state.profile.name,
                role=new_world.initial_state.profile.role,
                background=new_world.initial_state.profile.background,
            ),
            vitals=VitalStats(
                hp=new_world.initial_state.vitals.hp,
                max_hp=new_world.initial_state.vitals.max_hp,
                gold=new_world.initial_state.vitals.gold,
                reputation=new_world.initial_state.vitals.reputation,
                ac=getattr(new_world.initial_state.vitals, 'ac', 10),
                speed=getattr(new_world.initial_state.vitals, 'speed', 10),
                stamina=getattr(new_world.initial_state.vitals, 'stamina', 0),
                max_stamina=getattr(new_world.initial_state.vitals, 'max_stamina', 0),
                damage_types_resist=getattr(new_world.initial_state.vitals, 'damage_types_resist', {}),
            ),
            conditions=list(new_world.initial_state.conditions),
            relationships=dict(new_world.initial_state.relationships),
            world_time=WorldTime(
                calendar=new_world.initial_state.world_time.calendar,
                day=new_world.initial_state.world_time.day,
                phase=new_world.initial_state.world_time.phase,
                minute=new_world.initial_state.world_time.minute,
                weather=new_world.initial_state.world_time.weather,
            ),
            quest_log=[
                QuestEntry(
                    id=q.id,
                    title=q.title,
                    stage=q.stage,
                    summary=q.summary,
                    deadline=q.deadline,
                    known_facts=list(q.known_facts),
                    unresolved=list(q.unresolved),
                )
                for q in new_world.initial_state.quest_log
            ],
            player_attrs=_clean_custom_attributes(new_world.initial_state.player_attrs),
            world_attrs=_clean_custom_attributes(new_world.initial_state.world_attrs),
            # 初始技能（出身自带）：深拷贝，使成长状态独立于 content 模板
            skills=[_clone_skill(s) for s in new_world.initial_state.skills],
        )
        if new_world.initial_state
        else GameState(position=list(new_world.rooms.keys())[0])
    )

    SESSION = Session(world_name=world, world=new_world, state=new_state)

    scene = _room_snapshot(new_world, new_state)
    canon_prompt = new_world.get_world_canon_prompt()

    return {
        "ok": True,
        "world": world,
        "scene": scene,
        "inventory": _inventory_snapshot(new_state),
        "world_canon": canon_prompt,
        "turn": new_state.turn,
        "state_context": _state_context(new_state),
        "hud": _build_hud(new_state, new_world),
        "gm_hint": (
            "你是 GM。工具结果仅你可见，不会显示给玩家。"
            "每回合：按需调用工具（get_scene / inspect_object / call_affordance / roll_check / move / take_item），"
            "然后写一段沉浸式叙事给玩家。世界观约束见 world_canon 字段。"
        ),
    }


@mcp.tool()
def get_scene() -> dict:
    """查看当前场景：房间描述、出口、物体及其可用方法。"""
    if err := _require_started():
        return err
    scene = _room_snapshot(SESSION.world, SESSION.state)
    enemy_profiles = _enemy_profiles_for_scene(SESSION.state)
    result = {
        "ok": True,
        "scene": scene,
        "inventory": _inventory_snapshot(SESSION.state),
        "clues": _clues_snapshot(SESSION.state.clues),
        "flags": SESSION.state.flags,
        "turn": SESSION.state.turn,
        "state_context": _state_context(SESSION.state),
        "hud": _build_hud(SESSION.state, SESSION.world),
    }
    if enemy_profiles:
        result["enemy_profiles"] = enemy_profiles
        result["can_initiate_combat"] = True
    return result


def _reveal_objects(object_ids: list, room, world: GameWorld) -> list:
    """Reveal hidden objects in the current room and return revealed IDs."""
    revealed = []
    if not room:
        return revealed

    for object_id in object_ids:
        obj = world.get_object(object_id)
        if not obj:
            continue
        obj.hidden = False
        if object_id not in room.objects:
            room.objects.append(object_id)
        if object_id not in revealed:
            revealed.append(object_id)

    return revealed


def _advance_turn(state: GameState) -> list:
    """叙事回合推进（探索时）。战斗回合走 declare_intent 内的轮转，不调本函数。"""
    state.turn += 1
    state.world_time.minute += 5
    # ── §9/E2：玩家 buff tick（hp/过期效应 + roll buff 刷进全局池）──
    _tick_bearer_buffs(state, state)
    _refresh_persistent_buff_mods(state)
    # ── §6 Phase 4：active 技能冷却递减 ──
    for skill in state.skills:
        if skill.active and skill.active.remaining_cooldown > 0:
            skill.active.remaining_cooldown -= 1
    state.improvised_buff_count_this_turn = 0  # reset per-turn gate
    return state.tick_ttl()


# ── Phase 2：Buff 引擎 ────────────────────────────────────────────────


def _emit_buff_modifiers(bearer, timing: str) -> List[Modifier]:
    """遍历 bearer 的 active buff，返回在 timing 触发的 emit_modifiers 列表。

    bearer 是任何 BuffBearer（GameState / Combatant / 带 buffs 的 GameObject）。
    不直接注入全局 pool——调用方决定生命周期。
    """
    result: List[Modifier] = []
    for buff in getattr(bearer, "buffs", []):
        tick = buff.ticks.get(timing)
        if not tick:
            continue
        for mod in tick.emit_modifiers:
            cloned = Modifier(
                id=f"buff_{buff.id}_{mod.id}_{timing}",
                source_kind="buff",
                source_id=buff.id,
                target=mod.target,
                selector=mod.selector,
                op=mod.op,
                value=mod.value,
                reason=f"{buff.name}: {mod.reason or buff.desc}",
                visible=mod.visible,
            )
            result.append(cloned)
    return result


def _refresh_persistent_buff_mods(state: GameState):
    """清除所有旧 buff modifier，重新发射玩家 turn_start/turn_end 的 persistent modifier。

    只处理玩家（state.buffs）——这些 modifier 进全局 roll 池影响玩家掷骰。
    敌人/物体的 buff 不进全局池（见 _tick_bearer_buffs），避免污染玩家检定。
    """
    _remove_modifiers_for_source("buff", "*")
    for timing in ("turn_start", "turn_end"):
        for mod in _emit_buff_modifiers(state, timing):
            SESSION.modifiers.append(mod)


def _tick_buff_expiry(bearer):
    """递减 bearer 所有 buff 的 expire_on 中的 turns/turns_remaining 计数器。"""
    for buff in getattr(bearer, "buffs", []):
        for cond in buff.expire_on:
            for key in ("turns", "turns_remaining"):
                if key in cond and isinstance(cond[key], (int, float)):
                    cond[key] -= 1


def _purge_expired_buffs(bearer, state: GameState):
    """移除 bearer 已到期的 buff，并清理其关联的全局 modifier。

    flag 条件读全局 state.flags（flag 是世界级的），但删除作用于 bearer.buffs。
    """
    buffs = getattr(bearer, "buffs", None)
    if buffs is None:
        return
    expired_ids = [b.id for b in buffs if _is_buff_expired(b, state)]
    if not expired_ids:
        return
    bearer.buffs = [b for b in buffs if b.id not in expired_ids]
    for bid in expired_ids:
        _remove_modifiers_for_source("buff", bid)


def _is_buff_expired(buff: Buff, state: GameState) -> bool:
    """检查 buff 是否满足任一 expire_on 条件（OR 逻辑）。"""
    if not buff.expire_on:
        return False
    for cond in buff.expire_on:
        # Flag-based: {"flag": "dried_off"} → expired when flag is True
        if "flag" in cond and state.flags.get(cond["flag"]):
            return True
        # Turn-based: {"turns": N} → expired when turns <= 0
        if "turns" in cond and cond["turns"] <= 0:
            return True
        if "turns_remaining" in cond and cond["turns_remaining"] <= 0:
            return True
    return False


def _apply_direct_modifiers(bearer, mods: List[Modifier], state: GameState):
    """将非 roll/dc 的 modifier 直接应用到 bearer（hp）或 state（gold/narrative_tag）。

    hp 写回 bearer 自身：玩家走 state.vitals.hp，Combatant/GameObject 走 .hp。
    gold/narrative_tag 是世界/玩家级，始终落在 state。
    """
    for m in mods:
        if m.target == "hp":
            _apply_hp_delta(bearer, m)
        elif m.target == "gold":
            if m.op == "add":
                state.vitals.gold += int(m.value)
            elif m.op == "set":
                state.vitals.gold = int(m.value)
        elif m.target == "narrative_tag":
            if m.op == "add" and isinstance(m.value, str):
                tag = m.value
                if tag not in state.conditions:
                    state.conditions.append(tag)


def _apply_hp_delta(bearer, m: Modifier):
    """把一个 hp modifier 应用到 bearer 自身的 hp 字段。"""
    # 玩家：hp 在 vitals 上；Combatant/GameObject：hp 是顶层字段
    vitals = getattr(bearer, "vitals", None)
    if vitals is not None:
        cur, mx = vitals.hp, vitals.max_hp
        new = cur + int(m.value) if m.op == "add" else (int(m.value) if m.op == "set" else cur)
        vitals.hp = max(0, min(mx, new))
    elif getattr(bearer, "hp", None) is not None:
        cur, mx = bearer.hp, bearer.max_hp
        new = cur + int(m.value) if m.op == "add" else (int(m.value) if m.op == "set" else cur)
        bearer.hp = max(0, min(mx, new))


# ── §9/E3：统一伤害入口 ────────────────────────────────────────────
# deal_damage 探索/战斗共用。结算写成吃 Damageable bearer 的自由函数，
# 不绑对象方法（与 data-oriented 风格一致）。bearer = Combatant 或带 hp 的
# GameObject——两者 hp/max_hp/damage_types_resist 字段同形，故同一函数通吃。

def _resolve_damage(bearer, raw_dmg: int, dmg_type: str,
                    match_context: dict | None = None) -> dict:
    """对一个 Damageable bearer 结算一次伤害。

    流程：raw → damage modifier(add/mul) → 抗性(damage_types_resist) → 扣 hp。
    最低造成 1 点（命中即有效）。返回结算明细，不负责善后（on_destroyed
    由调用方按 bearer 类型分派）。

    match_context 给 damage modifier 的 selector 用（如 reason_includes）。
    """
    match_context = match_context or {}

    # ── damage 类 modifier ──
    # 来源三路：① 全局池（武器增伤、易伤）② 玩家 buff 的 on_check damage 发射
    # （如剑技"蓄力斩"+4）③ 技能 passive 的 damage 修正。后两路靠各自 selector
    # 过滤——只在 reason 匹配（如"攻击/斩"）时生效，敌人/环境伤害不会误吃玩家增伤。
    dmg_mods = list(_collect_for_target("damage", match_context))
    if SESSION.started:
        for m in _emit_buff_modifiers(SESSION.state, "on_check") + _emit_skill_passive_modifiers(SESSION.state):
            if m.target == "damage" and _match_selector(m.selector, match_context):
                dmg_mods.append(m)

    dmg_total = raw_dmg
    for m in dmg_mods:
        if m.op == "add":
            dmg_total += int(m.value)
        elif m.op == "mul":
            dmg_total = int(dmg_total * m.value)
    dmg_total = max(1, dmg_total)

    # ── 抗性：resist[type] 缺省 1.0（无抗性）；0.5=半伤，2.0=易伤 ──
    resist = bearer.damage_types_resist.get(dmg_type, 1.0)
    final_dmg = max(1, int(dmg_total * resist))

    hp_before = bearer.hp
    bearer.hp = max(0, bearer.hp - final_dmg)
    destroyed = bearer.hp <= 0

    return {
        "target": bearer.id,
        "damage": final_dmg,
        "damage_type": dmg_type,
        "resist": resist,
        "hp_before": hp_before,
        "hp_after": bearer.hp,
        "max_hp": bearer.max_hp,
        "destroyed": destroyed,
    }


def _run_on_destroyed(obj: "GameObject", state: GameState, world: GameWorld) -> dict:
    """场景物体 hp 归零的善后：跑 on_destroyed step 列表 + 从房间移除 + 留痕。

    on_destroyed 复用 affordance 的 effect 语法（flags/clues/reveals_objects/
    unlock_exit），故 content 作者用同一套 DSL。战斗 Combatant 不走这里
    （它们只标 is_dead）。
    """
    outcome: dict = {"destroyed": obj.id, "effects": {}, "revealed": []}

    # on_destroyed 是 list[Step]；每个 step 是一个 effect dict
    for step in obj.on_destroyed:
        if isinstance(step, dict):
            applied = _apply_effect(step, state, world)
            # 合并各 step 的产出
            outcome["effects"].setdefault("flags_set", {}).update(applied.get("flags_set", {}))
            outcome["effects"].setdefault("clues_added", []).extend(applied.get("clues_added", []))
            outcome["revealed"].extend(applied.get("revealed", []))

    # 从当前房间移除被毁物（若在场景中）
    room = world.get_room(state.position)
    if room and obj.id in room.objects:
        room.objects = [o for o in room.objects if o != obj.id]
        outcome["removed_from_room"] = state.position

    # 从背包移除被毁物（若在背包中）——deal_damage 也接受背包物为目标。
    # reveals_objects 揭示进当前房间：背包物在手中被砸碎，内容物散落脚下，语义自洽。
    if state.has_item(obj.id):
        state.remove_item(obj.id)
        outcome["removed_from_inventory"] = obj.id

    # 留一条痕迹线索，便于回看
    trace = f"{obj.name}已被摧毁"
    if not state.has_clue(trace):
        state.add_clue(trace, tags=["destruction"])
        outcome["trace_clue"] = trace

    return outcome


# ── §6 Phase 3-5：Skill 技能树 ────────────────────────────────────

def _get_skill(state: GameState, skill_id: str) -> Optional[Skill]:
    for s in state.skills:
        if s.id == skill_id:
            return s
    return None


def _clone_modifier(m: Modifier) -> Modifier:
    return Modifier(
        id=m.id, source_kind=m.source_kind, source_id=m.source_id,
        target=m.target, selector=dict(m.selector), op=m.op,
        value=m.value, reason=m.reason, visible=m.visible,
    )


def _clone_step(s: Step) -> Step:
    return Step(
        verb=s.verb, args=dict(s.args),
        on_success=[_clone_step(c) for c in s.on_success],
        on_failure=[_clone_step(c) for c in s.on_failure],
    )


def _clone_skill(t: Skill) -> Skill:
    """深拷贝技能模板，使玩家的成长状态（xp/rank/cooldown）独立于 content 模板。"""
    active = None
    if t.active:
        active = ActiveSkill(
            cost=dict(t.active.cost), cooldown=t.active.cooldown,
            remaining_cooldown=t.active.remaining_cooldown,
            recipe=[_clone_step(s) for s in t.active.recipe],
        )
    reactive = None
    if t.reactive:
        reactive = ReactiveSkill(
            trigger=t.reactive.trigger, condition=dict(t.reactive.condition),
            recipe=[_clone_step(s) for s in t.reactive.recipe],
        )
    return Skill(
        id=t.id, name=t.name, desc=t.desc,
        passive_modifiers=[_clone_modifier(m) for m in t.passive_modifiers],
        active=active, reactive=reactive,
        rank=t.rank, xp=t.xp, rank_thresholds=list(t.rank_thresholds),
        obtained_from=t.obtained_from,
    )


def _emit_skill_passive_modifiers(state: GameState) -> List[Modifier]:
    """收集所有已掌握技能的 passive_modifiers，作为一次性 modifier 注入掷骰。

    与 on_check buff 同路：不进全局池，每次掷骰临时发射，永不 stale。
    克隆出来确保 id/来源可追溯，进 audit trail。
    """
    result: List[Modifier] = []
    for skill in state.skills:
        for mod in skill.passive_modifiers:
            result.append(Modifier(
                id=f"skill_{skill.id}_{mod.id}",
                source_kind="skill",
                source_id=skill.id,
                target=mod.target,
                selector=mod.selector,
                op=mod.op,
                value=mod.value,
                reason=mod.reason or f"{skill.name}（被动）",
                visible=mod.visible,
            ))
    return result


def _apply_xp_and_rankup(skill: Skill, xp: int) -> dict:
    """给技能加 xp，跨过 rank_thresholds 自动升 rank。返回成长明细。"""
    before_rank = skill.rank
    skill.xp += xp
    # rank_thresholds 是累积阈值：rank N 需要 thresholds[N-1] 总 xp
    new_rank = 1
    for threshold in skill.rank_thresholds:
        if skill.xp >= threshold:
            new_rank += 1
        else:
            break
    skill.rank = new_rank
    return {
        "skill_id": skill.id,
        "xp_gained": xp,
        "total_xp": skill.xp,
        "rank_before": before_rank,
        "rank_after": skill.rank,
        "ranked_up": skill.rank > before_rank,
    }


_reactive_firing = False  # 再入守卫：reactive recipe 里的 roll_check 不应再触发 before_roll


def _fire_reactive_skills(trigger: str, event: dict) -> list:
    """触发匹配 trigger 且 condition 命中的 ReactiveSkill，按序跑其 recipe。

    钩子点：before_roll(roll_check) / on_take_damage(deal_damage) / on_scene_enter(move)。
    带再入守卫——reactive recipe 内部若再跑 roll_check（→before_roll），不会无限递归。
    """
    global _reactive_firing
    if not SESSION.started or _reactive_firing:
        return []
    fired = []
    _reactive_firing = True
    try:
        for skill in SESSION.state.skills:
            rx = skill.reactive
            if not rx or rx.trigger != trigger:
                continue
            if not _match_selector(rx.condition, event):
                continue
            outcomes = _run_recipe(rx.recipe, source=f"reactive:{skill.id}")
            fired.append({"skill_id": skill.id, "trigger": trigger, "steps": outcomes})
    finally:
        _reactive_firing = False
    return fired


# ── §6 Phase 4：Step 白名单执行器 ────────────────────────────────
# recipe 里的每个 Step 走 SKILL_STEP_VERBS 白名单。verb 不重复实现底层逻辑，
# 而是调现有机器（roll_check / Buff 构造 / Modifier 池 / ImprovisedItem），
# 数学始终落在 Modifier 那层。

def _step_apply_buff(args: dict, source: str) -> dict:
    """recipe step：挂一个 content 作者定义的 Buff（不走 7 关——技能是预定义可信内容）。"""
    state = SESSION.state
    name = args.get("name", "技能效果")
    timing = args.get("timing", "on_check")
    if timing not in BUFF_TICK_TIMINGS:
        timing = "on_check"
    buff_id = f"skill_buff_{name.replace(' ', '_')}"
    # 已存在同名则跳过（避免叠加爆炸）
    if any(b.id == buff_id for b in state.buffs):
        return {"verb": "apply_buff", "ok": True, "skipped": "已存在", "buff_id": buff_id}

    mod = Modifier(
        id=f"{buff_id}_main", source_kind="buff", source_id=buff_id,
        target=args.get("target", "roll"), selector=args.get("selector", {}),
        op=args.get("op", "add"), value=float(args.get("value", 0)),
        reason=args.get("reason", name), visible=args.get("visible", "result"),
    )
    buff = Buff(
        id=buff_id, name=name, desc=args.get("desc", ""),
        polarity=args.get("polarity", "buff"),
        source_kind="skill", source_id=source,
        ticks={timing: BuffTick(emit_modifiers=[mod])},
        expire_on=[{"turns": int(args.get("duration", 3))}],
        visible=args.get("visible", "result"),
    )
    state.buffs.append(buff)
    if timing in ("turn_start", "turn_end"):
        _refresh_persistent_buff_mods(state)
    return {"verb": "apply_buff", "ok": True, "buff_id": buff_id, "name": name}


def _step_spawn_improvised(args: dict) -> dict:
    """recipe step：生成一件临时物品入背包。"""
    state = SESSION.state
    name = args.get("name", "临时物品")
    item = ImprovisedItem(
        id=f"imp_{name.replace(' ', '_')}_{state.turn}",
        name=name, desc=args.get("desc", ""),
        category=args.get("category", "trinket"),
        size=args.get("size", "small"),
        ttl=int(args.get("ttl", IMPROVISED_DEFAULT_TTL)),
        tags=args.get("tags", []),
    )
    state.add_item(item.to_inventory_item())
    return {"verb": "spawn_improvised", "ok": True, "item_id": item.id, "name": name}


def _step_narrative_tag(args: dict) -> dict:
    """recipe step：加一个叙事 condition 标签（不影响掷骰）。"""
    state = SESSION.state
    tag = args.get("tag", "")
    if tag and tag not in state.conditions:
        state.conditions.append(tag)
    return {"verb": "narrative_tag", "ok": True, "tag": tag}


def _step_roll_check(args: dict) -> dict:
    """recipe step：跑一次检定，结果用于 on_success/on_failure 分支。"""
    result = roll_check(
        reason=args.get("reason", "技能检定"),
        sides=int(args.get("sides", 20)),
        modifier=int(args.get("modifier", 0)),
        dc=args.get("dc"),
    )
    outcome = result.get("outcome")
    # 无 dc 时视为恒成功（走 on_success）
    success = outcome in ("success", "critical_success") if outcome else True
    return {"verb": "roll_check", "ok": result.get("ok", False),
            "success": success, "roll": result}


def _step_emit_modifier(args: dict, source: str) -> dict:
    """recipe step：向 Modifier 池加一个修正。"""
    mid = f"mod_skill_{source}_{len(SESSION.modifiers)}"
    m = Modifier(
        id=mid, source_kind="skill", source_id=source,
        target=args.get("target", "roll"), selector=args.get("selector", {}),
        op=args.get("op", "add"), value=float(args.get("value", 0)),
        reason=args.get("reason", "技能修正"), visible=args.get("visible", "result"),
    )
    SESSION.modifiers.append(m)
    return {"verb": "emit_modifier", "ok": True, "modifier_id": mid}


def _run_step(step: Step, source: str) -> dict:
    """执行单个 Step，按 verb 分派；roll_check 的成败驱动 on_success/on_failure 子链。"""
    if step.verb not in SKILL_STEP_VERBS:
        return {"verb": step.verb, "ok": False, "error": f"verb 不在白名单: {step.verb}"}

    if step.verb == "apply_buff":
        result = _step_apply_buff(step.args, source)
    elif step.verb == "spawn_improvised":
        result = _step_spawn_improvised(step.args)
    elif step.verb == "narrative_tag":
        result = _step_narrative_tag(step.args)
    elif step.verb == "roll_check":
        result = _step_roll_check(step.args)
    elif step.verb == "emit_modifier":
        result = _step_emit_modifier(step.args, source)
    else:
        result = {"verb": step.verb, "ok": False, "error": "未实现"}

    # 分支：roll_check 用 success 决定走哪条；其余 verb 视为成功走 on_success
    success = result.get("success", result.get("ok", True))
    children = step.on_success if success else step.on_failure
    if children:
        result["children"] = _run_recipe(children, source)
    return result


def _run_recipe(recipe: List[Step], source: str = "") -> list:
    """按序执行 Step 链，返回每步的执行明细。"""
    return [_run_step(step, source) for step in recipe]


def _tick_bearer_buffs(bearer, state: GameState):
    """对单个 bearer 跑一轮 buff tick：turn_start/turn_end 的直接效应 + 过期清理。

    turn_start/turn_end 的 hp/narrative 效应直接作用于 bearer 自身。
    on_check 时机在 roll_check 内单独处理（仅玩家有掷骰）。
    """
    _apply_direct_modifiers(bearer, _emit_buff_modifiers(bearer, "turn_start"), state)
    _apply_direct_modifiers(bearer, _emit_buff_modifiers(bearer, "turn_end"), state)
    _tick_buff_expiry(bearer)
    _purge_expired_buffs(bearer, state)


def _tick_combat_round(enc, state: GameState) -> List["CombatEvent"]:
    """战斗一整轮结束时，对所有存活 combatant 跑 buff tick，返回产生的 CombatEvent。

    流血/灼烧等 turn_start 的 hp modifier 在此作用于各自 hp；hp 归零标记死亡。
    """
    events: List[CombatEvent] = []
    for cid, cb in list(enc.combatants.items()):
        if cb.is_dead or not cb.buffs:
            continue
        hp_before = cb.hp
        _tick_bearer_buffs(cb, state)
        if cb.hp != hp_before:
            events.append(CombatEvent(
                kind="damage" if cb.hp < hp_before else "heal",
                actor=cid, target=cid,
                detail={"hp_delta": cb.hp - hp_before,
                        "target_hp": f"{cb.hp}/{cb.max_hp}",
                        "source": "buff_tick"},
            ))
        if cb.hp <= 0 and not cb.is_dead:
            cb.is_dead = True
            events.append(CombatEvent(
                kind="kill", actor="buff", target=cid,
                detail={"target_hp": f"0/{cb.max_hp}", "source": "buff_tick"},
            ))
    return events


def _remove_modifiers_for_source(source_kind: str, source_id: str):
    """按 source 批量移除 SESSION.modifiers 中的条目。source_id="*" 匹配所有。"""
    SESSION.modifiers = [
        m for m in SESSION.modifiers
        if not (m.source_kind == source_kind
                and (source_id == "*" or m.source_id == source_id))
    ]


@mcp.tool()
def inspect_object(object_id: str) -> dict:
    """检查当前场景或背包中的物体，发现隐藏线索或揭示关联物体。

    Args:
        object_id: 物体 ID
    """
    if err := _require_started():
        return err

    world, state = SESSION.world, SESSION.state
    room = world.get_room(state.position)
    obj = world.get_object(object_id)
    if not obj:
        return {"ok": False, "error": f"未知物体 {object_id!r}"}

    in_room = room and object_id in room.objects
    in_inventory = state.has_item(object_id)
    if not in_room and not in_inventory:
        return {"ok": False, "error": f"{object_id} 不在当前场景也不在背包中"}
    if in_room and obj.hidden:
        return {"ok": False, "error": f"{object_id} 仍处于隐藏状态，当前无法检查"}

    clues_added = []
    flags_set = {}
    if obj.hidden_clue and obj.hidden_flag and not state.flags.get(obj.hidden_flag):
        state.add_clue(obj.hidden_clue)
        clues_added.append(obj.hidden_clue)
        state.flags[obj.hidden_flag] = True
        flags_set[obj.hidden_flag] = True

    revealed = _reveal_objects(obj.reveals_objects, room, world)
    for rid in revealed:
        flag = f"revealed_{rid}"
        state.flags[flag] = True
        flags_set[flag] = True

    expired = _advance_turn(state)

    return {
        "ok": True,
        "object": {
            "id": obj.id,
            "name": obj.name,
            "desc": obj.description,
            "kind": obj.kind,
            "named_tags": obj.named_tags,
            "modifiers": obj.modifiers,
            "traits": obj.traits,
            "base_methods": _object_semantics(obj)["base_methods"],
        },
        "clues_added": clues_added,
        "flags_set": flags_set,
        "revealed": revealed,
        "expired_items": expired,
        "scene": _room_snapshot(world, state),
        "inventory": _inventory_snapshot(state),
        "turn": state.turn,
    }


@mcp.tool()
def call_affordance(object_id: str, verb: str) -> dict:
    """在物体上执行一个已定义的方法（affordance）。

    Args:
        object_id: 物体 ID（从 get_scene 的 objects 列表里取）
        verb: 方法名（从该物体的 affordances 列表里取）
    """
    if err := _require_started():
        return err

    world, state = SESSION.world, SESSION.state
    room = world.get_room(state.position)

    obj = world.get_object(object_id)
    if not obj:
        return {"ok": False, "error": f"未知物体 {object_id!r}"}

    if object_id not in (room.objects if room else []) and not state.has_item(object_id):
        return {"ok": False, "error": f"{object_id} 不在当前场景也不在背包中"}
    if object_id in (room.objects if room else []) and obj.hidden:
        return {"ok": False, "error": f"{object_id} 仍处于隐藏状态，当前无法交互"}

    aff = world.get_affordance(object_id, verb)
    if not aff:
        available = list(obj.affordances.keys())
        return {"ok": False, "error": f"{object_id} 没有 {verb!r} 方法。可用: {available}"}

    # Check requirements
    if aff.requires_item and not state.has_item(aff.requires_item):
        req_obj = world.get_object(aff.requires_item)
        req_name = req_obj.name if req_obj else aff.requires_item
        return {"ok": False, "error": f"需要持有【{req_name}】才能执行 {verb}"}

    if aff.requires_flag and not state.flags.get(aff.requires_flag):
        return {"ok": False, "error": f"条件未满足（需要 flag: {aff.requires_flag}）"}

    # Apply effect
    changes = _apply_effect(aff.effect, state, world)

    # Start combat if effect specifies it
    combat_started = None
    if "start_combat" in aff.effect and isinstance(aff.effect["start_combat"], dict):
        sc = aff.effect["start_combat"]
        canon_ids = sc.get("canon", [])
        imp_list = sc.get("improvised", [])
        initiative = sc.get("initiative_advantage", "")
        start_result = start_combat(canon=canon_ids, improvised=imp_list)
        if start_result.get("ok"):
            combat_started = start_result["encounter"]
            changes["combat_started"] = True
            changes["encounter_id"] = combat_started["id"]

    # Consume self (from inventory or room)
    if aff.consume_self:
        if state.has_item(object_id):
            state.remove_item(object_id)
        elif room and object_id in room.objects:
            room.objects = [o for o in room.objects if o != object_id]
        changes["consumed_self"] = object_id

    # Consume required item
    if aff.consume_item and aff.requires_item:
        state.remove_item(aff.requires_item)
        changes.setdefault("items_removed", []).append(aff.requires_item)

    expired = _advance_turn(state)
    if expired:
        changes["expired_items"] = expired

    return {
        "ok": True,
        "object": object_id,
        "verb": verb,
        "effect_desc": aff.effect.get("message", ""),
        "changes": changes,
        "scene": _room_snapshot(world, state),
        "inventory": _inventory_snapshot(state),
        "turn": state.turn,
    }


# ── Modifier 辅助 ──────────────────────────────────────────────

def _match_selector(selector: dict, match_context: dict) -> bool:
    """检查 modifier 的 selector 是否匹配当前上下文。"""
    if not selector:
        return True
    if "reason_includes" in selector:
        reason = match_context.get("reason", "")
        if not any(kw in reason for kw in selector["reason_includes"]):
            return False
    if "verb" in selector:
        if match_context.get("verb") != selector["verb"]:
            return False
    return True


def _collect_modifiers(target: str, match_context: dict,
                       extra: List[Modifier] | None = None) -> dict[str, list[Modifier]]:
    """从 SESSION 收集匹配的 modifier，按 op 分组。extra 为一次性追加列表。"""
    grouped: dict[str, list[Modifier]] = {}
    for m in SESSION.modifiers:
        if m.target != target:
            continue
        if not _match_selector(m.selector, match_context):
            continue
        grouped.setdefault(m.op, []).append(m)
    if extra:
        for m in extra:
            if m.target != target:
                continue
            if not _match_selector(m.selector, match_context):
                continue
            grouped.setdefault(m.op, []).append(m)
    return grouped


def _resolve_roll_modifiers(raw: int, sides: int, grouped: dict) -> tuple[int, int, list[dict]]:
    """应用 roll 类 modifier。返回 (final_roll, raw_used, audit_entries)。

    raw_used 可能与原始 raw 不同（advantage 双骰取高时记录实际用的那一次）。
    """
    applied: list[dict] = []
    value = float(raw)
    active_raw = raw

    # ── advantage / disadvantage（影响实际掷骰值）──
    has_adv = "advantage" in grouped
    has_dis = "disadvantage" in grouped

    if has_adv and not has_dis:
        second = random.randint(1, sides)
        for m in grouped["advantage"]:
            applied.append(_audit_entry(m))
        if second > value:
            active_raw = second
            value = float(second)
    elif has_dis and not has_adv:
        second = random.randint(1, sides)
        for m in grouped["disadvantage"]:
            applied.append(_audit_entry(m))
        if second < value:
            active_raw = second
            value = float(second)

    # ── clamp ──
    for m in grouped.get("clamp", []):
        value = max(0, min(value, m.value))
        applied.append(_audit_entry(m))

    # ── set ──
    for m in grouped.get("set", []):
        value = m.value
        applied.append(_audit_entry(m))

    # ── mul ──
    for m in grouped.get("mul", []):
        value *= m.value
        applied.append(_audit_entry(m))

    # ── add ──
    for m in grouped.get("add", []):
        value += m.value
        applied.append(_audit_entry(m))

    return int(value), active_raw, applied


def _resolve_dc_modifiers(dc: int, grouped: dict) -> tuple[int, list[dict]]:
    """应用 dc 类 modifier。返回 (modified_dc, audit_entries)。"""
    applied: list[dict] = []
    value = float(dc)

    for m in grouped.get("clamp", []):
        value = max(0, min(value, m.value))
        applied.append(_audit_entry(m))
    for m in grouped.get("set", []):
        value = m.value
        applied.append(_audit_entry(m))
    for m in grouped.get("mul", []):
        value *= m.value
        applied.append(_audit_entry(m))
    for m in grouped.get("add", []):
        value += m.value
        applied.append(_audit_entry(m))

    return int(value), applied


def _audit_entry(m: Modifier) -> dict:
    return {
        "op": m.op, "value": m.value,
        "reason": m.reason,
        "source": f"{m.source_kind}:{m.source_id}" if m.source_id else m.source_kind,
        "visible": m.visible,
    }


@mcp.tool()
def roll_check(reason: str, sides: int = 20, modifier: int = 0, dc: Optional[int] = None) -> dict:
    """骰子检定。自动合入 Modifier 池中的适配修正。

    Args:
        reason: 这次检定的理由（如"撬锁敏捷检定"）
        sides:  骰子面数，默认 d20
        modifier: 修正值（属性加值等，已包含在合算中）
        dc:     难度等级。若提供则返回 outcome（critical_success/success/failure/critical_failure）
    """
    if err := _require_started():
        return err

    # ── Phase 5：before_roll reactive skills（emit_modifier 进池，本次掷骰用完即清）──
    pool_before = len(SESSION.modifiers)
    _fire_reactive_skills("before_roll", {"reason": reason, "sides": sides, "dc": dc})
    reactive_added = SESSION.modifiers[pool_before:]  # 本轮 reactive 新增的，掷骰后撤掉

    # ── Phase 2：on_check buff ticks 作为一次性 modifier ──
    on_check_mods = _emit_buff_modifiers(SESSION.state, "on_check")
    # ── Phase 3：skill passive_modifiers 作为一次性 modifier（掌握期间常驻）──
    passive_mods = _emit_skill_passive_modifiers(SESSION.state)
    extra_mods = on_check_mods + passive_mods

    match_context = {"reason": reason}
    raw = random.randint(1, sides)

    # ── 收集 roll 和 dc 两类 modifier（含 on_check + passive 一次性修正）──
    grouped_roll = _collect_modifiers("roll", match_context, extra_mods)
    grouped_dc = _collect_modifiers("dc", match_context, extra_mods)

    # ── 应用 roll modifier（含 advantage/disadvantage 双骰）──
    final_roll, active_raw, audit_roll = _resolve_roll_modifiers(raw, sides, grouped_roll)
    total = final_roll + modifier

    # ── 应用 dc modifier ──
    modified_dc = dc
    audit_dc: list[dict] = []
    if dc is not None:
        modified_dc, audit_dc = _resolve_dc_modifiers(dc, grouped_dc)
        total = final_roll + modifier

    result: dict = {
        "ok": True,
        "reason": reason,
        "raw": active_raw,
        "modifier": modifier,
        "total": total,
        "sides": sides,
    }
    if dc is not None:
        result["dc"] = modified_dc
        result["original_dc"] = dc
        if sides == 20 and active_raw == 20:
            result["outcome"] = "critical_success"
        elif sides == 20 and active_raw == 1:
            result["outcome"] = "critical_failure"
        elif total >= modified_dc:
            result["outcome"] = "success"
        else:
            result["outcome"] = "failure"

    # ── 写 audit trail ──
    SESSION.last_roll_audit = {
        "reason": reason,
        "sides": sides,
        "raw": active_raw,
        "raw_original": raw,
        "modifier": modifier,
        "total": total,
        "dc_original": dc,
        "dc_final": modified_dc,
        "modifiers_applied": audit_roll + audit_dc,
        "outcome": result.get("outcome"),
    }
    SESSION.rolls_log.append(result)

    # ── Phase 5：撤掉本轮 reactive 临时注入的 modifier（用完即清，不跨轮累积）──
    if reactive_added:
        ids = {m.id for m in reactive_added}
        SESSION.modifiers = [m for m in SESSION.modifiers if m.id not in ids]

    return result


@mcp.tool()
def explain_last_roll() -> dict:
    """返回上一次掷骰的完整修正链路，按来源展开。玩家可借此了解'为什么是这个数'。"""
    audit = SESSION.last_roll_audit
    if not audit:
        return {"ok": False, "error": "尚未进行过掷骰检定。"}

    # 分组：full 可见 vs result 可见 vs hidden
    full_items = []
    result_items = []
    for entry in audit["modifiers_applied"]:
        if entry["visible"] == "hidden":
            continue
        item = f"{entry['op']}({entry['value']}) : {entry['reason']} [{entry['source']}]"
        if entry["visible"] == "full":
            full_items.append(item)
        else:
            result_items.append(item)

    return {
        "ok": True,
        "reason": audit["reason"],
        "raw": audit["raw"],
        "raw_original": audit.get("raw_original", audit["raw"]),
        "modifier": audit["modifier"],
        "total": audit["total"],
        "dc": audit["dc_final"],
        "dc_original": audit["dc_original"],
        "outcome": audit["outcome"],
        "modifiers_full": full_items,       # 玩家能看见来源和数值
        "modifiers_result": result_items,    # 玩家只能看见数值影响
        "line_format": (                     # GM 可以直贴叙事
            f"📊 {audit['reason']} d{audit['sides']}={audit['raw_original']}"
            + (f"→{audit['raw']}" if audit['raw'] != audit.get('raw_original', audit['raw']) else "")
            + (f" + {audit['modifier']}" if audit['modifier'] else "")
            + "".join(f" {'+' if e['op']=='add' else '×' if e['op']=='mul' else ''}{e['value'] if e['op'] in ('add','mul') else e['op']} ({e['reason']})" for e in audit['modifiers_applied'] if e['visible'] != 'hidden')
            + f" = {audit['total']}"
            + (f" vs DC{audit['dc_final']}" if audit['dc_final'] is not None else "")
            + (f" → {audit['outcome']}" if audit['outcome'] else "")
        ),
    }


@mcp.tool()
def add_modifier(
    source_kind: str,
    target: str,
    op: str,
    value: float = 0.0,
    source_id: str = "",
    reason: str = "",
    visible: str = "result",
    reason_includes: str = "",
    verb_match: str = "",
) -> dict:
    """向 Modifier 池添加一个修正。自动生成唯一 id。

    Args:
        source_kind: 来源类型 — skill / buff / item / scene / improvised
        target:     修正目标 — roll / dc / damage / hp / gold / narrative_tag
        op:         操作 — add / mul / set / clamp / advantage / disadvantage / reroll
        value:      数值
        source_id:  上溯来源 id
        reason:     给玩家看的说明（如"潜行训练"）
        visible:    full（看到来源和数值）/ result（只看到数值影响）/ hidden（完全隐藏）
        reason_includes: selector — 检定理由包含此关键词时生效（逗号分隔多个）
        verb_match: selector — 检定关联的 affordance verb 匹配时生效
    """
    if op not in MODIFIER_OPS:
        return {"ok": False, "error": f"不支持的 op={op!r}，可用: {MODIFIER_OPS}"}
    if target not in MODIFIER_TARGETS:
        return {"ok": False, "error": f"不支持的 target={target!r}，可用: {MODIFIER_TARGETS}"}
    if visible not in MODIFIER_VISIBILITY:
        return {"ok": False, "error": f"不支持的 visible={visible!r}，可用: {MODIFIER_VISIBILITY}"}

    mid = f"mod_{source_kind}_{source_id or 'anon'}_{len(SESSION.modifiers)}"

    selector: dict = {}
    if reason_includes:
        selector["reason_includes"] = [s.strip() for s in reason_includes.split(",") if s.strip()]
    if verb_match:
        selector["verb"] = verb_match

    m = Modifier(
        id=mid, source_kind=source_kind, source_id=source_id,
        target=target, selector=selector, op=op, value=value,
        reason=reason, visible=visible,
    )
    SESSION.modifiers.append(m)

    return {
        "ok": True,
        "modifier_id": mid,
        "source_kind": source_kind,
        "target": target,
        "op": op,
        "value": value,
        "reason": reason,
        "total_modifiers": len(SESSION.modifiers),
    }


@mcp.tool()
def remove_modifier(modifier_id: str = "", source_kind: str = "", source_id: str = "") -> dict:
    """从 Modifier 池移除修正。可指定 modifier_id 精确删除，或按 source_kind/source_id 批量删除。

    Args:
        modifier_id: 精确 modifier id
        source_kind: 按来源类型批量删除
        source_id:   按来源 id 批量删除（通常与 source_kind 组合使用）
    """
    before = len(SESSION.modifiers)

    if modifier_id:
        SESSION.modifiers = [m for m in SESSION.modifiers if m.id != modifier_id]
    elif source_kind:
        SESSION.modifiers = [
            m for m in SESSION.modifiers
            if not (m.source_kind == source_kind and (not source_id or m.source_id == source_id))
        ]
    else:
        return {"ok": False, "error": "需提供 modifier_id 或 source_kind"}

    removed = before - len(SESSION.modifiers)
    return {"ok": True, "removed": removed, "total_modifiers_remaining": len(SESSION.modifiers)}


# ── Phase 2：Buff 工具 ───────────────────────────────────────────────


@mcp.tool()
def apply_buff(buff_id: str) -> dict:
    """手动应用一个已定义的 buff 到玩家身上。用于 go_buff/go_debuff 等 presets。

    Args:
        buff_id: buff 的 id（暂支持手动构造）
    """
    if err := _require_started():
        return err

    state = SESSION.state
    # Check for duplicate
    if any(b.id == buff_id for b in state.buffs):
        return {"ok": False, "error": f"buff {buff_id!r} 已存在"}

    return {"ok": False, "error": f"buff {buff_id!r} 未预定义。请用 add_improvised_buff 创建即兴 buff。"}


@mcp.tool()
def remove_buff(buff_id: str) -> dict:
    """移除玩家身上指定 id 的 buff（包括其关联的 modifier）。

    Args:
        buff_id: 要移除的 buff id
    """
    if err := _require_started():
        return err

    state = SESSION.state
    before = len(state.buffs)
    state.buffs = [b for b in state.buffs if b.id != buff_id]
    after = len(state.buffs)
    if before == after:
        return {"ok": False, "error": f"未找到 buff {buff_id!r}"}

    # Clean up modifiers from this buff
    _remove_modifiers_for_source("buff", buff_id)

    return {"ok": True, "removed": buff_id, "buffs_remaining": after}


@mcp.tool()
def add_improvised_buff(
    name: str,
    desc: str,
    polarity: str,
    target: str,
    op: str,
    value: float,
    duration: int,
    timing: str = "on_check",
    reason: str = "",
    visible: str = "result",
    tags: list = None,
    bearer_id: str = "",
) -> dict:
    """Codex 提议即兴 buff/debuff。经 7 关验证后生效。

    7 关：
    1. name 非空、不重复（同一 bearer 上）
    2. polarity ∈ {buff, debuff, neutral}
    3. target ∈ {roll, dc, hp, narrative_tag}（不许动 gold/reputation）
    4. value ∈ [-5, 5]（不允许碾压性修正）
    5. duration ∈ [1, 5] 回合
    6. 每回合最多 1 个 improvised buff
    7. 同一 bearer 身上同时最多 3 个 improvised buff

    bearer_id 为空挂玩家；战斗中可填 combatant id（如 "enemy_thug_01"）把
    debuff 挂到敌人身上（如"濒死流血"）。挂敌人的 hp buff 在战斗每轮 tick。

    Args:
        name:     buff 显示名（如"雨夜湿冷"）
        desc:     给玩家看的说明
        polarity: buff / debuff / neutral
        target:   修正目标 — roll / dc / hp / narrative_tag
        op:       操作 — add / mul / set
        value:    修正值（±5 内）
        duration: 持续回合数（1-5）
        timing:   触发时机 — on_check / turn_start / turn_end / scene_leave（默认 on_check）
        reason:   来源说明（如"被雨水淋透"）
        visible:  full / result / hidden
        tags:     可选标签
    """
    if err := _require_started():
        return err

    state = SESSION.state
    tags = tags or []
    rejections = []

    # 解析 bearer：空 = 玩家；否则查战斗中的 combatant
    if bearer_id:
        enc = SESSION.encounter
        if not enc or bearer_id not in enc.combatants:
            return {"ok": False, "error": f"bearer {bearer_id!r} 不是当前战斗中的 combatant"}
        bearer = enc.combatants[bearer_id]
    else:
        bearer = state

    # Gate 1: name 非空、不重复（同一 bearer 上）
    name = name.strip()
    if not name:
        rejections.append("name 不能为空")
    elif any(b.name == name for b in bearer.buffs):
        rejections.append(f"buff {name!r} 已存在于 {bearer_id or 'player'}")

    # Gate 2: polarity 合法
    if polarity not in BUFF_POLARITIES:
        rejections.append(f"polarity={polarity!r} 不合法，允许: {sorted(BUFF_POLARITIES)}")

    # Gate 3: target 白名单（不许动 gold/reputation）
    if target not in IMPROVISED_BUFF_TARGETS:
        rejections.append(f"target={target!r} 不合法，允许: {sorted(IMPROVISED_BUFF_TARGETS)}")

    # Gate 4: value ∈ [-5, 5]
    if not (-5 <= value <= 5):
        rejections.append(f"value={value} 超出范围 [-5, 5]")
    if value == 0:
        rejections.append("value 不能为 0")

    # Gate 5: duration ∈ [1, 5]
    if not (1 <= duration <= IMPROVISED_BUFF_MAX_DURATION):
        rejections.append(f"duration={duration} 超出范围 [1, {IMPROVISED_BUFF_MAX_DURATION}]")

    # Gate 6: 每回合最多 1 个 improvised buff
    if state.improvised_buff_count_this_turn >= IMPROVISED_BUFF_MAX_PER_TURN:
        rejections.append(f"每回合最多 {IMPROVISED_BUFF_MAX_PER_TURN} 个 improvised buff")

    # Gate 7: 同一 bearer 身上最多 3 个 improvised buff
    improvised_count = sum(1 for b in bearer.buffs if b.source_kind == "improvised")
    if improvised_count >= IMPROVISED_BUFF_MAX_ACTIVE:
        rejections.append(f"{bearer_id or 'player'} 身上已有 {improvised_count}/{IMPROVISED_BUFF_MAX_ACTIVE} 个 improvised buff")

    if rejections:
        return {"ok": False, "rejected": True, "reasons": rejections}

    # Validation passed — create the buff
    if timing not in BUFF_TICK_TIMINGS:
        if target in ("roll", "dc"):
            timing = "on_check"
        elif target == "hp":
            timing = "turn_start"
        else:
            timing = "on_check"

    buff_id = f"imp_buff_{name.replace(' ', '_')}"

    buff = Buff(
        id=buff_id,
        name=name,
        desc=desc,
        polarity=polarity,
        source_kind="improvised",
        source_id=buff_id,
        tags=[t for t in tags if isinstance(t, str)],
        ticks={
            timing: BuffTick(emit_modifiers=[
                Modifier(
                    id=f"{buff_id}_main",
                    source_kind="buff",
                    source_id=buff_id,
                    target=target,
                    selector={},
                    op=op,
                    value=float(value),
                    reason=reason or desc,
                    visible=visible,
                ),
            ]),
        },
        expire_on=[{"turns": duration}],
        visible=visible,
    )

    bearer.buffs.append(buff)
    state.improvised_buff_count_this_turn += 1

    # 玩家的 persistent modifier 立即刷进全局 roll 池（敌人 buff 不进池）
    if bearer is state and timing in ("turn_start", "turn_end"):
        _refresh_persistent_buff_mods(state)

    return {
        "ok": True,
        "buff_id": buff_id,
        "bearer": bearer_id or "player",
        "name": name,
        "polarity": polarity,
        "target": target,
        "op": op,
        "value": value,
        "duration": duration,
        "timing": timing,
        "total_buffs": len(bearer.buffs),
    }


# ── §6 Phase 3：Skill 工具 ───────────────────────────────────────

def _skill_snapshot(skill: Skill) -> dict:
    """技能的玩家可见摘要。"""
    return {
        "id": skill.id,
        "name": skill.name,
        "desc": skill.desc,
        "rank": skill.rank,
        "xp": skill.xp,
        "next_threshold": next(
            (t for t in skill.rank_thresholds if t > skill.xp), None
        ),
        "passive_count": len(skill.passive_modifiers),
        "has_active": skill.active is not None,
        "has_reactive": skill.reactive is not None,
        "obtained_from": skill.obtained_from,
    }


@mcp.tool()
def learn_skill(skill_id: str) -> dict:
    """玩家习得一个 content 中预定义的技能（从世界 SKILLS 注册表取）。

    技能一旦掌握，其 passive_modifiers 在每次相关掷骰自动生效（进 audit trail），
    active/reactive 部分分别由 use_skill / 触发器系统驱动。

    Args:
        skill_id: 技能 id（content/<world>.py 的 SKILLS 表 key）
    """
    if err := _require_started():
        return err

    world, state = SESSION.world, SESSION.state
    if _get_skill(state, skill_id):
        return {"ok": False, "error": f"已掌握技能 {skill_id!r}"}

    template = world.get_skill(skill_id)
    if not template:
        available = list((world.skills or {}).keys())
        return {"ok": False, "error": f"未知技能 {skill_id!r}。可用: {available}"}

    # 深拷贝模板到玩家身上（成长状态独立于模板）
    learned = _clone_skill(template)
    state.skills.append(learned)

    return {
        "ok": True,
        "learned": _skill_snapshot(learned),
        "total_skills": len(state.skills),
    }


@mcp.tool()
def grant_xp(skill_id: str, xp: int, reason: str = "") -> dict:
    """给已掌握技能授予经验，跨过阈值自动升 rank。

    Args:
        skill_id: 技能 id
        xp:       经验值（正整数，如解决任务后 +5）
        reason:   来源说明（如"完成潜入任务"）
    """
    if err := _require_started():
        return err
    if xp <= 0:
        return {"ok": False, "error": "xp 必须为正整数"}

    skill = _get_skill(SESSION.state, skill_id)
    if not skill:
        return {"ok": False, "error": f"未掌握技能 {skill_id!r}"}

    growth = _apply_xp_and_rankup(skill, xp)
    growth["reason"] = reason
    growth["ok"] = True
    growth["skill"] = _skill_snapshot(skill)
    return growth


@mcp.tool()
def use_skill(skill_id: str) -> dict:
    """主动施放一个已掌握的 active 技能：校验资源/冷却 → 扣消耗 → 跑 recipe。

    cost 支持 stamina / hp / gold / item（持有指定物品 id）。施放后进入冷却，
    冷却随叙事回合递减。recipe 走 Step 白名单（apply_buff/spawn_improvised/
    narrative_tag/roll_check/emit_modifier），不含战斗 verb。

    Args:
        skill_id: 技能 id（须已 learn_skill 且该技能有 active 部分）
    """
    if err := _require_started():
        return err

    state = SESSION.state
    skill = _get_skill(state, skill_id)
    if not skill:
        return {"ok": False, "error": f"未掌握技能 {skill_id!r}"}
    if not skill.active:
        return {"ok": False, "error": f"{skill.name} 没有主动效果（非 active 技能）"}

    act = skill.active

    # ── 冷却校验 ──
    if act.remaining_cooldown > 0:
        return {"ok": False, "error": f"{skill.name} 冷却中，剩余 {act.remaining_cooldown} 回合"}

    # ── 资源校验（先验后扣，避免半途失败）──
    cost = act.cost or {}
    stamina_cost = int(cost.get("stamina", 0))
    hp_cost = int(cost.get("hp", 0))
    gold_cost = int(cost.get("gold", 0))
    item_cost = cost.get("item", "")
    shortfalls = []
    if stamina_cost and state.vitals.stamina < stamina_cost:
        shortfalls.append(f"耐力不足（需 {stamina_cost}，有 {state.vitals.stamina}）")
    if hp_cost and state.vitals.hp <= hp_cost:
        shortfalls.append(f"生命不足（需 >{hp_cost}）")
    if gold_cost and state.vitals.gold < gold_cost:
        shortfalls.append(f"金币不足（需 {gold_cost}）")
    if item_cost and not state.has_item(item_cost):
        shortfalls.append(f"缺少消耗物品 {item_cost!r}")
    if shortfalls:
        return {"ok": False, "error": "；".join(shortfalls)}

    # ── 扣消耗 ──
    if stamina_cost:
        state.vitals.stamina -= stamina_cost
    if hp_cost:
        state.vitals.hp = max(0, state.vitals.hp - hp_cost)
    if gold_cost:
        state.vitals.gold -= gold_cost
    if item_cost:
        state.remove_item(item_cost)

    # ── 执行 recipe ──
    steps = _run_recipe(act.recipe, source=skill.id)

    # ── 进入冷却 ──
    act.remaining_cooldown = act.cooldown

    return {
        "ok": True,
        "skill_id": skill_id,
        "name": skill.name,
        "cost_paid": {"stamina": stamina_cost, "hp": hp_cost,
                      "gold": gold_cost, "item": item_cost or None},
        "steps": steps,
        "cooldown": act.cooldown,
        "state_context": _state_context(state),
    }


# ── 战斗系统 helpers ─────────────────────────────────────────────

def _roll_damage(expression: str) -> int:
    """Parse dice expression. Supports: '1d4', '2d6', '1d8+2', '2d6+1'."""
    expr = expression.strip()
    bonus = 0
    if "+" in expr:
        parts = expr.split("+")
        expr, bonus_str = parts[0].strip(), parts[1].strip()
        bonus = int(bonus_str)
    if "d" not in expr:
        return int(expr) + bonus
    count_str, sides_str = expr.split("d")
    count = int(count_str or "1")
    sides = int(sides_str)
    total = sum(random.randint(1, sides) for _ in range(count))
    return total + bonus


def _build_player_combatant(state: GameState) -> Combatant:
    """从 GameState 投影玩家 Combatant。"""
    player_ac = state.vitals.ac
    # Check for armor modifiers in pool
    ac_mods = _collect_for_target("ac", {"reason": "combat"})
    for m in ac_mods:
        if m.op == "add":
            player_ac += int(m.value)
    return Combatant(
        id="player", name=state.profile.name, side="player",
        hp=state.vitals.hp, max_hp=state.vitals.max_hp,
        ac=player_ac, speed=state.vitals.speed,
        damage_expr="1d4", damage_type="blunt",
        damage_types_resist=dict(state.vitals.damage_types_resist),
        stamina=state.vitals.stamina, max_stamina=state.vitals.max_stamina,
    )


def _build_enemy_from_template(tmpl: EnemyTemplate, suffix: str = "") -> Combatant:
    """从 EnemyTemplate 构建 Combatant。"""
    eid = f"enemy_{tmpl.id}{suffix}"
    import random as _random
    return Combatant(
        id=eid, name=tmpl.name + suffix, side="enemy",
        hp=tmpl.hp, max_hp=tmpl.max_hp,
        ac=tmpl.ac, speed=tmpl.speed,
        damage_expr=tmpl.damage_expr, damage_type=tmpl.damage_type,
        damage_types_resist=dict(tmpl.damage_types_resist),
        behavior_profile=tmpl.behavior_profile,
        skills=list(tmpl.skills),
    )


def _build_enemy_from_archetype(name: str, archetype_key: str, suffix: str = "") -> Optional[Combatant]:
    """从 archetype 表生成 improvised Combatant。stats 由 MCP 决定。"""
    arch = ENEMY_ARCHETYPES.get(archetype_key)
    if not arch:
        return None
    h_min, h_max = arch["hp_range"]
    hp = random.randint(h_min, h_max)
    eid = f"enemy_imp_{name.replace(' ', '_')}{suffix}"
    return Combatant(
        id=eid, name=name + suffix, side="enemy",
        hp=hp, max_hp=hp,
        ac=arch["ac"], speed=arch["speed"],
        damage_expr=arch["damage_expr"], damage_type=arch["damage_type"],
        behavior_profile=arch["behavior_profile"],
    )


def _collect_for_target(target: str, match_context: dict) -> list[Modifier]:
    """Collect modifiers matching target + selector."""
    result = []
    for m in SESSION.modifiers:
        if m.target != target:
            continue
        if not _match_selector(m.selector, match_context):
            continue
        result.append(m)
    return result


def _encounter_snapshot() -> dict:
    """Return a compact encounter view for get_state() / combat tools."""
    enc = SESSION.encounter
    if not enc:
        return {"active": False}
    combatants = []
    for cid, c in enc.combatants.items():
        combatants.append({
            "id": c.id, "name": c.name, "side": c.side,
            "hp": c.hp, "max_hp": c.max_hp, "ac": c.ac,
            "is_dead": c.is_dead,
        })
    active = enc.turn_order[enc.active_idx] if enc.turn_order and enc.active_idx < len(enc.turn_order) else "?"
    recent = []
    for ev in enc.log[-6:]:
        recent.append({"kind": ev.kind, "actor": ev.actor, "target": ev.target, "detail": ev.detail})
    return {
        "active": True,
        "id": enc.id,
        "round": enc.round,
        "active_combatant": active,
        "turn_order": enc.turn_order,
        "combatants": combatants,
        "recent_events": recent,
        "combat_hud": _build_combat_hud(enc),
    }


def _write_combat_log(events: list, enc: Encounter, source: str):
    """Append combat events to logs/combat.jsonl for debug tracing."""
    try:
        LOG_DIR = _HERE / "logs"
        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / "combat.jsonl"
        entries = []
        for ev in events:
            entries.append({
                "ts": f"round_{enc.round}", "source": source,
                "kind": ev.kind, "actor": ev.actor, "target": ev.target,
                "detail": ev.detail,
            })
        entries.append({
            "ts": f"round_{enc.round}", "source": source, "kind": "snapshot",
            "combatants": {
                cid: {"hp": c.hp, "max_hp": c.max_hp, "is_dead": c.is_dead}
                for cid, c in enc.combatants.items()
            },
        })
        with open(log_path, "a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # log failure never blocks game


def _enemy_profiles_for_scene(state: GameState) -> list:
    """Return enemy combat profile summaries for the current room."""
    world = SESSION.world
    room = world.get_room(state.position)
    if not room or not room.enemies:
        return []
    profiles = []
    for eid in room.enemies:
        tmpl = world.get_enemy(eid)
        if not tmpl:
            continue
        profiles.append({
            "id": eid,
            "name": tmpl.name,
            "archetype": tmpl.archetype,
            "hp": tmpl.hp, "max_hp": tmpl.max_hp,
            "ac": tmpl.ac,
            "damage_expr": tmpl.damage_expr,
            "damage_type": tmpl.damage_type,
            "behavior_profile": tmpl.behavior_profile,
            "flavor": tmpl.flavor,
        })
    return profiles


# ── 战斗 MCP 工具 ────────────────────────────────────────────────

@mcp.tool()
def start_combat(canon: list[str] = None, improvised: list[dict] = None) -> dict:
    """开始一场战斗遭遇。

    Args:
        canon: 引用 content/<world>.py 中 ENEMIES 表的 id 列表，例 ["dock_thug"]
        improvised: [{name, archetype, count}] 列表，通过 archetype 表生成敌人
                    例 [{"name":"醉汉","archetype":"brute_low","count":1}]

    MCP 自动把玩家从 GameState 投影成 Combatant，roll initiative。
    返回 encounter 快照 + 谁先动。
    """
    if err := _require_started():
        return err
    if SESSION.in_combat:
        return {"ok": False, "error": "已在战斗中，请先结束当前战斗。"}

    canon = canon or []
    improvised = improvised or []
    world, state = SESSION.world, SESSION.state

    combatants: dict[str, Combatant] = {}

    # ── Player ──
    player = _build_player_combatant(state)
    combatants["player"] = player

    # ── Canon enemies ──
    for eid in canon:
        tmpl = world.get_enemy(eid)
        if not tmpl:
            return {"ok": False, "error": f"未知 canon 敌人 {eid!r}"}
        ec = _build_enemy_from_template(tmpl)
        cid = ec.id
        count = 1
        # Handle numbered suffixes if same enemy added multiple times
        while cid in combatants:
            count += 1
            ec = _build_enemy_from_template(tmpl, suffix=f"_{count}")
            cid = ec.id
        combatants[cid] = ec

    # ── Improvised enemies ──
    for imp in improvised:
        name = imp.get("name", "不明敌人")
        archetype_key = imp.get("archetype", "brute_low")
        count = imp.get("count", 1)
        arch_def = ENEMY_ARCHETYPES.get(archetype_key)
        if not arch_def:
            return {"ok": False, "error": f"未知 archetype {archetype_key!r}，可用: {list(ENEMY_ARCHETYPES.keys())}"}
        for i in range(count):
            suffix = f"_{i + 1}" if count > 1 else ""
            ec = _build_enemy_from_archetype(name, archetype_key, suffix)
            if ec:
                # dedup id
                cid = ec.id
                n = 1
                while cid in combatants:
                    n += 1
                    cid = f"{ec.id}_{n}"
                ec.id = cid
                combatants[cid] = ec

    # ── Initiative: player first, then enemies by speed descending ──
    turn_order = ["player"]
    enemy_ids = [cid for cid in combatants if cid != "player"]
    enemy_ids.sort(key=lambda cid: combatants[cid].speed, reverse=True)
    turn_order += enemy_ids

    # ── Build Encounter ──
    enc_id = f"enc_{state.turn}_{len(canon) + sum(i.get('count', 1) for i in improvised)}"
    enc = Encounter(id=enc_id, combatants=combatants, turn_order=turn_order,
                    round=1, active_idx=0, log=[])
    SESSION.encounter = enc

    snapshot = _encounter_snapshot()
    snapshot["player_hp"] = player.hp
    snapshot["player_max_hp"] = player.max_hp
    snapshot["combatant_count"] = len(combatants)
    return {"ok": True, "encounter": snapshot}


@mcp.tool()
def request_combat(reason: str, canon: list[str] = None,
                   improvised: list[dict] = None,
                   initiative_advantage: str = "") -> dict:
    """Codex 或玩家提议开战。MCP 做合法性校验后等效于 start_combat。

    Args:
        reason: 开战理由（如"守卫发现你闯入库房"）
        canon: enemy id 列表
        improvised: [{name, archetype, count}] 列表
        initiative_advantage: "player"=玩家先手加值 / ""=正常
    """
    if err := _require_started():
        return err
    if SESSION.in_combat:
        return {"ok": False, "error": "已在战斗中。"}

    world, state = SESSION.world, SESSION.state
    room = world.get_room(state.position)

    # Validation: at least one valid enemy source
    has_canon = bool(canon)
    has_improvised = bool(improvised)
    if not has_canon and not has_improvised:
        # Check if room has registered enemies
        if room and room.enemies:
            canon = list(room.enemies)
            has_canon = True
        else:
            return {"ok": False, "error": "当前场景无可战斗敌人。请提供 canon 或 improvised 参数。"}

    # Start combat
    result = start_combat(canon=canon, improvised=improvised)
    if not result["ok"]:
        return result

    result["reason"] = reason
    result["initiative_advantage"] = initiative_advantage
    return result


@mcp.tool()
def end_combat(reason: str = "") -> dict:
    """结束当前战斗遭遇。

    把 player Combatant 的最终 hp/buff/stamina 写回 GameState。
    返回战利品、经验、留下的 buff。

    Args:
        reason: 结束原因（"全员战败" / "玩家逃跑" / "和平解决"）
    """
    if err := _require_started():
        return err
    enc = SESSION.encounter
    if not enc:
        return {"ok": False, "error": "当前无战斗。"}

    state = SESSION.state
    player = enc.combatants.get("player")

    # Write back player state
    if player:
        state.vitals.hp = max(0, player.hp)
        state.vitals.stamina = player.stamina

    # Compute loot from dead enemies
    loot = []
    enemies_defeated = []
    for cid, c in enc.combatants.items():
        if c.side == "enemy" and c.is_dead:
            enemies_defeated.append({"id": cid, "name": c.name})
            # Check if this came from a canon template
            tmpl = SESSION.world.get_enemy(cid.replace("enemy_", "").rsplit("_", 1)[0])
            # also check original ID format
            for eid in (SESSION.world.enemies or {}):
                if c.id.startswith(f"enemy_{eid}"):
                    tmpl = SESSION.world.get_enemy(eid)
                    if tmpl and tmpl.loot:
                        loot.extend(tmpl.loot)
                    break

    # Events log for narrative
    events = [
        {"kind": ev.kind, "actor": ev.actor, "target": ev.target, "detail": ev.detail}
        for ev in enc.log
    ]

    result = {
        "ok": True,
        "reason": reason,
        "rounds": enc.round,
        "player_hp": player.hp if player else 0,
        "player_max_hp": player.max_hp if player else 0,
        "enemies_defeated": enemies_defeated,
        "loot": loot,
        "events": events,
    }

    SESSION.encounter = None
    return result


@mcp.tool()
def declare_intent(actor: str, intent: str, target: str = "",
                   skill_id: str = "", weapon: str = "") -> dict:
    """声明当前行动者的战斗意图。核心战斗工具。

    Args:
        actor:     行动者 id（"player" 或 "enemy_xxx"）
        intent:    意图 — attack / defend / flee / use_item / use_skill
        target:    目标 id（attack 时必填）
        skill_id:  使用的技能 id（可选）
        weapon:    使用的武器 id（可选，从背包取）

    内部完整执行：命中判定 → 伤害 → buff → 死亡判定，返回 CombatEvent[] + 下一行动者。
    """
    if err := _require_started():
        return err
    enc = SESSION.encounter
    if not enc:
        return {"ok": False, "error": "当前无战斗。"}

    # Validate actor
    if actor not in enc.combatants:
        return {"ok": False, "error": f"未知行动者 {actor!r}"}
    active_id = enc.turn_order[enc.active_idx] if enc.active_idx < len(enc.turn_order) else ""
    if actor != active_id:
        return {"ok": False, "error": f"不是 {actor} 的回合，当前行动者是 {active_id}"}

    combatant = enc.combatants[actor]
    events: list[CombatEvent] = []

    # ── attack ──
    if intent == "attack":
        if not target or target not in enc.combatants:
            return {"ok": False, "error": f"目标 {target!r} 不存在"}
        target_com = enc.combatants[target]

        damage_expr = combatant.damage_expr
        # Use weapon if provided
        if weapon and weapon != "":
            # Check inventory for weapon item
            item = SESSION.state.get_item(weapon)
            if item and "damage" in item.tags:
                for tag in item.tags:
                    if tag.startswith("dmg:"):
                        damage_expr = tag.split(":", 1)[1]
                        break

        # Attack roll vs target AC
        atk_roll = roll_check(
            reason=f"{combatant.name} 攻击 {target_com.name}",
            sides=20, dc=target_com.ac,
        )
        if not atk_roll["ok"]:
            return atk_roll

        if atk_roll.get("outcome") in ("success", "critical_success"):
            # Hit — roll damage, then resolve through the unified damage entry
            # (E3：探索/战斗共用 _resolve_damage，消除内联重复)
            dmg_raw = _roll_damage(damage_expr)
            dmg_type = combatant.damage_type
            dmg = _resolve_damage(
                target_com, dmg_raw, dmg_type,
                {"reason": f"{combatant.name} 攻击 {target_com.name}"},
            )
            final_dmg = dmg["damage"]

            events.append(CombatEvent(
                kind="attack", actor=actor, target=target,
                detail={"roll": atk_roll["raw"], "ac": target_com.ac},
                roll_audit=SESSION.last_roll_audit,
            ))
            events.append(CombatEvent(
                kind="hit", actor=actor, target=target,
                detail={"damage": final_dmg, "damage_type": dmg_type,
                        "target_hp": f"{target_com.hp}/{target_com.max_hp}"},
            ))
        else:
            events.append(CombatEvent(
                kind="miss", actor=actor, target=target,
                detail={"roll": atk_roll["raw"], "ac": target_com.ac},
                roll_audit=SESSION.last_roll_audit,
            ))

        # Check target death
        if target_com.hp <= 0:
            target_com.is_dead = True
            events.append(CombatEvent(
                kind="kill", actor=actor, target=target,
                detail={"target_hp": f"0/{target_com.max_hp}"},
            ))

    # ── defend ──
    elif intent == "defend":
        enc.combatants[actor].ac += 2  # temp AC bonus until end of round
        events.append(CombatEvent(
            kind="buff_applied", actor=actor, target=actor,
            detail={"effect": "临时 AC +2（防御姿态）"},
        ))

    # ── flee ──
    elif intent == "flee":
        # Find highest enemy AC as flee DC
        flee_dc = 10
        for cid, c in enc.combatants.items():
            if c.side == "enemy" and not c.is_dead:
                if c.ac > flee_dc:
                    flee_dc = c.ac
        flee_roll = roll_check(
            reason=f"{combatant.name} 逃跑", sides=20, dc=flee_dc,
        )
        if flee_roll.get("outcome") in ("success", "critical_success"):
            events.append(CombatEvent(
                kind="flee", actor=actor, target="",
                detail={"success": True, "roll": flee_roll["raw"], "dc": flee_dc},
            ))
            # End combat immediately
            enc.log.extend(events)
            _write_combat_log(events, enc, "declare_intent_flee")
            end_combat(reason=f"{combatant.name} 逃跑")
            # Return pre-built snapshot
            snapshot = _encounter_snapshot()
            snapshot["combat_ended"] = True
            snapshot["end_reason"] = f"{combatant.name} 逃跑"
            return {
                "ok": True,
                "events": [
                    {"kind": e.kind, "actor": e.actor, "target": e.target, "detail": e.detail}
                    for e in events
                ],
                "encounter": snapshot,
                "next_actor": None,
            }
        else:
            events.append(CombatEvent(
                kind="flee", actor=actor, target="",
                detail={"success": False, "roll": flee_roll["raw"], "dc": flee_dc},
            ))

    # ── use_item ──
    elif intent == "use_item" and weapon:
        item = SESSION.state.get_item(weapon)
        if item:
            events.append(CombatEvent(
                kind="skill_used", actor=actor, target=target or actor,
                detail={"item": weapon, "name": item.name},
            ))
            # Item effect handled by specific logic or just narrative
            if "consume" in item.tags:
                SESSION.state.remove_item(weapon)
        else:
            return {"ok": False, "error": f"物品 {weapon!r} 不在背包"}

    else:
        return {"ok": False, "error": f"不支持的意图 {intent!r}，可用: attack/defend/flee/use_item"}

    # ── Check if all enemies dead ──
    all_enemies_dead = all(
        c.is_dead for cid, c in enc.combatants.items() if c.side == "enemy"
    )
    if all_enemies_dead and enc.combatants:
        events.append(CombatEvent(
            kind="combat_end", actor="system", target="",
            detail={"reason": "all enemies defeated"},
        ))

    # ── Append events to log ──
    enc.log.extend(events)
    _write_combat_log(events, enc, "declare_intent")

    # ── Advance turn ──
    dead_ids = {cid for cid, c in enc.combatants.items() if c.is_dead}
    enc.active_idx = (enc.active_idx + 1) % len(enc.turn_order)
    skipped = 0
    while skipped < len(enc.turn_order):
        next_id = enc.turn_order[enc.active_idx]
        if next_id not in dead_ids:
            break
        enc.active_idx = (enc.active_idx + 1) % len(enc.turn_order)
        skipped += 1

    if all_enemies_dead:
        # Auto end
        enc.log.extend(events)
        _write_combat_log(events, enc, "declare_intent_victory")
        end_result = end_combat(reason="all enemies defeated")
        snapshot = _encounter_snapshot()
        snapshot["combat_ended"] = True
        snapshot["end_reason"] = "all enemies defeated"
        return {
            "ok": True,
            "events": [
                {"kind": e.kind, "actor": e.actor, "target": e.target, "detail": e.detail}
                for e in events
            ],
            "encounter": snapshot,
            "next_actor": None,
            "end_combat_result": end_result,
        }

    # Bump round if we wrapped around to first
    next_id = enc.turn_order[enc.active_idx]
    if next_id == "player" and enc.active_idx == 0:
        enc.round += 1
        # §9/E2：一整轮战斗结束 → 所有 bearer 的 buff tick（流血/灼烧/过期）
        events.extend(_tick_combat_round(enc, SESSION.state))

    snapshot = _encounter_snapshot()
    return {
        "ok": True,
        "events": [
            {"kind": e.kind, "actor": e.actor, "target": e.target, "detail": e.detail}
            for e in events
        ],
        "encounter": snapshot,
        "next_actor": next_id,
    }


@mcp.tool()
def enemy_suggest(enemy_id: str) -> dict:
    """轮到敌人时，MCP 根据 behavior_profile 返回建议意图。

    Codex 拿到后可用 declare_intent 执行（可微调措辞），但数值/skill 不做改动。

    Args:
        enemy_id: 敌人 combatant id（如 "enemy_dock_thug"）
    """
    enc = SESSION.encounter
    if not enc:
        return {"ok": False, "error": "当前无战斗。"}
    if enemy_id not in enc.combatants:
        return {"ok": False, "error": f"未知敌人 {enemy_id!r}"}

    enemy = enc.combatants[enemy_id]
    profile = enemy.behavior_profile

    # Determine possible targets (player and non-dead enemies on other sides)
    targets = [
        c for cid, c in enc.combatants.items()
        if cid != enemy_id and not c.is_dead and c.side != enemy.side
    ]
    if not targets:
        return {"ok": True, "enemy_id": enemy_id, "suggested_intent": "wait",
                "reason": "no valid targets", "target": ""}

    intent = "attack"
    suggested_target = targets[0].id

    if profile == "aggressive":
        # Attack the enemy with lowest current HP
        targets.sort(key=lambda c: c.hp)
        suggested_target = targets[0].id
        reason = f"aggressive: 攻击血量最少的 {targets[0].name}"

    elif profile == "cautious":
        if enemy.hp < enemy.max_hp * 0.5:
            intent = "flee"
            suggested_target = ""
            reason = f"cautious: hp={enemy.hp}/{enemy.max_hp} < 50%, 尝试逃跑"
        else:
            # Attack lowest threat target (lowest damage potential)
            targets.sort(key=lambda c: (
                int(c.damage_expr.split("d")[1].split("+")[0]) if "d" in c.damage_expr else 4
            ))
            suggested_target = targets[0].id
            reason = f"cautious: 攻击威胁最低的 {targets[0].name}"

    elif profile == "opportunist":
        # Attack target with lowest HP
        targets.sort(key=lambda c: c.hp)
        suggested_target = targets[0].id
        reason = f"opportunist: 攻击最虚弱的 {targets[0].name}"

    elif profile == "support":
        # Heal ally with lowest HP, or attack if no allies to heal
        allies = [c for cid, c in enc.combatants.items() if cid != enemy_id and
                  c.side == enemy.side and not c.is_dead and c.hp < c.max_hp]
        if allies:
            allies.sort(key=lambda c: c.hp)
            intent = "use_item"
            suggested_target = allies[0].id
            reason = f"support: 治疗盟友 {allies[0].name}"
        else:
            targets.sort(key=lambda c: c.hp)
            suggested_target = targets[0].id
            reason = f"support: 无盟友需治疗，自卫生存"

    else:
        # Fallback aggressive
        targets.sort(key=lambda c: c.hp)
        suggested_target = targets[0].id
        reason = f"default(→aggressive): 攻击 {targets[0].name}"

    return {
        "ok": True,
        "enemy_id": enemy_id,
        "enemy_name": enemy.name,
        "enemy_hp": f"{enemy.hp}/{enemy.max_hp}",
        "profile": profile,
        "suggested_intent": intent,
        "suggested_target": suggested_target,
        "suggested_target_name": enc.combatants[suggested_target].name if suggested_target in enc.combatants else "",
        "reason": reason,
    }


@mcp.tool()
def deal_damage(target: str, amount: int, damage_type: str = "blunt",
                reason: str = "") -> dict:
    """统一伤害入口——探索态炸/烧/砸场景物体，战斗态对 combatant 造成伤害。

    BG3 式"万物皆可破坏"：场景里的牛粪、酒坛、木门天生有 hp/抗性（默认冻结
    不进 get_scene），玩家做出破坏意图时此工具解冻它们参与结算。indestructible
    的（墙/大地）会被拒绝。hp 归零时：场景物跑 on_destroyed（揭示隐藏物/置 flag/
    留痕），战斗 combatant 标记死亡。

    Args:
        target:      目标 id。战斗中优先解析 combatant；否则解析当前场景的 GameObject。
        amount:      原始伤害值（正整数）。会经 damage modifier 和目标抗性调整。
        damage_type: 伤害类型 — blunt/slash/pierce/fire/arcane 等，匹配目标抗性表。
        reason:      叙事理由（如"鞭炮炸牛粪堆"），同时作为 damage modifier 的 selector 上下文。
    """
    if err := _require_started():
        return err
    if amount <= 0:
        return {"ok": False, "error": "amount 必须为正整数"}

    world, state = SESSION.world, SESSION.state
    enc = SESSION.encounter
    match_context = {"reason": reason} if reason else {}

    # ── 战斗态：优先解析 combatant ──
    if enc and target in enc.combatants:
        bearer = enc.combatants[target]
        if bearer.is_dead:
            return {"ok": False, "error": f"{target} 已经死亡"}
        result = _resolve_damage(bearer, amount, damage_type, match_context)
        if result["destroyed"] and not bearer.is_dead:
            bearer.is_dead = True
        payload = {"ok": True, "context": "combat", **result}
        # ── Phase 5：玩家受击触发 on_take_damage reactive skills ──
        if target == "player":
            fired = _fire_reactive_skills("on_take_damage", {
                "damage": result["damage"], "damage_type": damage_type,
                "reason": reason, "hp_after": result["hp_after"],
            })
            if fired:
                payload["reactive_fired"] = fired
        return payload

    # ── 探索态：解析场景 GameObject ──
    obj = world.get_object(target)
    if not obj:
        return {"ok": False, "error": f"未知目标 {target!r}（不是战斗单位也不是场景物体）"}

    room = world.get_room(state.position)
    in_room = bool(room and target in room.objects)
    in_inventory = state.has_item(target)
    if not in_room and not in_inventory:
        return {"ok": False, "error": f"{target} 不在当前场景也不在背包中"}
    if in_room and obj.hidden:
        return {"ok": False, "error": f"{target} 仍处于隐藏状态，无法作为目标"}

    # 属性解冻 + 可破坏校验（indestructible 的墙/大地打不动）
    if not is_damageable(obj):
        return {"ok": False, "error": f"{obj.name} 坚不可摧，无法被破坏"}

    result = _resolve_damage(obj, amount, damage_type, match_context)
    payload = {"ok": True, "context": "exploration", "name": obj.name, **result}

    if result["destroyed"]:
        payload["on_destroyed"] = _run_on_destroyed(obj, state, world)
        payload["scene"] = _room_snapshot(world, state)

    return payload


@mcp.tool()
def move(direction: str) -> dict:
    """向某方向移动。

    Args:
        direction: 方向（north/south/east/west 或自定义方向 ID）
    """
    if err := _require_started():
        return err

    world, state = SESSION.world, SESSION.state
    old_room = world.get_room(state.position)
    if not old_room:
        return {"ok": False, "error": "当前房间数据缺失"}

    if direction in old_room.locked_exits:
        lock_obj_id = old_room.locked_exits[direction]
        lock_obj = world.get_object(lock_obj_id)
        lock_name = lock_obj.name if lock_obj else lock_obj_id
        return {"ok": False, "error": f"出口 {direction} 被锁住，需要【{lock_name}】解锁"}

    if direction not in old_room.exits:
        return {"ok": False, "error": f"无法向 {direction} 移动。可用方向: {list(old_room.exits.keys())}"}

    new_room_id = old_room.exits[direction]
    new_room = world.get_room(new_room_id)
    if not new_room:
        return {"ok": False, "error": f"目标房间 {new_room_id} 不存在"}

    # ── 离开旧房间：写入 RoomSnapshot ──
    _write_room_snapshot(world, state, old_room)

    # ── Phase 2：处理 scene_leave buff ticks ──
    _apply_direct_modifiers(state, _emit_buff_modifiers(state, "scene_leave"), state)

    # Clear improvised items on room change
    imp_cleared = [i.id for i in state.inventory if i.id.startswith("imp_")]
    for iid in imp_cleared:
        state.remove_item(iid)

    old_room_id = state.position
    state.position = new_room_id
    expired = _advance_turn(state)

    # ── 进入新房间：应用 RoomSnapshot 或 on_first_enter ──
    snapshot_applied = _apply_room_snapshot(world, state, new_room)
    first_enter = _apply_on_first_enter(world, state, new_room)

    # ── Phase 5：on_scene_enter reactive skills ──
    reactive_fired = _fire_reactive_skills("on_scene_enter", {
        "room_id": new_room_id, "room_tags": list(new_room.tags),
        "from_room": old_room_id,
    })

    result = {
        "ok": True,
        "moved_to": new_room_id,
        "moved_from": old_room_id,
        "improvised_cleared": imp_cleared,
        "expired_items": expired,
        "snapshot_written": old_room_id,
        "snapshot_applied": snapshot_applied,
        "on_first_enter_applied": first_enter,
        "scene": _room_snapshot(world, state),
        "inventory": _inventory_snapshot(state),
        "turn": state.turn,
    }
    if reactive_fired:
        result["reactive_fired"] = reactive_fired
    return result


def _write_room_snapshot(world: GameWorld, state: GameState, room) -> None:
    """离开房间时写入快照：保存当前房间的物体清单和相关 flags。"""
    objects_state = {}
    # Find all objects that belong to this room (including revealed ones)
    for oid in room.objects:
        obj = world.get_object(oid)
        inspected = bool(obj and obj.hidden_flag and state.flags.get(obj.hidden_flag))
        objects_state[oid] = {"taken": False, "inspected": inspected}

    # Collect flags related to this room's objects
    flags_here = []
    for oid in list(room.objects) + [oid for oid in objects_state]:
        obj = world.get_object(oid)
        if obj:
            if obj.hidden_flag and state.flags.get(obj.hidden_flag):
                flags_here.append(obj.hidden_flag)
            if f"revealed_{oid}" in state.flags and state.flags[f"revealed_{oid}"]:
                flags_here.append(f"revealed_{oid}")

    # Also capture unlock flags for this room's exits
    for d in room.exits:
        if f"exit_{d}_unlocked" in state.flags:
            flags_here.append(f"exit_{d}_unlocked")

    state.room_snapshots[room.id] = RoomSnapshot(
        room_id=room.id,
        last_visited_turn=state.turn,
        objects_state=objects_state,
        flags_set_here=list(set(flags_here)),
    )


def _apply_room_snapshot(world: GameWorld, state: GameState, room) -> bool:
    """进入房间时应用快照（如果存在）。"""
    if room.id not in state.room_snapshots:
        return False

    rs = state.room_snapshots[room.id]

    # Restore object presence: remove taken ones
    taken_ids = [oid for oid, os in rs.objects_state.items() if os.get("taken")]
    for oid in taken_ids:
        if oid in room.objects:
            room.objects.remove(oid)

    # Restore revealed objects that were in snapshot but not currently in room
    for oid in rs.objects_state:
        if oid not in room.objects and not rs.objects_state[oid].get("taken"):
            obj = world.get_object(oid)
            if obj:
                obj.hidden = False
                room.objects.append(oid)

    # Re-apply flags (don't overwrite existing)
    for flag in rs.flags_set_here:
        if flag not in state.flags:
            state.flags[flag] = True

    return True


def _apply_on_first_enter(world: GameWorld, state: GameState, room) -> bool:
    """如果房间首次进入且有 on_first_enter 钩子，执行。"""
    if room.id in state.room_snapshots:
        return False  # Already visited before
    if not room.on_first_enter:
        return False

    for action in room.on_first_enter:
        verb = action.get("verb", "")
        if verb == "reveal_objects":
            for oid in action.get("object_ids", []):
                obj = world.get_object(oid)
                if obj:
                    obj.hidden = False
                    if oid not in room.objects:
                        room.objects.append(oid)
        elif verb == "set_flags":
            for flag, val in action.get("flags", {}).items():
                state.flags[flag] = val
        elif verb == "add_clues":
            for clue_text in action.get("clues", []):
                state.add_clue(clue_text, tags=action.get("tags", []))

    return True


@mcp.tool()
def take_item(object_id: str) -> dict:
    """从场景中拾取物品放入背包。

    Args:
        object_id: 物体 ID
    """
    if err := _require_started():
        return err

    world, state = SESSION.world, SESSION.state
    room = world.get_room(state.position)

    if not room or object_id not in room.objects:
        return {"ok": False, "error": f"{object_id} 不在当前场景"}

    obj = world.get_object(object_id)
    if not obj:
        return {"ok": False, "error": f"未知物体 {object_id!r}"}

    if not obj.takable:
        return {"ok": False, "error": f"【{obj.name}】无法拾取"}

    if obj.hidden:
        return {"ok": False, "error": f"【{obj.name}】仍处于隐藏状态，无法拾取"}

    if state.has_item(object_id):
        return {"ok": False, "error": "已在背包中"}

    state.add_item(InventoryItem.from_object(obj))
    room.objects = [oid for oid in room.objects if oid != object_id]
    expired = _advance_turn(state)

    return {
        "ok": True,
        "picked_up": object_id,
        "name": obj.name,
        "scene": _room_snapshot(world, state),
        "inventory": _inventory_snapshot(state),
        "expired_items": expired,
        "turn": state.turn,
    }


@mcp.tool()
def add_improvised(items: list) -> dict:
    """即兴添加临时物品（经 7 关验证后入背包）。

    每回合最多 2 个，背包上限 4 个即兴物品。trace 类不入背包。

    Args:
        items: 物品列表，每个对象格式：
               { "id": "imp_xxx", "name": "...", "desc": "...",
                 "category": "fragment|consumable|trinket|tool|clue",
                 "size": "tiny|small|medium", "ttl": 1-5, "tags": [] }
    """
    if err := _require_started():
        return err

    state = SESSION.state
    accepted, reasons = _validate_improvised(items, state)

    added = []
    for imp in accepted:
        inv_item = imp.to_inventory_item()
        state.add_item(inv_item)
        added.append({"id": imp.id, "name": imp.name, "category": imp.category, "ttl": imp.ttl})

    return {
        "ok": True,
        "added": added,
        "rejected_reasons": reasons,
        "inventory": _inventory_snapshot(state),
    }


@mcp.tool()
def set_custom_attribute(
    scope: str,
    key: str,
    value: str,
    value_type: str = "text",
    label: str = "",
    note: str = "",
) -> dict:
    """添加或更新 GM 自定义属性。

    Args:
        scope: player 或 world。player 用于暴击率、恐惧值等玩家扩展属性；world 用于天象、潮汐等世界扩展属性。
        key: 稳定字段名，只允许字母、数字、下划线、连字符。
        value: 字段值。会按 value_type 解析。
        value_type: text / int / float / bool / json。
        label: 给 GM 看的显示名。留空则使用 key。
        note: 字段说明或叙事用途。
    """
    if err := _require_started():
        return err

    if scope not in {"player", "world"}:
        return {"ok": False, "error": "scope 必须是 player 或 world"}

    clean_key = key.strip()
    if not clean_key:
        return {"ok": False, "error": "key 不能为空"}
    if len(clean_key) > 48:
        return {"ok": False, "error": "key 不能超过 48 个字符"}
    if any(not (char.isalnum() or char in "_-") for char in clean_key):
        return {"ok": False, "error": "key 只允许字母、数字、下划线、连字符"}

    clean_value_type = value_type.strip().lower()
    parsed_value, parse_error = _parse_custom_value(value, clean_value_type)
    if parse_error:
        return {"ok": False, "error": parse_error}

    entry = {
        "label": label.strip() or clean_key,
        "value": parsed_value,
        "value_type": clean_value_type,
        "note": note.strip(),
    }
    attrs = SESSION.state.player_attrs if scope == "player" else SESSION.state.world_attrs
    attrs[clean_key] = entry

    return {
        "ok": True,
        "scope": scope,
        "key": clean_key,
        "attribute": entry,
        "state_context": _state_context(SESSION.state),
    }


@mcp.tool()
def remove_custom_attribute(scope: str, key: str) -> dict:
    """删除 GM 自定义属性。

    Args:
        scope: player 或 world。
        key: 要删除的字段名。
    """
    if err := _require_started():
        return err

    if scope not in {"player", "world"}:
        return {"ok": False, "error": "scope 必须是 player 或 world"}

    attrs = SESSION.state.player_attrs if scope == "player" else SESSION.state.world_attrs
    removed = attrs.pop(key, None)
    return {
        "ok": True,
        "scope": scope,
        "key": key,
        "removed": removed,
        "state_context": _state_context(SESSION.state),
    }


# ── §8 冷热分层辅助函数 ────────────────────────────────────────────


def _active_quest_tags(state: GameState) -> set:
    """收集当前 active quest 的 tags（从 known_facts + title 提取关键词）。"""
    tags = set()
    for q in state.quest_log:
        if q.stage not in ("closed", "failed", "completed"):
            tags.update(q.title.split("·"))
            for fact in q.known_facts:
                # Extract short keywords from facts
                for word in fact.replace("：", " ").replace("，", " ").split():
                    if len(word) >= 2:
                        tags.add(word)
    return tags


def _hot_cold_clues(state: GameState) -> dict:
    clues = state.clues
    if not clues:
        return {"clues": [], "clues_cold": 0}

    active_tags = _active_quest_tags(state)

    # Hot: recent 5 + tag match with active quest
    recent = sorted(clues, key=lambda c: c.turn, reverse=True)
    hot = []
    for i, c in enumerate(recent):
        if i < 5 or any(t in active_tags for t in c.tags):
            hot.append(c)

    hot_ids = {id(c) for c in hot}
    cold = [c for c in clues if id(c) not in hot_ids]

    cold_tags = list(set(t for c in cold for t in c.tags))[:20]

    return {
        "clues": _clues_snapshot(hot),
        "clues_cold": {"count": len(cold), "sample_tags": cold_tags},
    }


def _hot_cold_quests(state: GameState) -> dict:
    hot = []
    cold_summaries = []
    for q in state.quest_log:
        if q.stage in ("closed", "failed", "completed"):
            cold_summaries.append({"id": q.id, "title": q.title, "stage": q.stage, "summary": q.summary})
        else:
            hot.append({
                "id": q.id, "title": q.title, "stage": q.stage,
                "summary": q.summary, "deadline": q.deadline,
                "known_facts": q.known_facts, "unresolved": q.unresolved,
            })

    return {
        "quest_log": hot,
        "quest_log_cold": cold_summaries[:20],
    }


def _hot_cold_dialogues(state: GameState) -> dict:
    dialogues = state.dialogue_log
    if not dialogues:
        return {"dialogue_log": [], "dialogue_cold": 0}

    recent = sorted(dialogues, key=lambda d: d.turn, reverse=True)
    hot = recent[:3]
    cold = recent[3:]

    cold_npcs = list(set(d.npc_id for d in cold))
    cold_tags = list(set(t for d in cold for t in d.tags))[:20]

    return {
        "dialogue_log": _dialogue_log_snapshot(hot),
        "dialogue_cold": {"count": len(cold), "npcs": cold_npcs, "sample_tags": cold_tags},
    }


def _hot_cold_rooms(state: GameState, world: GameWorld) -> dict:
    room = world.get_room(state.position)
    current_room_id = state.position
    prev_room_id = ""
    # Find previous room from snapshots (most recent non-current)
    if state.room_snapshots:
        sorted_rooms = sorted(
            state.room_snapshots.values(),
            key=lambda rs: rs.last_visited_turn, reverse=True
        )
        prev_room_id = sorted_rooms[0].room_id

    # Hot: current room + previous room snapshot
    hot_snapshots = {}
    if current_room_id in state.room_snapshots:
        rs = state.room_snapshots[current_room_id]
        hot_snapshots[current_room_id] = {
            "room_id": rs.room_id, "last_visited_turn": rs.last_visited_turn,
            "objects_state": rs.objects_state, "flags_set_here": rs.flags_set_here,
        }
    if prev_room_id and prev_room_id != current_room_id and prev_room_id in state.room_snapshots:
        rs = state.room_snapshots[prev_room_id]
        hot_snapshots[prev_room_id] = {
            "room_id": rs.room_id, "last_visited_turn": rs.last_visited_turn,
            "objects_state": rs.objects_state, "flags_set_here": rs.flags_set_here,
        }

    # Cold: other rooms
    rooms_visited = []
    for rid, rs in state.room_snapshots.items():
        if rid not in hot_snapshots:
            r = world.get_room(rid)
            rooms_visited.append({
                "id": rid, "name": r.name if r else rid, "last_turn": rs.last_visited_turn,
            })

    return {
        "room_snapshots": hot_snapshots if hot_snapshots else {},
        "rooms_visited": rooms_visited,
    }


@mcp.tool()
def get_state() -> dict:
    """查看完整游戏状态（位置、背包、线索、标记、回合数、最近骰子）。

    热区直接展开；冷区仅给计数索引，大数量数据需要通过 recall 工具调取。
    """
    if err := _require_started():
        return err

    state = SESSION.state
    world = SESSION.world
    room = world.get_room(state.position)

    result = {
        "ok": True,
        "world": SESSION.world_name,
        "turn": state.turn,
        "position": state.position,
        "room_name": room.name if room else "?",
        "inventory": _inventory_snapshot(state),
        **_hot_cold_clues(state),
        **_hot_cold_quests(state),
        **_hot_cold_dialogues(state),
        **_hot_cold_rooms(state, world),
        "flags": state.flags,
        "alertness": state.alertness,
        "buffs": _buffs_snapshot(state),
        "state_context": _state_context(state),
        "recent_rolls": SESSION.rolls_log[-5:],
        "hud": _build_hud(state, world),
    }
    if SESSION.encounter:
        result["encounter"] = _encounter_snapshot()
    return result


def _match_topic(text: str, tags: List[str], topic: str) -> bool:
    """Check if topic keyword matches text or any tag."""
    t = topic.strip().lower()
    if not t:
        return False
    if t in text.lower():
        return True
    for tag in tags:
        if t in tag.lower():
            return True
    return False


@mcp.tool()
def recall(topic: str, kind: str = "any", limit: int = 5) -> dict:
    """从冷区记忆中按关键词检索线索/任务/对话/房间快照。

    Args:
        topic: 关键词，匹配 text + tags
        kind: 检索范围 — clue / quest / dialogue / room / any（默认）
        limit: 返回条数上限（默认 5）
    """
    if err := _require_started():
        return err

    state = SESSION.state
    world = SESSION.world
    limit = max(1, min(limit, 20))
    results = []

    # Search clues
    if kind in ("clue", "any"):
        for c in state.clues:
            if _match_topic(c.text, c.tags, topic):
                results.append({
                    "kind": "clue",
                    "text": c.text,
                    "tags": c.tags,
                    "turn": c.turn,
                })

    # Search quests
    if kind in ("quest", "any"):
        for q in state.quest_log:
            combined = q.title + " " + q.summary + " " + " ".join(q.known_facts) + " " + " ".join(q.unresolved)
            if _match_topic(combined, [], topic):
                results.append({
                    "kind": "quest",
                    "id": q.id,
                    "title": q.title,
                    "stage": q.stage,
                    "summary": q.summary,
                    "known_facts": q.known_facts,
                    "unresolved": q.unresolved,
                })

    # Search dialogues
    if kind in ("dialogue", "any"):
        for d in state.dialogue_log:
            if _match_topic(d.summary, d.tags, topic) or _match_topic(d.npc_id, [], topic):
                results.append({
                    "kind": "dialogue",
                    "turn": d.turn,
                    "npc_id": d.npc_id,
                    "summary": d.summary,
                    "tags": d.tags,
                })

    # Search room snapshots
    if kind in ("room", "any"):
        for rid, rs in state.room_snapshots.items():
            r = world.get_room(rid)
            room_name = r.name if r else rid
            room_text = f"{rid} {room_name} {' '.join(rs.flags_set_here)}"
            if _match_topic(room_text, [], topic):
                results.append({
                    "kind": "room",
                    "room_id": rid,
                    "room_name": room_name,
                    "last_visited_turn": rs.last_visited_turn,
                    "flags_set_here": rs.flags_set_here,
                    "objects_state_keys": list(rs.objects_state.keys()),
                })

    # Limit results and deduplicate by text for clues, by id for others
    seen = set()
    deduped = []
    for r in results:
        key = r.get("text") or r.get("id") or r.get("room_id") or str(r)
        if key not in seen:
            seen.add(key)
            deduped.append(r)
        if len(deduped) >= limit:
            break

    return {
        "ok": True,
        "topic": topic,
        "kind": kind,
        "total_matches": len(results),
        "limit": limit,
        "results": deduped[:limit],
    }


@mcp.tool()
def log_dialogue(npc_id: str, summary: str, tags: list = None) -> dict:
    """记录 NPC 对话摘要到 dialogue_log。

    Codex 在每场 NPC 对话结束后调用，写一句话摘要，不下原文。

    Args:
        npc_id: NPC 的 object_id（如 "dwarf_bartender"）
        summary: 一句话对话摘要
        tags: 可选标签列表（如 ["码头","走私"]）
    """
    if err := _require_started():
        return err

    state = SESSION.state
    tags = tags or []

    entry = DialogueEntry(
        turn=state.turn,
        npc_id=npc_id,
        summary=summary,
        tags=[t for t in tags if isinstance(t, str)],
    )
    state.dialogue_log.append(entry)

    # Mark older entries as cold (keep last 3 hot)
    recent = sorted(state.dialogue_log, key=lambda d: d.turn, reverse=True)
    for d in recent[3:]:
        d.cold = True

    return {
        "ok": True,
        "npc_id": npc_id,
        "turn": state.turn,
        "dialogue_log_count": len(state.dialogue_log),
    }


@mcp.tool()
def add_clue(text: str, tags: list = None) -> dict:
    """发现新线索时调用，写入结构化 Clue 到线索列表。

    Args:
        text: 线索文本
        tags: 可选标签（如 ["码头","委托人"]）
    """
    if err := _require_started():
        return err

    state = SESSION.state
    tags = tags or []

    state.add_clue(text, tags=[t for t in tags if isinstance(t, str)])

    # Mark older clues as cold (keep last 5 hot)
    recent = sorted(state.clues, key=lambda c: c.turn, reverse=True)
    for c in recent[5:]:
        c.cold = True

    return {
        "ok": True,
        "text": text,
        "tags": tags,
        "turn": state.turn,
        "clues_count": len(state.clues),
    }


@mcp.tool()
def update_quest(
    quest_id: str,
    stage: str = "",
    known_facts: list = None,
    unresolved: list = None,
) -> dict:
    """推进任务状态。Codex 在任务有进展时调用。

    Args:
        quest_id: 任务 ID（如 "assassination_contract"）
        stage: 新阶段（如 "investigating"），空字符串表示不修改
        known_facts: 新增已知事实列表
        unresolved: 新未解问题列表（替换旧的）
    """
    if err := _require_started():
        return err

    state = SESSION.state
    known_facts = known_facts or []
    unresolved = unresolved or []

    target = None
    for q in state.quest_log:
        if q.id == quest_id:
            target = q
            break

    if not target:
        return {"ok": False, "error": f"未找到任务 {quest_id!r}"}

    if stage:
        target.stage = stage
    for fact in known_facts:
        if isinstance(fact, str) and fact not in target.known_facts:
            target.known_facts.append(fact)
    if unresolved:
        target.unresolved = [u for u in unresolved if isinstance(u, str)]

    return {
        "ok": True,
        "quest_id": quest_id,
        "stage": target.stage,
        "known_facts": target.known_facts,
        "unresolved": target.unresolved,
    }


@mcp.tool()
def gm_set_flag(flag: str, value: bool = True, unlock_exit: str = "") -> dict:
    """GM 裁定权：置一个世界 flag，可选解锁当前房间的一个出口。

    用途——玩家用了 content 没预设 affordance 的**创意解法**（如"吹口哨引开守卫"
    "贿赂哨兵""从屋顶绕进去"），而你判断这合理且达成了某个机制目标时，用此工具
    把结果落到引擎，让世界状态真正认可它（locked_exits 会更新、flag 进存档）。

    这是"算得清 × 玩得开"的接缝：不强迫玩家套预设动作，但创意解法的后果仍走工具、
    可追溯、不脑补。**别滥用**——它是给"预设之外但合理"的解法兜底，不是绕过正常 affordance/检定的捷径。

    Args:
        flag:        要置的 flag 名（如 "guard_post_cleared"）
        value:       置 true 还是 false（默认 true）
        unlock_exit: 可选，同时解锁当前房间的这个方向出口（如 "east"）
    """
    if err := _require_started():
        return err

    world, state = SESSION.world, SESSION.state
    state.flags[flag] = bool(value)
    result = {"ok": True, "flag": flag, "value": bool(value)}

    if unlock_exit:
        room = world.get_room(state.position)
        if room and unlock_exit in room.locked_exits:
            del room.locked_exits[unlock_exit]
            result["unlocked_exit"] = unlock_exit
        elif room and unlock_exit in room.exits:
            result["unlock_note"] = f"出口 {unlock_exit} 本就未锁"
        else:
            result["unlock_note"] = f"当前房间没有 {unlock_exit} 方向出口"

    result["hud"] = _build_hud(state, world)
    return result


@mcp.tool()
def save_game(slot: str = "default") -> dict:
    """将当前游戏状态存档到文件。

    Args:
        slot: 存档槽名称（字母数字，默认 "default"）
    """
    if err := _require_started():
        return err

    # Sanitize slot name
    safe_slot = "".join(c for c in slot if c.isalnum() or c in "-_")[:32] or "default"
    path = SAVE_DIR / f"{safe_slot}.json"

    state = SESSION.state
    data = {
        "world": SESSION.world_name,
        "position": state.position,
        "inventory": [
            {
                "id": i.id,
                "name": i.name,
                "desc": i.desc,
                "tags": i.tags,
                "ttl": i.ttl,
                "kind": i.kind,
                "named_tags": i.named_tags,
                "modifiers": i.modifiers,
            }
            for i in state.inventory
        ],
        "flags": state.flags,
        "alertness": state.alertness,
        "clues": _clues_snapshot(state.clues),
        "turn": state.turn,
        "profile": _profile_snapshot(state.profile),
        "vitals": _vitals_snapshot(state.vitals),
        "conditions": state.conditions,
        "relationships": state.relationships,
        "world_time": _world_time_snapshot(state.world_time),
        "quest_log": _quest_log_snapshot(state.quest_log),
        "dialogue_log": _dialogue_log_snapshot(state.dialogue_log),
        "room_snapshots": {
            rid: {
                "room_id": rs.room_id,
                "last_visited_turn": rs.last_visited_turn,
                "objects_state": rs.objects_state,
                "flags_set_here": rs.flags_set_here,
            }
            for rid, rs in state.room_snapshots.items()
        },
        "buffs": [
            {
                "id": b.id, "name": b.name, "desc": b.desc,
                "polarity": b.polarity, "source_kind": b.source_kind,
                "source_id": b.source_id, "tags": b.tags,
                "stacks": b.stacks, "max_stacks": b.max_stacks,
                "ticks": {t: {"emit_modifiers": [
                    {"id": m.id, "source_kind": m.source_kind, "source_id": m.source_id,
                     "target": m.target, "selector": m.selector, "op": m.op,
                     "value": m.value, "reason": m.reason, "visible": m.visible}
                    for m in bt.emit_modifiers
                ]} for t, bt in b.ticks.items()},
                "expire_on": b.expire_on, "visible": b.visible,
            }
            for b in state.buffs
        ],
        "skills": [_serialize_skill(s) for s in state.skills],
        "player_attrs": state.player_attrs,
        "world_attrs": state.world_attrs,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "slot": safe_slot, "path": str(path), "turn": state.turn}


@mcp.tool()
def load_game(slot: str = "default") -> dict:
    """从文件载入存档。

    Args:
        slot: 存档槽名称（默认 "default"）
    """
    global SESSION

    safe_slot = "".join(c for c in slot if c.isalnum() or c in "-_")[:32] or "default"
    path = SAVE_DIR / f"{safe_slot}.json"

    if not path.exists():
        return {"ok": False, "error": f"存档 {safe_slot!r} 不存在"}

    data = json.loads(path.read_text(encoding="utf-8"))
    world_name = data.get("world", "yanan")

    if world_name not in WORLDS:
        return {"ok": False, "error": f"存档中的世界 {world_name!r} 未安装"}

    module = WORLDS[world_name]
    new_world = GameWorld(content_module=module)

    inventory = [
        InventoryItem(
            id=i["id"], name=i["name"], desc=i.get("desc", ""),
            tags=i.get("tags", []), ttl=i.get("ttl", -1),
            kind=i.get("kind", "item"),
            named_tags=i.get("named_tags", []),
            modifiers=i.get("modifiers", []),
        )
        for i in data.get("inventory", [])
    ]
    # Backward compat: clues may be old-style plain strings or new-style dicts
    raw_clues = data.get("clues", [])
    clues = []
    for c in raw_clues:
        if isinstance(c, str):
            clues.append(Clue(text=c, tags=[], turn=data.get("turn", 0)))
        elif isinstance(c, dict):
            clues.append(Clue(
                text=c.get("text", ""), tags=c.get("tags", []),
                turn=c.get("turn", 0), cold=c.get("cold", False),
            ))

    raw_dialogues = data.get("dialogue_log", [])
    dialogue_log = [
        DialogueEntry(
            turn=d.get("turn", 0), npc_id=d.get("npc_id", ""),
            summary=d.get("summary", ""), tags=d.get("tags", []),
            cold=d.get("cold", False),
        )
        for d in raw_dialogues
    ]

    raw_snapshots = data.get("room_snapshots", {})
    room_snapshots = {
        rid: RoomSnapshot(
            room_id=rs.get("room_id", rid),
            last_visited_turn=rs.get("last_visited_turn", 0),
            objects_state=rs.get("objects_state", {}),
            flags_set_here=rs.get("flags_set_here", []),
        )
        for rid, rs in raw_snapshots.items()
    }

    new_state = GameState(
        position=data["position"],
        inventory=inventory,
        flags=data.get("flags", {}),
        alertness=data.get("alertness", 0),
        clues=clues,
        turn=data.get("turn", 0),
        profile=ActorProfile(**data.get("profile", {})),
        vitals=VitalStats(**data.get("vitals", {})),
        conditions=data.get("conditions", []),
        relationships=data.get("relationships", {}),
        world_time=WorldTime(**data.get("world_time", {})),
        quest_log=[
            QuestEntry(
                id=q["id"],
                title=q["title"],
                stage=q["stage"],
                summary=q.get("summary", ""),
                deadline=q.get("deadline", ""),
                known_facts=q.get("known_facts", []),
                unresolved=q.get("unresolved", []),
            )
            for q in data.get("quest_log", [])
        ],
        dialogue_log=dialogue_log,
        room_snapshots=room_snapshots,
        buffs=_load_buffs(data.get("buffs", [])),
        skills=_load_skills(data.get("skills", [])),
        player_attrs=_clean_custom_attributes(data.get("player_attrs", {})),
        world_attrs=_clean_custom_attributes(data.get("world_attrs", {})),
    )

    SESSION = Session(world_name=world_name, world=new_world, state=new_state)
    scene = _room_snapshot(new_world, new_state)

    return {
        "ok": True,
        "slot": safe_slot,
        "world": world_name,
        "turn": new_state.turn,
        "scene": scene,
        "inventory": _inventory_snapshot(new_state),
        "clues": _clues_snapshot(new_state.clues),
        "state_context": _state_context(new_state),
        "hud": _build_hud(new_state, new_world),
    }


if __name__ == "__main__":
    mcp.run()
