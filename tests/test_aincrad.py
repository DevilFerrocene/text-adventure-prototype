"""苍穹回廊（aincrad）新世界骨架回归测试。

锁住机制（世界可启动、房间可达、怪物可战、属性克制、三类技能、攻略主线），
不测叙事文案（desc 多为 TODO）。同时确认多世界共存（不影响 yanan）。
"""
import unittest
from unittest.mock import patch

import mcp_server


class AincradWorldTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        self.world = mcp_server.SESSION.world

    def test_world_starts_in_camp(self):
        self.assertEqual(mcp_server.SESSION.state.position, "camp")
        # 起手有 SP（stamina）和铁剑
        self.assertEqual(mcp_server.SESSION.state.vitals.max_stamina, 10)
        self.assertTrue(mcp_server.SESSION.state.has_item("iron_sword"))

    def test_hud_shows_sp_and_floor(self):
        hud = mcp_server.get_state()["hud"]
        self.assertIn("⚡", hud)            # SP 条
        self.assertIn("营地", hud)          # 位置

    def test_floor_1_rooms_chain(self):
        self.assertEqual(self.world.get_room("camp").exits.get("north"), "plains")
        self.assertEqual(self.world.get_room("plains").exits.get("north"), "labyrinth")
        self.assertEqual(self.world.get_room("labyrinth").exits.get("north"), "warden_gate")

    def test_camp_is_safe_zone_no_enemies(self):
        self.assertEqual(self.world.get_room("camp").enemies, [])

    def test_enemies_and_boss_exist(self):
        for eid in ("frenzy_boar", "gale_wolf", "mistbloom", "warden_gorehoof"):
            self.assertIsNotNone(self.world.get_enemy(eid))


class CombatAndResistanceTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.SESSION.state.position = "warden_gate"

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_challenge_starts_boss_fight(self):
        r = mcp_server.call_affordance("warden_arena", "challenge")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.in_combat)
        ids = {c["id"] for c in mcp_server._encounter_snapshot()["combatants"]}
        self.assertIn("enemy_warden_gorehoof", ids)

    def test_fire_amplified_against_boss(self):
        mcp_server.call_affordance("warden_arena", "challenge")
        boss = mcp_server.SESSION.encounter.combatants["enemy_warden_gorehoof"]
        boss.hp = boss.max_hp = 100
        r = mcp_server.deal_damage(target="enemy_warden_gorehoof", amount=10, damage_type="fire")
        self.assertEqual(r["resist"], 1.5)
        self.assertEqual(r["damage"], 15)  # 10 × 1.5

    def test_frost_resisted_against_boss(self):
        mcp_server.call_affordance("warden_arena", "challenge")
        boss = mcp_server.SESSION.encounter.combatants["enemy_warden_gorehoof"]
        boss.hp = boss.max_hp = 100
        r = mcp_server.deal_damage(target="enemy_warden_gorehoof", amount=10, damage_type="frost")
        self.assertEqual(r["damage"], 5)  # 10 × 0.5


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.SESSION.modifiers.clear()

    def test_passive_mastery_boosts_attack_roll(self):
        mcp_server.learn_skill("sword_mastery")
        with patch("mcp_server.random.randint", return_value=10):
            rc = mcp_server.roll_check(reason="挥砍攻击", sides=20)
        self.assertEqual(rc["total"], 12)  # 10 + 2

    def test_active_sword_art_costs_sp(self):
        mcp_server.SESSION.state.vitals.stamina = 10
        mcp_server.learn_skill("vertical_arc")
        before = mcp_server.SESSION.state.vitals.stamina
        u = mcp_server.use_skill("vertical_arc")
        self.assertTrue(u["ok"])
        self.assertEqual(mcp_server.SESSION.state.vitals.stamina, before - 3)

    def test_sword_art_buff_amplifies_next_attack(self):
        mcp_server.SESSION.state.vitals.stamina = 10
        mcp_server.learn_skill("vertical_arc")
        mcp_server.use_skill("vertical_arc")  # 挂"蓄力斩" damage +4 buff
        # 在战斗里验证增伤：起一场战斗对野猪
        mcp_server.SESSION.state.position = "plains"
        mcp_server.start_combat(canon=["frenzy_boar"])
        boar = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        boar.hp = boar.max_hp = 100
        # deal_damage 走 damage modifier 池：基础 5 + 4(蓄力) = 9
        r = mcp_server.deal_damage(target="enemy_frenzy_boar", amount=5,
                                   damage_type="slash", reason="垂直方斩攻击")
        self.assertGreaterEqual(r["damage"], 9)
        mcp_server.end_combat(reason="test")

    def test_reactive_evasion_on_take_damage(self):
        mcp_server.learn_skill("crisis_evasion")
        mcp_server.SESSION.state.position = "warden_gate"
        mcp_server.call_affordance("warden_arena", "challenge")
        r = mcp_server.deal_damage(target="player", amount=2, reason="首领重踏")
        self.assertTrue(r["ok"])
        self.assertIn("reactive_fired", r)
        mcp_server.end_combat(reason="test")


class LabyrinthAndQuestTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_labyrinth_locked_until_solved(self):
        lab = mcp_server.SESSION.world.get_room("labyrinth")
        self.assertIn("north", lab.locked_exits)  # 首领门默认锁

    def test_solving_rune_door_needs_glyph_first(self):
        mcp_server.SESSION.state.position = "labyrinth"
        # 没读刻印 → 解不开
        r = mcp_server.call_affordance("rune_door", "solve")
        self.assertFalse(r["ok"])

    def test_full_labyrinth_clear_unlocks_boss_gate(self):
        mcp_server.SESSION.state.position = "labyrinth"
        mcp_server.inspect_object("wall_glyph")          # 置 read_wall_glyph
        r = mcp_server.call_affordance("rune_door", "solve")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("labyrinth_cleared"))
        self.assertNotIn("north", mcp_server.SESSION.world.get_room("labyrinth").locked_exits)

    def test_skill_book_chest_teaches_art(self):
        mcp_server.SESSION.state.position = "labyrinth"
        r = mcp_server.call_affordance("treasure_chest", "open")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("learned_vertical_arc"))

    def test_quest_starts_at_floor_1(self):
        q = mcp_server.get_state()["state_context"]["quest_log"][0]
        self.assertEqual(q["id"], "floor_1_conquest")
        self.assertEqual(q["stage"], "entered_floor_1")

    def test_grant_xp_levels_up_skill(self):
        mcp_server.learn_skill("sword_mastery")
        r = mcp_server.grant_xp("sword_mastery", 3, reason="清光草原杂兵")
        self.assertTrue(r["ranked_up"])
        self.assertEqual(r["rank_after"], 2)


class MultiWorldCoexistenceTest(unittest.TestCase):
    """两个世界共存：切换不串味，各自独立。"""

    def test_can_switch_between_worlds(self):
        self.assertTrue(mcp_server.start_game("yanan")["ok"])
        self.assertEqual(mcp_server.SESSION.state.position, "apartment")
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        self.assertEqual(mcp_server.SESSION.state.position, "camp")
        # aincrad 的敌人不在 yanan
        self.assertTrue(mcp_server.start_game("yanan")["ok"])
        self.assertIsNone(mcp_server.SESSION.world.get_enemy("warden_gorehoof"))
        self.assertIsNotNone(mcp_server.SESSION.world.get_enemy("dock_thug"))

    def test_unknown_world_rejected(self):
        r = mcp_server.start_game("no_such_world")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
