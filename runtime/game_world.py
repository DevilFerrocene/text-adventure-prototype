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
            problems += self._validate_grid(rid, room)

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

    def _validate_grid(self, rid: str, room) -> List[str]:
        """二维棋盘校验：坐标越界 / 实体叠格 / 引用错 / 进门落点不可站 / 实体走不到。
        把作者手摆格子时的常见错误（把东西墙进死角、出口够不着）在 --check 期就抓出来。"""
        grid = getattr(room, "grid", None)
        if not grid:
            return []
        problems: List[str] = []
        W, H = grid.width, grid.height

        def inb(c):
            return 0 <= c[0] < W and 0 <= c[1] < H

        # 1. 越界 + 引用完整性
        ambient_names = {e.split(":", 1)[0].strip() for e in (getattr(room, "ambient", []) or [])}
        room_obj_ids = set(getattr(room, "objects", []) or [])
        for oid, c in grid.objects.items():
            if not inb(c):
                problems.append(f"房间 {rid!r} 棋盘：物体 {oid!r} 坐标 {tuple(c)} 越界（{W}×{H}）")
            if oid not in room_obj_ids:
                problems.append(f"房间 {rid!r} 棋盘：钉了物体 {oid!r}，但它不在 room.objects 里")
        for nm, c in grid.ambient.items():
            if not inb(c):
                problems.append(f"房间 {rid!r} 棋盘：陈设 {nm!r} 坐标 {tuple(c)} 越界（{W}×{H}）")
            if nm not in ambient_names:
                problems.append(f"房间 {rid!r} 棋盘：钉了陈设 {nm!r}，但它不在 room.ambient 里")
        for d, c in grid.exits.items():
            if not inb(c):
                problems.append(f"房间 {rid!r} 棋盘：出口 {d!r} 坐标 {tuple(c)} 越界（{W}×{H}）")
            if d not in (getattr(room, "exits", {}) or {}):
                problems.append(f"房间 {rid!r} 棋盘：钉了出口 {d!r}，但它不在 room.exits 里")
        for nm, c in grid.landmarks.items():
            if not inb(c):
                problems.append(f"房间 {rid!r} 棋盘：地标 {nm!r} 坐标 {tuple(c)} 越界（{W}×{H}）")
        for c in grid.blocked:
            if not inb(c):
                problems.append(f"房间 {rid!r} 棋盘：障碍格 {tuple(c)} 越界（{W}×{H}）")
        # 探索点：越界 + hint 非空 + payload.kind 合法 + 伏击敌人引用存在
        VALID_POI_KINDS = {"loot", "clue", "event", "trap", "ambush"}
        for p in (getattr(grid, "pois", []) or []):
            if not inb(p.cell):
                problems.append(f"房间 {rid!r} 棋盘：探索点 {p.id!r} 坐标 {tuple(p.cell)} 越界（{W}×{H}）")
            if not getattr(p, "hint", ""):
                problems.append(f"房间 {rid!r} 棋盘：探索点 {p.id!r} 缺 hint（明面感官提示，不能空）")
            pkind = (p.payload or {}).get("kind")
            if pkind not in VALID_POI_KINDS:
                problems.append(f"房间 {rid!r} 棋盘：探索点 {p.id!r} 的 payload.kind={pkind!r} 非法（须属 {sorted(VALID_POI_KINDS)}）")
            if pkind == "ambush":
                for e in (p.payload.get("enemies", []) or []):
                    if isinstance(e, str) and e not in self.enemies:
                        problems.append(f"房间 {rid!r} 棋盘：探索点 {p.id!r} 伏击引用了不存在的敌人 {e!r}")

        # 2. 叠格：物体/陈设/地标/出口/探索点互不重叠
        placed = {}  # cell -> 标签
        for label, mapping in (("物体", grid.objects), ("陈设", grid.ambient),
                               ("出口", grid.exits), ("地标", grid.landmarks)):
            for key, c in mapping.items():
                c = tuple(c)
                if c in placed:
                    problems.append(f"房间 {rid!r} 棋盘：{c} 上叠了两样（{placed[c]} 与 {label} {key!r}）")
                else:
                    placed[c] = f"{label} {key!r}"
        for p in (getattr(grid, "pois", []) or []):
            c = tuple(p.cell)
            if c in placed:
                problems.append(f"房间 {rid!r} 棋盘：{c} 上叠了两样（{placed[c]} 与 探索点 {p.id!r}）")
            else:
                placed[c] = f"探索点 {p.id!r}"

        if problems:        # 坐标都没摆对，连通性检查就别跑了（噪声）
            return problems

        # 3. 连通性：进门落点可站，且每个实体都走得到
        occupied = {tuple(c) for c in grid.objects.values()} | {tuple(c) for c in grid.ambient.values()}
        blocked = {tuple(c) for c in grid.blocked}

        def standable(c):
            return inb(c) and tuple(c) not in blocked and tuple(c) not in occupied

        entry = tuple(grid.entry)
        if not standable(entry):
            problems.append(f"房间 {rid!r} 棋盘：进门落点 entry={entry} 不可站（被占/障碍/越界）")
            return problems
        # BFS 可达集
        seen, frontier = {entry}, [entry]
        while frontier:
            nxt = []
            for cx, cy in frontier:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx or dy:
                            n = (cx + dx, cy + dy)
                            if n not in seen and standable(n):
                                seen.add(n)
                                nxt.append(n)
            frontier = nxt
        # 物体/陈设：至少一个相邻可站格在可达集里（站旁边交互）
        for label, mapping in (("物体", grid.objects), ("陈设", grid.ambient)):
            for key, c in mapping.items():
                cx, cy = tuple(c)
                neigh = [(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                         if (dx or dy)]
                if not any(standable(n) and n in seen for n in neigh):
                    problems.append(f"房间 {rid!r} 棋盘：{label} {key!r}@{tuple(c)} 四周无可达落脚格——被墙死了，玩家走不到")
        # 出口/地标：本格须可站且可达
        for label, mapping in (("出口", grid.exits), ("地标", grid.landmarks)):
            for key, c in mapping.items():
                if tuple(c) not in seen:
                    problems.append(f"房间 {rid!r} 棋盘：{label} {key!r}@{tuple(c)} 从进门处走不到（不可站或被隔断）")
        # 探索点：要走上去揭示，本格须可站且可达
        for p in (getattr(grid, "pois", []) or []):
            if tuple(p.cell) not in seen:
                problems.append(f"房间 {rid!r} 棋盘：探索点 {p.id!r}@{tuple(p.cell)} 从进门处走不到（不可站或被隔断）")
        return problems
