"""Game world: manages rooms, objects, item interactions, world canon."""

from typing import Dict, List, Optional, Tuple
from core.types import Room, GameObject, Affordance, GameState, WorldCanon, InventoryItem, EnemyTemplate, Skill


class GameWorld:
    def __init__(self, content_module=None):
        self.rooms: Dict[str, Room] = {}
        self.objects: Dict[str, GameObject] = {}
        self.enemies: Dict[str, EnemyTemplate] = {}
        self.skills: Dict[str, Skill] = {}
        self.initial_state: Optional[GameState] = None
        self.world_canon: Optional[WorldCanon] = None
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
