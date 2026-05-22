"""苍穹回廊（aincrad）新世界骨架回归测试。

锁住机制（世界可启动、房间可达、怪物可战、属性克制、三类技能、攻略主线），
不测叙事文案（desc 多为 TODO）。
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
        # 冷开局：赤贫无依——6 血、0 金、空背包、无技能、少量 SP
        v = mcp_server.SESSION.state.vitals
        self.assertEqual(v.max_hp, 6)
        self.assertEqual(v.gold, 0)
        self.assertEqual(mcp_server.SESSION.state.inventory, [])
        self.assertEqual(mcp_server.SESSION.state.skills, [])

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

    def test_cold_open_has_no_skills_then_learnable(self):
        # 冷开局一无所长：起手没有任何技能
        self.assertEqual(mcp_server.SESSION.state.skills, [])
        # 但技能可习得，习得后真进 state + 前台可见
        self.assertTrue(mcp_server.learn_skill("sword_mastery")["ok"])
        ids = {s.id for s in mcp_server.SESSION.state.skills}
        self.assertIn("sword_mastery", ids)
        ctx_ids = {s["id"] for s in mcp_server.get_state()["state_context"]["skills"]}
        self.assertIn("sword_mastery", ctx_ids)

    def test_npc_teaches_skill_into_state(self):
        # 营地教官教学：真进 state.skills，不只是置 flag
        before = {s.id for s in mcp_server.SESSION.state.skills}
        self.assertNotIn("vertical_arc", before)
        r = mcp_server.call_affordance("skill_trainer", "learn_vertical_arc")
        self.assertTrue(r["ok"])
        self.assertIn("vertical_arc", r["changes"].get("skills_learned", []))
        after = {s.id for s in mcp_server.SESSION.state.skills}
        self.assertIn("vertical_arc", after)

    def test_relearning_does_not_duplicate(self):
        mcp_server.call_affordance("skill_trainer", "learn_vertical_arc")
        r2 = mcp_server.call_affordance("skill_trainer", "learn_vertical_arc")
        self.assertEqual(r2["changes"].get("skills_learned"), [])
        count = [s.id for s in mcp_server.SESSION.state.skills].count("vertical_arc")
        self.assertEqual(count, 1)

    def test_passive_mastery_boosts_attack_roll(self):
        mcp_server.learn_skill("sword_mastery")
        with patch("mcp_server.random.randint", return_value=10):
            rc = mcp_server.roll_check(reason="挥砍攻击", sides=20)
        self.assertEqual(rc["total"], 16)  # 10 + 2(精通passive) + 4(敏)

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
        # 技能真进 state.skills，不只是 flag
        self.assertIn("vertical_arc", r["changes"].get("skills_learned", []))
        self.assertIn("vertical_arc", {s.id for s in mcp_server.SESSION.state.skills})

    def test_quest_starts_at_floor_1(self):
        # 冷开局首要任务是"破局"，攻略首领是后话
        q = mcp_server.get_state()["state_context"]["quest_log"][0]
        self.assertEqual(q["id"], "break_the_deadlock")
        self.assertEqual(q["stage"], "penniless")

    def test_grant_xp_levels_up_skill(self):
        mcp_server.learn_skill("sword_mastery")
        r = mcp_server.grant_xp("sword_mastery", 3, reason="清光草原杂兵")
        self.assertTrue(r["ranked_up"])
        self.assertEqual(r["rank_after"], 2)


class WorldRegistryTest(unittest.TestCase):
    """世界注册：未知世界被拒。"""

    def test_unknown_world_rejected(self):
        r = mcp_server.start_game("no_such_world")
        self.assertFalse(r["ok"])


class GmAdjudicationTest(unittest.TestCase):
    """GM 裁定权：gm_set_flag 兜底预设外的创意解法（aincrad 迷宫符文门）。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.SESSION.state.position = "labyrinth"

    def test_gm_set_flag_unlocks_locked_exit(self):
        # 迷宫北门默认锁在 labyrinth_cleared 之后
        self.assertIn("north", mcp_server.SESSION.world.get_room("labyrinth").locked_exits)
        r = mcp_server.gm_set_flag("labyrinth_cleared", True, unlock_exit="north")
        self.assertTrue(r["ok"])
        self.assertEqual(r["unlocked_exit"], "north")
        self.assertTrue(mcp_server.SESSION.state.flags.get("labyrinth_cleared"))
        self.assertNotIn("north", mcp_server.SESSION.world.get_room("labyrinth").locked_exits)
        # 解锁后玩家真能走进首领之间
        moved = mcp_server.move("north")
        self.assertTrue(moved["ok"])
        self.assertEqual(mcp_server.SESSION.state.position, "warden_gate")

    def test_gm_set_flag_without_unlock(self):
        r = mcp_server.gm_set_flag("some_story_flag", True)
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.state.flags.get("some_story_flag"))

    def test_gm_set_flag_nonexistent_exit_notes_gracefully(self):
        r = mcp_server.gm_set_flag("x", True, unlock_exit="down")
        self.assertTrue(r["ok"])
        self.assertIn("unlock_note", r)  # 优雅提示，不报错


class TacticalBossFightTest(unittest.TestCase):
    """§14-B：裂蹄殿首领战是战术战斗——前排近战牛魔王 + 后排远程巫祝。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        # 冷开局起手无武器；给一把近战 reach-1 剑（iron_sword）以测触及门控
        from core.types import InventoryItem
        mcp_server.SESSION.state.add_item(InventoryItem(
            id="iron_sword", name="铁剑", kind="tool", equip_slot="weapon",
            damage_expr="1d6", damage_type="slash", scaling={"str": 1.0}, reach=1))
        mcp_server.SESSION.state.position = "warden_gate"

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def _start_fight(self):
        r = mcp_server.call_affordance("warden_arena", "challenge")
        self.assertTrue(r["ok"])
        self.assertTrue(mcp_server.SESSION.in_combat)
        return mcp_server.SESSION.encounter

    def test_arena_spawns_tactical_with_positions(self):
        enc = self._start_fight()
        self.assertTrue(enc.action_economy)              # 行动经济开
        boss = enc.combatants["enemy_warden_gorehoof"]
        shaman = enc.combatants["enemy_horn_shaman"]
        self.assertEqual((boss.rank, boss.reach), (0, 1))     # 前排近战
        self.assertEqual(boss.max_poise, 12)                  # 破防条（R4 用）
        self.assertEqual((shaman.rank, shaman.reach), (1, 99))  # 后排远程

    def test_melee_cannot_reach_backline_shaman(self):
        self._start_fight()
        mcp_server.equip("iron_sword")  # 近战 reach 1
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_horn_shaman")
        self.assertFalse(r["ok"])
        self.assertIn("触及范围外", r["error"])

    def test_melee_reaches_front_boss(self):
        self._start_fight()
        mcp_server.equip("iron_sword")
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_warden_gorehoof")
        self.assertTrue(r["ok"])
        # 行动经济：大动用掉，回合仍在玩家（还有小动）
        self.assertEqual(r["next_actor"], "player")
        self.assertEqual(r["actions_left"], {"major": False, "minor": True})

    def test_ranged_staff_reaches_backline_shaman(self):
        from core.types import InventoryItem
        # 远程 build：辉石杖 reach 99，能点后排
        staff = mcp_server.SESSION.world.get_object("cave_glow_staff")
        mcp_server.SESSION.state.add_item(InventoryItem.from_object(staff))
        self._start_fight()
        r = mcp_server.declare_intent(
            actor="player", intent="attack",
            target="enemy_horn_shaman", weapon="cave_glow_staff")
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    unittest.main()
