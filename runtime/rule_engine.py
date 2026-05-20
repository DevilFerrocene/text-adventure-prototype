"""RuleEngine — affordance executor + improvised item manager."""

from typing import List

from core.types import (
    GameState, InventoryItem, ImprovisedItem,
    IMPROVISED_CATEGORIES, IMPROVISED_SIZES, IMPROVISED_MAX_TTL,
    MAX_IMPROVISED_IN_INVENTORY, MAX_IMPROVISED_PER_TURN, IMPROVISED_DEFAULT_TTL,
)
from runtime.game_world import GameWorld


class RuleEngine:
    def __init__(self, world: GameWorld):
        self.world = world

    def apply(self, method_call: dict, state: GameState,
              improvised_raw: List[dict] = None) -> dict:
        """Execute method_call, apply improvised items, return summary."""
        applied = {
            "verb": method_call.get("verb", "none"),
            "object_id": method_call.get("object_id"),
            "target_id": method_call.get("target_id"),
            "clues_added": [],
            "items_added": [],
            "items_removed": [],
            "flags_set": {},
            "moved_to": None,
            "improvised_added": [],
        }

        verb = method_call.get("verb", "none")
        object_id = method_call.get("object_id")
        target_id = method_call.get("target_id")
        room = self.world.get_room(state.position)

        # ── inspect: hidden clue / reveal objects ──
        if verb == "inspect" and object_id and room:
            obj = self.world.get_object(object_id)
            if obj:
                if obj.hidden_clue and obj.hidden_flag and not state.flags.get(obj.hidden_flag):
                    applied["clues_added"].append(obj.hidden_clue)
                    applied["flags_set"][obj.hidden_flag] = True
                for rid in obj.reveals_objects:
                    if rid not in room.objects:
                        room.objects.append(rid)
                        applied["flags_set"][f"revealed_{rid}"] = True

        # ── take ──
        elif verb == "take" and object_id:
            applied["items_added"].append(object_id)
            for item_id in method_call.get("items_picked_up", []):
                if item_id not in applied["items_added"]:
                    applied["items_added"].append(item_id)

        # ── move ──
        elif verb == "move":
            move_to = method_call.get("move_to")
            if move_to and self.world.get_room(move_to):
                applied["moved_to"] = move_to

        # ── affordance call (any verb with a defined Affordance) ──
        elif verb not in ("none", "freeform", "inspect", "take", "move") and object_id:
            affordance = self.world.get_affordance(object_id, verb)
            if affordance:
                effect = affordance.effect
                # Unlock exit
                if "unlock_exit" in effect and room:
                    d = effect["unlock_exit"]
                    if d in room.locked_exits:
                        del room.locked_exits[d]
                # Flags
                applied["flags_set"].update(effect.get("flags", {}))
                # Clues
                applied["clues_added"].extend(effect.get("clues", []))
                # Consume self
                if affordance.consume_self:
                    applied["items_removed"].append(object_id)
                # Consume required item
                if affordance.consume_item and affordance.requires_item:
                    applied["items_removed"].append(affordance.requires_item)
                # Reveal objects
                for rid in effect.get("reveals_objects", []):
                    if room and rid not in room.objects:
                        room.objects.append(rid)
                        applied["flags_set"][f"revealed_{rid}"] = True

        # ── LLM-proposed clues (supplement, not override) ──
        if not applied["clues_added"]:
            for clue in method_call.get("clues_found", []):
                if clue and not state.has_clue(clue):
                    applied["clues_added"].append(clue)

        # ── items_used_up (freeform or LLM-declared consumption) ──
        for item_id in method_call.get("items_used_up", []):
            if item_id not in applied["items_removed"] and state.has_item(item_id):
                applied["items_removed"].append(item_id)

        # ── Commit canon changes ──
        for flag, val in applied["flags_set"].items():
            state.flags[flag] = val
        for clue in applied["clues_added"]:
            state.add_clue(clue)
        for item_id in applied["items_added"]:
            if not state.has_item(item_id):
                obj = self.world.get_object(item_id)
                if obj:
                    state.add_item(InventoryItem.from_object(obj))
                else:
                    state.add_item(InventoryItem(id=item_id, name=item_id))
        for item_id in applied["items_removed"]:
            state.remove_item(item_id)

        # ── Move: clear improvised items on room change ──
        if applied["moved_to"]:
            imp_ids = [i.id for i in state.inventory if i.id.startswith("imp_")]
            for iid in imp_ids:
                state.remove_item(iid)
                applied["items_removed"].append(iid)
            state.position = applied["moved_to"]

        # ── Improvised items ──
        if improvised_raw:
            validated = self._validate_improvised(improvised_raw, state)
            for imp in validated:
                inv_item = imp.to_inventory_item()
                state.add_item(inv_item)
                applied["improvised_added"].append({
                    "id": imp.id, "name": imp.name,
                    "category": imp.category, "ttl": imp.ttl,
                })

        state.turn += 1
        expired = state.tick_ttl()
        if expired:
            applied["items_removed"] = list(set(applied["items_removed"] + expired))

        return applied

    def _validate_improvised(self, raw_items: list, state: GameState) -> List[ImprovisedItem]:
        existing_imp_count = sum(1 for i in state.inventory if i.id.startswith("imp_"))
        slots_available = MAX_IMPROVISED_IN_INVENTORY - existing_imp_count
        if slots_available <= 0:
            return []

        accepted = []
        seen_ids = set()

        for raw in raw_items[:MAX_IMPROVISED_PER_TURN]:
            item_id = raw.get("id", "")
            name = raw.get("name", "").strip()
            desc = raw.get("desc", "").strip()
            category = raw.get("category", "")
            size = raw.get("size", "small")
            ttl_raw = raw.get("ttl", IMPROVISED_DEFAULT_TTL)
            tags = raw.get("tags", [])
            if not isinstance(tags, list):
                tags = []

            if not item_id.startswith("imp_"): continue
            if not name: continue
            if item_id in seen_ids or state.has_item(item_id): continue
            if category not in IMPROVISED_CATEGORIES: continue
            if category == "trace": continue      # trace never enters inventory
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
            if len(accepted) >= slots_available:
                break

        return accepted
