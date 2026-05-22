"""破局冷开局：赤贫起手 + 三条破局路 + 杀人兔门槛。"""
import unittest

import mcp_server


class ColdOpenStartTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_start_is_destitute(self):
        v = mcp_server.SESSION.state.vitals
        self.assertEqual((v.hp, v.max_hp), (6, 6))
        self.assertEqual(v.gold, 0)
        self.assertEqual(mcp_server.SESSION.state.inventory, [])
        self.assertEqual(mcp_server.SESSION.state.skills, [])
        self.assertEqual(mcp_server.SESSION.state.relationships, {})

    def test_unarmed_is_1d1(self):
        mcp_server.start_combat(canon=["killer_rabbit"])
        self.assertEqual(
            mcp_server.SESSION.encounter.combatants["player"].damage_expr, "1d1")

    def test_killer_rabbit_stats(self):
        rb = mcp_server.SESSION.world.get_enemy("killer_rabbit")
        self.assertEqual((rb.hp, rb.damage_expr), (8, "1d4"))

    def test_weapon_rack_gated_for_newcomer(self):
        # 未登记新人领不到镇上军备
        r = mcp_server.call_affordance("weapon_rack", "take_sword")
        self.assertFalse(r["ok"])


class PathTavernTest(unittest.TestCase):
    """破局路一：酒馆斗殴 → 挨打 → 道义补偿（首币 + 人脉）。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        self.assertTrue(mcp_server.move("east")["ok"])  # 营地 → 酒馆

    def test_back_adventurers_rewards(self):
        r = mcp_server.call_affordance("tavern_brawl", "back_adventurers")
        self.assertTrue(r["ok"])
        self.assertEqual(mcp_server.SESSION.state.vitals.gold, 5)
        self.assertTrue(mcp_server.SESSION.state.flags.get("tavern_ally"))

    def test_back_guards_also_rewards(self):
        r = mcp_server.call_affordance("tavern_brawl", "back_guards")
        self.assertTrue(r["ok"])
        self.assertEqual(mcp_server.SESSION.state.vitals.gold, 5)  # 不管帮谁都有补偿
        self.assertTrue(mcp_server.SESSION.state.flags.get("tavern_ally"))

    def test_brawl_is_one_shot(self):
        mcp_server.call_affordance("tavern_brawl", "back_adventurers")
        # consume_self：选过边后斗殴对象消失，不能再刷
        r2 = mcp_server.call_affordance("tavern_brawl", "back_guards")
        self.assertFalse(r2["ok"])


class PathTreeTest(unittest.TestCase):
    """破局路二：攻击/掰枯树 → 木棍（1d4）。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        self.assertTrue(mcp_server.move("north")["ok"])  # 营地 → 草原

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_break_branch_yields_club(self):
        r = mcp_server.call_affordance("lone_tree", "break_branch")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("got_first_weapon"))
        self.assertTrue(mcp_server.take_item("wooden_club")["ok"])
        eq = mcp_server.equip("wooden_club")
        self.assertTrue(eq["ok"])

    def test_destroying_tree_also_yields_club(self):
        # 用 deal_damage 砸断枯树（hp 4），on_destroyed 也给木棍
        r = mcp_server.deal_damage(target="lone_tree", amount=10, reason="一脚踹断")
        self.assertTrue(r["destroyed"])
        self.assertIn("wooden_club", r["on_destroyed"]["revealed"])

    def test_club_is_1d4_weapon(self):
        club = mcp_server.SESSION.world.get_object("wooden_club")
        self.assertEqual(club.damage_expr, "1d4")
        self.assertEqual(club.equip_slot, "weapon")


class PathForestTest(unittest.TestCase):
    """破局路三：闯树林（需运气，GM 裁定）→ 守林员小屋 → 手斧（1d6）。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.SESSION.state.position = "forest_edge"

    def test_hut_locked_until_path_found(self):
        r = mcp_server.move("in")
        self.assertFalse(r["ok"])  # 没找到路 → 锁着

    def test_gm_unlock_then_hatchet(self):
        # GM 让玩家掷运气过关后解锁
        mcp_server.gm_set_flag("forest_path_found", True, unlock_exit="in")
        self.assertTrue(mcp_server.move("in")["ok"])
        self.assertEqual(mcp_server.SESSION.state.position, "forester_hut")
        self.assertTrue(mcp_server.take_item("forester_hatchet")["ok"])
        eq = mcp_server.equip("forester_hatchet")
        self.assertTrue(eq["ok"])

    def test_hatchet_is_1d6(self):
        axe = mcp_server.SESSION.world.get_object("forester_hatchet")
        self.assertEqual(axe.damage_expr, "1d6")

    def test_search_shelf_gains_gold(self):
        mcp_server.gm_set_flag("forest_path_found", True, unlock_exit="in")
        mcp_server.move("in")
        g0 = mcp_server.SESSION.state.vitals.gold
        r = mcp_server.call_affordance("dusty_shelf", "search")
        self.assertTrue(r["ok"])
        self.assertEqual(mcp_server.SESSION.state.vitals.gold, g0 + 3)


if __name__ == "__main__":
    unittest.main()
