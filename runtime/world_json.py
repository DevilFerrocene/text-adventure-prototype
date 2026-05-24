"""JSON 世界格式 ⇄ GameWorld。

世界本来是 Python 模块（content/aincrad/*.py，靠 register() 组装）。WebUI 世界编辑器
需要把世界当【数据】增删改，于是有了这一层：一个 JSON 文件就是一个完整世界，
load_world_from_json 把它还原成 GameWorld 的 dataclass 们，world_to_json 反向导出。

核心是 _from_dict：顺着 dataclass 的类型注解【递归】构造嵌套结构——tuple 坐标
（JSON 只有数组）、Dict[verb,Affordance]、List[Modifier]、Optional[ActiveSkill]…
都按注解自动还原，不用为每个类手写解析。新增字段只要进 dataclass，这里零改动。
"""

from dataclasses import fields, is_dataclass, asdict
from typing import get_type_hints, get_origin, get_args, Union
import types as _types

from core.types import (
    WorldCanon, RuleBook, EnemyTemplate, Skill, Room, GameObject, GameState,
)
from runtime.game_world import GameWorld


_NONE = type(None)


def _build(typ, value):
    """按类型注解 typ 把 JSON 值 value 还原成对应运行期对象。"""
    if value is None:
        return None

    origin = get_origin(typ)

    # Optional[X] / Union[...]：剥掉 NoneType，取第一个非空分支
    if origin is Union or isinstance(typ, getattr(_types, "UnionType", ())):
        args = [a for a in get_args(typ) if a is not _NONE]
        if len(args) == 1:
            return _build(args[0], value)
        # 多分支 union（罕见）：dict→当 dataclass 试，否则原样
        for a in args:
            if is_dataclass(a) and isinstance(value, dict):
                return _from_dict(a, value)
        return value

    if is_dataclass(typ):
        return _from_dict(typ, value)

    if origin in (list, set, frozenset):
        args = get_args(typ)
        if not args:
            return list(value)
        return [_build(args[0], v) for v in value]

    if origin is tuple:
        args = get_args(typ)
        if not args:
            return tuple(value)
        if len(args) == 2 and args[1] is Ellipsis:      # Tuple[int, ...] 变长
            return tuple(_build(args[0], v) for v in value)
        return tuple(_build(a, v) for a, v in zip(args, value))

    if origin is dict:
        args = get_args(typ)
        if len(args) == 2:
            return {k: _build(args[1], v) for k, v in value.items()}
        return dict(value)

    # 基础类型 / Any / 无参 dict|list：原样返回
    return value


def _from_dict(cls, data: dict):
    """用 data 里的键构造 dataclass cls；未知键忽略（向前兼容）。"""
    if not isinstance(data, dict):
        raise TypeError(f"{cls.__name__} 需要 dict，得到 {type(data).__name__}")
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = _build(hints.get(f.name, f.type), data[f.name])
    return cls(**kwargs)


# ── 加载：JSON → GameWorld ────────────────────────────────────────

def populate_world_from_json(world: GameWorld, data: dict):
    """把 JSON 世界数据灌进一个已存在的 GameWorld（就地）。供 JsonWorld.register 用。"""
    if data.get("canon"):
        world.set_world_canon(_from_dict(WorldCanon, data["canon"]))
    if data.get("rulebook"):
        world.rulebook = _from_dict(RuleBook, data["rulebook"])

    for eid, ed in (data.get("enemies") or {}).items():
        ed = {**ed, "id": ed.get("id", eid)}
        world.register_enemies({eid: _from_dict(EnemyTemplate, ed)})

    for sid, sd in (data.get("skills") or {}).items():
        sd = {**sd, "id": sd.get("id", sid)}
        world.register_skills({sid: _from_dict(Skill, sd)})

    for rid, rd in (data.get("rooms") or {}).items():
        rd = {**rd, "id": rd.get("id", rid)}
        world.add_room(_from_dict(Room, rd))

    for oid, od in (data.get("objects") or {}).items():
        od = {**od, "id": od.get("id", oid)}
        world.add_object(_from_dict(GameObject, od))

    if data.get("initial_state"):
        world.initial_state = _from_dict(GameState, data["initial_state"])


def load_world_from_json(data: dict) -> GameWorld:
    """JSON 世界数据 → 全新 GameWorld。"""
    world = GameWorld()
    populate_world_from_json(world, data)
    return world


class JsonWorld:
    """把一份 JSON 世界数据包装成 WORLDS 注册表认得的"内容模块"——
    暴露 register(world) 接口，使 GameWorld(content_module=JsonWorld(...)) 照常工作。"""

    def __init__(self, data: dict, name: str = ""):
        self.data = data
        self.name = name or data.get("name", "")

    def register(self, world: GameWorld):
        populate_world_from_json(world, self.data)


# ── 导出：GameWorld → JSON ────────────────────────────────────────

def world_to_json(world: GameWorld, name: str = "") -> dict:
    """把 GameWorld 导成 JSON 可序列化的 dict（tuple 会在 json.dumps 时成数组，
    加载时按类型注解还原回 tuple）。编辑器用它把 Python 世界导成可编辑的 JSON。"""
    out: dict = {"name": name or getattr(world, "name", "")}
    if world.world_canon:
        out["canon"] = asdict(world.world_canon)
    if world.rulebook:
        out["rulebook"] = asdict(world.rulebook)
    out["enemies"] = {eid: asdict(e) for eid, e in world.enemies.items()}
    out["skills"] = {sid: asdict(s) for sid, s in world.skills.items()}
    out["rooms"] = {rid: asdict(r) for rid, r in world.rooms.items()}
    out["objects"] = {oid: asdict(o) for oid, o in world.objects.items()}
    if world.initial_state:
        out["initial_state"] = asdict(world.initial_state)
    return out
