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


class ImprovisedWeaponTest(unittest.TestCase):
    """破局核心：GM 能即兴出真能装备开打的破烂武器，且超规被钳。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_improvised_weapon_is_equippable(self):
        r = mcp_server.add_improvised([{
            "id": "imp_bottle", "name": "碎酒瓶", "category": "tool",
            "equip_slot": "weapon", "damage_expr": "1d3", "damage_type": "slash"}])
        self.assertTrue(r["ok"])
        it = mcp_server.SESSION.state.get_item("imp_bottle")
        self.assertEqual((it.equip_slot, it.damage_expr, it.damage_type), ("weapon", "1d3", "slash"))
        self.assertTrue(mcp_server.equip("imp_bottle")["ok"])

    def test_overspec_weapon_clamped(self):
        # 神兵级/元素伤害被钳：默认 1d3、类型回退物理
        mcp_server.add_improvised([{
            "id": "imp_godsword", "name": "神剑", "category": "tool",
            "equip_slot": "weapon", "damage_expr": "2d12", "damage_type": "fire"}])
        it = mcp_server.SESSION.state.get_item("imp_godsword")
        self.assertIn(it.damage_expr, mcp_server.IMPROVISED_WEAPON_DICE)
        self.assertIn(it.damage_type, mcp_server.IMPROVISED_DMG_TYPES)

    def test_capabilities_surfaced(self):
        r = mcp_server.add_improvised([
            {"id": "imp_club", "name": "桌腿", "category": "tool",
             "equip_slot": "weapon", "damage_expr": "1d4"},
            {"id": "imp_note", "name": "字条", "category": "clue", "desc": "潦草几字"},
        ])
        caps = {a["id"]: a["capabilities"] for a in r["added"]}
        self.assertTrue(any("武器" in c for c in caps["imp_club"]))
        self.assertTrue(any("纯叙事" in c for c in caps["imp_note"]))

    def test_improvised_armor_defense_clamped(self):
        mcp_server.add_improvised([{
            "id": "imp_lid", "name": "破锅盖", "category": "tool",
            "equip_slot": "armor", "defense": 99}])
        it = mcp_server.SESSION.state.get_item("imp_lid")
        self.assertLessEqual(it.defense, mcp_server.IMPROVISED_MAX_DEFENSE)

    def test_improvised_consumable_heal_clamped(self):
        mcp_server.add_improvised([{
            "id": "imp_berry", "name": "野果", "category": "consumable",
            "use_effect": {"heal": 999}}])
        it = mcp_server.SESSION.state.get_item("imp_berry")
        self.assertLessEqual(it.use_effect.get("heal", 0), mcp_server.IMPROVISED_MAX_HEAL)

    def test_plain_item_has_no_weapon_capability(self):
        # 光给名字的物品 = 纯叙事，不能当武器
        mcp_server.add_improvised([{"id": "imp_rag", "name": "破布", "category": "fragment"}])
        it = mcp_server.SESSION.state.get_item("imp_rag")
        self.assertEqual(it.equip_slot, "")
        self.assertEqual(it.damage_expr, "")

    def test_improvised_item_survives_room_change(self):
        # 即兴物品不再跨场景消失——掰的棍、捡的瓶子带得走
        mcp_server.add_improvised([{
            "id": "imp_bottle", "name": "碎酒瓶", "category": "tool",
            "equip_slot": "weapon", "damage_expr": "1d3"}])
        self.assertTrue(mcp_server.SESSION.state.has_item("imp_bottle"))
        self.assertTrue(mcp_server.move("north")["ok"])   # 营地 → 草原
        self.assertTrue(mcp_server.SESSION.state.has_item("imp_bottle"))

    def test_default_ttl_is_permanent(self):
        # 默认不过期：推进多个回合仍在
        mcp_server.add_improvised([{"id": "imp_keep", "name": "护身石", "category": "trinket"}])
        self.assertEqual(mcp_server.SESSION.state.get_item("imp_keep").ttl, -1)
        for _ in range(8):
            mcp_server.inspect_object("teleport_crystal")   # 每次推进一回合 + tick_ttl
        self.assertTrue(mcp_server.SESSION.state.has_item("imp_keep"))

    def test_explicit_finite_ttl_still_expires(self):
        # 显式限时（火把/烟雾）仍按 ttl 到期消失
        mcp_server.add_improvised([{"id": "imp_torch", "name": "火把", "category": "tool", "ttl": 2}])
        self.assertEqual(mcp_server.SESSION.state.get_item("imp_torch").ttl, 2)
        for _ in range(2):
            mcp_server.inspect_object("teleport_crystal")
        self.assertFalse(mcp_server.SESSION.state.has_item("imp_torch"))


if __name__ == "__main__":
    unittest.main()
