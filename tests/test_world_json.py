"""JSON 世界格式 ⇄ GameWorld 往返无损 + 加载器边界。

世界编辑器把世界当数据增删改，全靠这条 JSON ⇄ dataclass 通路。这里钉死：
导出再加载的世界与原世界结构等价、嵌套结构（tuple 坐标/affordance/棋盘 POI/
技能 recipe/初始状态）都正确还原、未知键被忽略。
"""
import json
import unittest

from runtime.game_world import GameWorld
from runtime.world_json import (
    world_to_json, load_world_from_json, populate_world_from_json, JsonWorld,
)
import content.aincrad as aincrad


def _aincrad_json() -> dict:
    """把 Python 版 aincrad 导成 JSON 数据，再过一遍 json 字符串（逼出非法类型）。"""
    w = GameWorld(content_module=aincrad)
    return json.loads(json.dumps(world_to_json(w, "aincrad"), ensure_ascii=False))


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self.w0 = GameWorld(content_module=aincrad)
        self.w1 = load_world_from_json(_aincrad_json())

    def test_both_validate_clean(self):
        self.assertEqual(self.w0.validate(), [])
        self.assertEqual(self.w1.validate(), [], "JSON 还原后的世界引用应仍干净")

    def test_entity_counts_match(self):
        self.assertEqual(len(self.w1.rooms), len(self.w0.rooms))
        self.assertEqual(len(self.w1.objects), len(self.w0.objects))
        self.assertEqual(len(self.w1.enemies), len(self.w0.enemies))
        self.assertEqual(len(self.w1.skills), len(self.w0.skills))

    def test_grid_coords_are_tuples(self):
        grid = self.w1.rooms["tavern"].grid
        self.assertIsInstance(grid.entry, tuple)
        self.assertEqual(grid.entry, (0, 2))
        self.assertIsInstance(grid.objects["tavern_keeper"], tuple)
        self.assertEqual(grid.objects["tavern_keeper"], (3, 0))

    def test_grid_poi_restored(self):
        poi = self.w1.rooms["plains"].grid.pois[0]
        self.assertEqual(poi.id, "plains_glint")
        self.assertEqual(poi.cell, (4, 5))
        self.assertEqual(poi.payload["kind"], "loot")

    def test_object_affordance_restored(self):
        aff = self.w1.objects["tavern_brawl"].affordances["back_adventurers"]
        self.assertEqual(aff.verb, "back_adventurers")
        self.assertEqual(aff.effect["gain_gold"], 5)
        self.assertTrue(aff.consume_self)

    def test_skill_nested_recipe_restored(self):
        sk = self.w1.skills["vertical_arc"]
        self.assertIsNotNone(sk.active)
        self.assertEqual(sk.active.recipe[0].verb, "apply_buff")
        mod = self.w1.skills["sword_mastery"].passive_modifiers[0]
        self.assertEqual(mod.target, "roll")

    def test_initial_state_restored(self):
        st = self.w1.initial_state
        self.assertEqual(st.position, "camp")
        self.assertEqual(st.vitals.hp, 6)
        self.assertEqual(st.quest_log[0].id, "break_the_deadlock")
        self.assertEqual(st.vitals.attributes["dex"], 4)

    def test_enemy_combat_fields_restored(self):
        e = self.w1.enemies["gale_wolf"]
        self.assertEqual(e.sight, 4)
        self.assertEqual(e.reach, 1)
        self.assertEqual(e.damage_types_resist.get("frost"), 0.5)


class LoaderEdgeTest(unittest.TestCase):
    def test_unknown_keys_ignored(self):
        data = {
            "name": "tiny",
            "rooms": {"r0": {"id": "r0", "name": "房", "base_description": "d",
                             "bogus_field": 123}},
            "initial_state": {"position": "r0"},
        }
        w = load_world_from_json(data)
        self.assertIn("r0", w.rooms)
        self.assertEqual(w.validate(), [])

    def test_id_defaults_to_dict_key(self):
        data = {"enemies": {"goblin": {"name": "哥布林", "hp": 5, "max_hp": 5}}}
        w = load_world_from_json(data)
        self.assertEqual(w.enemies["goblin"].id, "goblin")

    def test_jsonworld_register_matches_loader(self):
        data = _aincrad_json()
        w = GameWorld(content_module=JsonWorld(data, "aincrad"))
        self.assertEqual(w.validate(), [])
        self.assertEqual(len(w.rooms), 9)

    def test_populate_in_place(self):
        w = GameWorld()
        populate_world_from_json(w, {"enemies": {"g": {"name": "g", "hp": 3, "max_hp": 3}}})
        self.assertEqual(w.get_enemy("g").name, "g")


if __name__ == "__main__":
    unittest.main()
