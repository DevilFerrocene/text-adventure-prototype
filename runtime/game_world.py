"""Game world: manages rooms, objects, item interactions, world canon."""

from typing import Dict, List, Optional, Tuple
from core.types import Room, GameObject, Affordance, GameState, WorldCanon, InventoryItem, EnemyTemplate, Skill, RuleBook


class GameWorld:
    def __init__(self, content_module=None):
        self.rooms: Dict[str, Room] = {}
        self.objects: Dict[str, GameObject] = {}
        self.enemies: Dict[str, EnemyTemplate] = {}
        self.skills: Dict[str, Skill] = {}
        self.initial_state: Optional[GameState] = None
        self.world_canon: Optional[WorldCanon] = None
        self.rulebook: RuleBook = RuleBook()              # §11：默认 RuleBook，content 可覆盖
        if content_module:
            content_module.register(self)

    def add_room(self, room: Room):
        self.rooms[room.id] = room

    def add_object(self, obj: GameObject):
        self.objects[obj.id] = obj

    def register_enemies(self, enemies: dict):
        """注册敌人模板表。key = enemy_id, value = EnemyTemplate。"""
        self.enemies.update(enemies)

    def get_enemy(self, enemy_id: str) -> Optional[EnemyTemplate]:
        return self.enemies.get(enemy_id)

    def register_skills(self, skills: dict):
        """注册技能模板表。key = skill_id, value = Skill。"""
        self.skills.update(skills)

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        return self.skills.get(skill_id)

    def add_affordance(self, object_id: str, affordance: Affordance):
        """Register an affordance on an existing object."""
        obj = self.objects.get(object_id)
        if obj:
            obj.affordances[affordance.verb] = affordance

    def set_world_canon(self, canon: WorldCanon):
        self.world_canon = canon

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id)

    def get_object(self, object_id: str) -> Optional[GameObject]:
        return self.objects.get(object_id)

    def get_affordance(self, object_id: str, verb: str) -> Optional[Affordance]:
        """Look up an affordance by object ID and verb."""
        obj = self.objects.get(object_id)
        if obj:
            return obj.affordances.get(verb)
        return None

    def get_callable_affordances(
        self, object_id: str, state: GameState
    ) -> List[Tuple[str, Affordance]]:
        """Return affordances on this object whose requirements are met."""
        obj = self.objects.get(object_id)
        if not obj:
            return []
        result = []
        for verb, aff in obj.affordances.items():
            if aff.requires_item and not state.has_item(aff.requires_item):
                continue
            if aff.requires_flag and not state.flags.get(aff.requires_flag):
                continue
            result.append((verb, aff))
        return result

    def make_inventory_item(self, item_id: str) -> Optional[InventoryItem]:
        obj = self.get_object(item_id)
        if obj:
            return InventoryItem.from_object(obj)
        return None

    def get_world_canon_prompt(self) -> str:
        if self.world_canon:
            return self.world_canon.to_prompt_block()
        return ""

    def validate(self) -> List[str]:
        """引用完整性校验：返回问题列表（空=干净）。

        把"作者期的字符串 id 拼写错"在加载/测试期就抓出来——而不是等玩到那个房间、
        触发那个 affordance 才静默失效或运行时崩。检查：房间出口目标、锁定出口、房间
        物体/敌人、物体 reveals_objects、on_destroyed 揭示、affordance 的 reveals_objects/
        learn_skills/start_combat.canon、初始位置。（loot 是即时字符串、requires_item 可
        能来自背包/即兴，故不在此校验，避免误报。）
        """
        problems: List[str] = []
        rooms, objs, enemies, skills = self.rooms, self.objects, self.enemies, self.skills

        def _check_objs(ids, where):
            for oid in (ids or []):
                if oid not in objs:
                    problems.append(f"{where}：引用了不存在的物体 {oid!r}")

        for rid, room in rooms.items():
            for d, target in (getattr(room, "exits", {}) or {}).items():
                if target and target not in rooms:       # "" = 故意预留的未建出口，跳过
                    problems.append(f"房间 {rid!r} 出口 {d!r} 指向不存在的房间 {target!r}")
            for d in (getattr(room, "locked_exits", {}) or {}):
                if d not in (getattr(room, "exits", {}) or {}):
                    problems.append(f"房间 {rid!r} 锁定了不存在的出口 {d!r}（不在 exits 里，永远走不到）")
            _check_objs(getattr(room, "objects", []), f"房间 {rid!r} 的 objects")
            for eid in (getattr(room, "enemies", []) or []):
                if eid not in enemies:
                    problems.append(f"房间 {rid!r} 引用了不存在的敌人 {eid!r}")

        for oid, obj in objs.items():
            _check_objs(getattr(obj, "reveals_objects", []), f"物体 {oid!r} 的 reveals_objects")
            for step in (getattr(obj, "on_destroyed", []) or []):
                if isinstance(step, dict):
                    _check_objs(step.get("reveals_objects", []),
                                f"物体 {oid!r} 的 on_destroyed.reveals_objects")
            for verb, aff in (getattr(obj, "affordances", {}) or {}).items():
                eff = getattr(aff, "effect", {}) or {}
                _check_objs(eff.get("reveals_objects", []),
                            f"物体 {oid!r}.{verb} 的 reveals_objects")
                for sid in (eff.get("learn_skills", []) or []):
                    if sid not in skills:
                        problems.append(f"物体 {oid!r}.{verb} 教授了不存在的技能 {sid!r}")
                sc = eff.get("start_combat")
                if isinstance(sc, dict):
                    for cid in (sc.get("canon", []) or []):
                        if cid not in enemies:
                            problems.append(f"物体 {oid!r}.{verb} 的 start_combat 引用了不存在的敌人 {cid!r}")

        if self.initial_state and self.initial_state.position not in rooms:
            problems.append(f"初始位置 {self.initial_state.position!r} 不是已注册房间")

        return problems
