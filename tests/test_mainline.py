"""主线后半段骨架回归测试。

锁住机制（房间可达、目标存在、守卫可战、三解法分支、任务推进），
不测叙事文案（desc 都是 TODO 占位）。
"""
import unittest

import mcp_server
from core.types import InventoryItem


def _give_item(item_id):
    obj = mcp_server.SESSION.world.get_object(item_id)
    mcp_server.SESSION.state.add_item(InventoryItem.from_object(obj))


class WorldExpansionTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        self.world = mcp_server.SESSION.world

    def test_new_rooms_exist(self):
        self.assertIsNotNone(self.world.get_room("dock_7_yard"))
        self.assertIsNotNone(self.world.get_room("lord_boathouse"))

    def test_target_npc_and_guards_exist(self):
        self.assertIsNotNone(self.world.get_object("lord_belveth"))
        self.assertIsNotNone(self.world.get_enemy("lord_guard"))
        self.assertIsNotNone(self.world.get_enemy("belveth_combatant"))

    def test_warehouse_connects_to_new_area(self):
        self.assertEqual(self.world.get_room("warehouse").exits.get("east"), "dock_7_yard")
        self.assertEqual(self.world.get_room("dock_7_yard").exits.get("east"), "lord_boathouse")

    def test_boathouse_locked_behind_guard_post(self):
        # 进 dock_7_yard 时 east 默认锁住
        yard = self.world.get_room("dock_7_yard")
        self.assertIn("east", yard.locked_exits)


class CombatSolutionTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.state.position = "dock_7_yard"

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_provoke_starts_combat_with_guard(self):
        r = mcp_server.call_affordance("guard_post", "provoke")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.in_combat)
        self.assertTrue(mcp_server.SESSION.state.flags.get("chose_combat"))
        # 守卫确实在场
        ids = {c["id"] for c in mcp_server._encounter_snapshot()["combatants"]}
        self.assertIn("enemy_lord_guard", ids)

    def test_confront_lord_starts_boss_combat(self):
        mcp_server.SESSION.state.position = "lord_boathouse"
        r = mcp_server.call_affordance("lord_belveth", "confront")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.in_combat)
        ids = {c["id"] for c in mcp_server._encounter_snapshot()["combatants"]}
        self.assertIn("enemy_belveth_combatant", ids)


class StealthSolutionTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.state.position = "dock_7_yard"

    def test_sneak_requires_stealth_check_flag(self):
        # 未通过检定 → 被拒
        r = mcp_server.call_affordance("guard_post", "sneak_past")
        self.assertFalse(r["ok"])

    def test_sneak_unlocks_after_check_passed(self):
        mcp_server.SESSION.state.flags["stealth_check_passed"] = True
        r = mcp_server.call_affordance("guard_post", "sneak_past")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("guard_post_cleared"))
        self.assertTrue(mcp_server.SESSION.state.flags.get("chose_stealth"))
        # east 解锁
        self.assertNotIn("east", self.world_yard().locked_exits)

    def test_assassinate_requires_stealth_approach(self):
        mcp_server.SESSION.state.position = "lord_boathouse"
        # 没走潜行路线 → 不能暗杀
        r = mcp_server.call_affordance("lord_belveth", "assassinate")
        self.assertFalse(r["ok"])

    def test_silent_kill_completes_via_assassinate(self):
        mcp_server.SESSION.state.flags["chose_stealth"] = True
        mcp_server.SESSION.state.position = "lord_boathouse"
        r = mcp_server.call_affordance("lord_belveth", "assassinate")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("silent_kill"))
        self.assertTrue(mcp_server.SESSION.state.flags.get("target_eliminated"))

    def world_yard(self):
        return mcp_server.SESSION.world.get_room("dock_7_yard")


class FrameSolutionTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.state.position = "lord_boathouse"

    def test_plant_evidence_requires_manifest(self):
        # 没有货运清单 → 被拒
        r = mcp_server.call_affordance("smuggled_arms_crate", "plant_evidence")
        self.assertFalse(r["ok"])

    def test_frame_completes_with_manifest(self):
        _give_item("dock_manifest")
        r = mcp_server.call_affordance("smuggled_arms_crate", "plant_evidence")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("framed"))
        self.assertTrue(mcp_server.SESSION.state.flags.get("target_eliminated"))
        # 嫁祸消耗清单
        self.assertFalse(mcp_server.SESSION.state.has_item("dock_manifest"))


class EnvironmentalHooksTest(unittest.TestCase):
    """环境'意外'：可破坏物的 on_destroyed 触发收尾 flag。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.state.position = "lord_boathouse"

    def test_oil_drums_fire_sets_ablaze(self):
        r = mcp_server.deal_damage(target="oil_drums", amount=2, damage_type="fire")
        self.assertTrue(r["ok"])
        self.assertTrue(r["destroyed"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("boathouse_ablaze"))

    def test_steam_launch_destroyed(self):
        r = mcp_server.deal_damage(target="steam_launch", amount=20, damage_type="fire")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("launch_destroyed"))

    def test_mooring_rope_slash_vulnerable(self):
        # 缆绳在外围货场（dock_7_yard），对斩击易伤（resist 2.0），一下就断
        mcp_server.SESSION.state.position = "dock_7_yard"
        r = mcp_server.deal_damage(target="mooring_rope", amount=2, damage_type="slash")
        self.assertTrue(r["ok"])
        self.assertTrue(r["destroyed"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("launch_adrift"))


class DistractSolutionTest(unittest.TestCase):
    """第三条解法：引开守卫（distract，需先制造声响）。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.state.position = "dock_7_yard"

    def test_distract_requires_a_disturbance_first(self):
        # 没制造声响（crates_toppled）→ 引不走守卫
        r = mcp_server.call_affordance("guard_post", "distract")
        self.assertFalse(r["ok"])

    def test_distract_clears_guards_after_disturbance(self):
        mcp_server.SESSION.state.flags["crates_toppled"] = True
        r = mcp_server.call_affordance("guard_post", "distract")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("guard_post_cleared"))
        self.assertNotIn("east", mcp_server.SESSION.world.get_room("dock_7_yard").locked_exits)

    def test_toppling_crates_then_distract_full_chain(self):
        # 完整链：砸倒货箱（deal_damage 触发 crates_toppled）→ 引开 → 通道开
        r1 = mcp_server.deal_damage(target="stacked_crates", amount=10, damage_type="blunt")
        self.assertTrue(r1["destroyed"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("crates_toppled"))
        r2 = mcp_server.call_affordance("guard_post", "distract")
        self.assertTrue(r2["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("guard_post_cleared"))


class GmAdjudicationTest(unittest.TestCase):
    """GM 裁定权：gm_set_flag 兜底预设外的创意解法。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.state.position = "dock_7_yard"

    def test_gm_set_flag_unlocks_locked_exit(self):
        # 模拟玩家用预设外手段清除守卫，GM 裁定后解锁
        self.assertIn("east", mcp_server.SESSION.world.get_room("dock_7_yard").locked_exits)
        r = mcp_server.gm_set_flag("guard_post_cleared", True, unlock_exit="east")
        self.assertTrue(r["ok"])
        self.assertEqual(r["unlocked_exit"], "east")
        self.assertTrue(mcp_server.SESSION.state.flags.get("guard_post_cleared"))
        self.assertNotIn("east", mcp_server.SESSION.world.get_room("dock_7_yard").locked_exits)
        # 解锁后玩家真能走过去
        moved = mcp_server.move("east")
        self.assertTrue(moved["ok"])
        self.assertEqual(mcp_server.SESSION.state.position, "lord_boathouse")

    def test_gm_set_flag_without_unlock(self):
        r = mcp_server.gm_set_flag("some_story_flag", True)
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("some_story_flag"))

    def test_gm_set_flag_nonexistent_exit_notes_gracefully(self):
        r = mcp_server.gm_set_flag("x", True, unlock_exit="up")
        self.assertTrue(r["ok"])
        self.assertIn("unlock_note", r)  # 优雅提示，不报错


if __name__ == "__main__":
    unittest.main()
