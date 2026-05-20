import unittest

import mcp_server
from core.types import GameObject, Combatant, InventoryItem


class ResolveDamageCoreTest(unittest.TestCase):
    """直接测 _resolve_damage 自由函数：抗性 + 扣 hp + destroyed 判定。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        # 清掉可能残留的全局 modifier，隔离抗性计算
        mcp_server.SESSION.modifiers.clear()

    def test_full_damage_no_resist(self):
        obj = GameObject(id="t1", name="箱", description="", hp=10, max_hp=10)
        r = mcp_server._resolve_damage(obj, 4, "blunt")
        self.assertEqual(r["damage"], 4)
        self.assertEqual(r["hp_after"], 6)
        self.assertFalse(r["destroyed"])

    def test_resistance_halves_damage(self):
        obj = GameObject(id="t2", name="湿木", description="", hp=10, max_hp=10,
                         damage_types_resist={"fire": 0.5})
        r = mcp_server._resolve_damage(obj, 6, "fire")
        self.assertEqual(r["damage"], 3)
        self.assertEqual(r["hp_after"], 7)

    def test_vulnerability_amplifies_damage(self):
        obj = GameObject(id="t3", name="火药桶", description="", hp=20, max_hp=20,
                         damage_types_resist={"fire": 2.0})
        r = mcp_server._resolve_damage(obj, 5, "fire")
        self.assertEqual(r["damage"], 10)

    def test_minimum_one_damage(self):
        obj = GameObject(id="t4", name="铁砧", description="", hp=10, max_hp=10,
                         damage_types_resist={"blunt": 0.0})
        r = mcp_server._resolve_damage(obj, 8, "blunt")
        self.assertEqual(r["damage"], 1)  # 抗性 0 也至少 1

    def test_hp_floors_at_zero_and_marks_destroyed(self):
        obj = GameObject(id="t5", name="陶罐", description="", hp=3, max_hp=3)
        r = mcp_server._resolve_damage(obj, 99, "blunt")
        self.assertEqual(r["hp_after"], 0)
        self.assertTrue(r["destroyed"])

    def test_damage_modifier_from_pool_applies(self):
        # 池里加一个 +3 damage modifier，确认 _resolve_damage 吃它
        mcp_server.add_modifier(source_kind="item", target="damage", op="add",
                                value=3, reason="利刃")
        obj = GameObject(id="t6", name="草人", description="", hp=20, max_hp=20)
        r = mcp_server._resolve_damage(obj, 2, "slash")
        self.assertEqual(r["damage"], 5)  # 2 + 3


class DealDamageExplorationTest(unittest.TestCase):
    """deal_damage 探索态：场景物体属性解冻 + on_destroyed 链路。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        # 走到巷子（牛粪堆所在房间）
        self.assertTrue(mcp_server.move("south")["ok"])

    def test_destroying_dung_heap_reveals_hidden_token(self):
        # 炸前：token 隐藏，不在场景
        scene_before = mcp_server.get_scene()["scene"]
        ids_before = {o["id"] for o in scene_before["objects"]}
        self.assertIn("dung_heap", ids_before)
        self.assertNotIn("rusted_token", ids_before)

        result = mcp_server.deal_damage(
            target="dung_heap", amount=5, damage_type="fire",
            reason="鞭炮炸牛粪堆",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["context"], "exploration")
        self.assertTrue(result["destroyed"])

        # on_destroyed 产出：揭示 token + 置 flag + 加线索
        od = result["on_destroyed"]
        self.assertIn("rusted_token", od["revealed"])
        self.assertTrue(od["effects"]["flags_set"]["dung_heap_destroyed"])

        # 场景：牛粪堆没了，token 现身且可拾取
        ids_after = {o["id"] for o in result["scene"]["objects"]}
        self.assertNotIn("dung_heap", ids_after)
        self.assertIn("rusted_token", ids_after)

        # 揭示的 token 真能拿走
        take = mcp_server.take_item("rusted_token")
        self.assertTrue(take["ok"])

    def test_indestructible_target_rejected(self):
        # 把石板路标成坚不可摧，确认被拒
        mcp_server.SESSION.world.get_object("wet_cobblestone").indestructible = True
        result = mcp_server.deal_damage(target="wet_cobblestone", amount=5)
        self.assertFalse(result["ok"])
        self.assertIn("坚不可摧", result["error"])

    def test_money_bag_is_protected_and_gold_untouched(self):
        # 钱是抽象 vitals 资产，coin_bag 是叙事道具——炸它应被拒，gold 不变。
        # （见会话记录：防止"火球烧没五万金币"这类散文/引擎脱节）
        mcp_server.start_game()  # 回到公寓，coin_bag 在场
        gold_before = mcp_server.SESSION.state.vitals.gold
        result = mcp_server.deal_damage(target="coin_bag", amount=100, damage_type="fire")
        self.assertFalse(result["ok"])
        self.assertIn("坚不可摧", result["error"])
        self.assertEqual(mcp_server.SESSION.state.vitals.gold, gold_before)

    def test_unknown_target_rejected(self):
        result = mcp_server.deal_damage(target="no_such_thing", amount=3)
        self.assertFalse(result["ok"])

    def test_target_not_in_room_rejected(self):
        # dwarf_bartender 在酒馆，不在当前巷子
        result = mcp_server.deal_damage(target="dwarf_bartender", amount=3)
        self.assertFalse(result["ok"])

    def test_nonpositive_amount_rejected(self):
        result = mcp_server.deal_damage(target="dung_heap", amount=0)
        self.assertFalse(result["ok"])

    def test_destroying_inventory_item_removes_it_from_inventory(self):
        # 临时构造一件可破坏的背包物：注册进 world（供 get_object 解析）+ 塞进背包
        world, state = mcp_server.SESSION.world, mcp_server.SESSION.state
        obj = GameObject(id="frail_vial", name="脆裂药瓶", description="一触即碎的小瓶",
                         hp=1, max_hp=1, takable=True)
        world.add_object(obj)
        state.add_item(InventoryItem.from_object(obj))
        self.assertTrue(state.has_item("frail_vial"))

        result = mcp_server.deal_damage(target="frail_vial", amount=5, reason="一脚踩碎")
        self.assertTrue(result["ok"])
        self.assertEqual(result["context"], "exploration")
        self.assertTrue(result["destroyed"])

        # 善后：从背包移除，且 outcome 记录 removed_from_inventory
        self.assertEqual(result["on_destroyed"]["removed_from_inventory"], "frail_vial")
        self.assertFalse(state.has_item("frail_vial"))


class DealDamageCombatTest(unittest.TestCase):
    """deal_damage 战斗态：解析 combatant，共用同一结算函数。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        self.assertTrue(mcp_server.start_combat(canon=["dock_thug"])["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_deal_damage_to_combatant_in_combat(self):
        result = mcp_server.deal_damage(
            target="enemy_dock_thug", amount=3, damage_type="blunt",
            reason="环境伤害：塌落的横梁",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["context"], "combat")
        thug = mcp_server.SESSION.encounter.combatants["enemy_dock_thug"]
        self.assertEqual(thug.hp, thug.max_hp - 3)

    def test_lethal_damage_marks_combatant_dead(self):
        thug = mcp_server.SESSION.encounter.combatants["enemy_dock_thug"]
        result = mcp_server.deal_damage(target="enemy_dock_thug", amount=999)
        self.assertTrue(result["ok"])
        self.assertTrue(result["destroyed"])
        self.assertTrue(thug.is_dead)

    def test_cannot_damage_already_dead(self):
        mcp_server.deal_damage(target="enemy_dock_thug", amount=999)
        again = mcp_server.deal_damage(target="enemy_dock_thug", amount=5)
        self.assertFalse(again["ok"])


if __name__ == "__main__":
    unittest.main()
