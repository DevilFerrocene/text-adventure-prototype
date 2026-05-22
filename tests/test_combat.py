import unittest
from unittest.mock import patch

import mcp_server


class CombatTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    # ── start_combat：投影玩家 + 生成敌人 + initiative ──────────────

    def test_start_combat_with_canon_enemy(self):
        result = mcp_server.start_combat(canon=["dock_thug"])
        self.assertTrue(result["ok"])
        enc = result["encounter"]
        self.assertTrue(enc["active"])
        ids = {c["id"] for c in enc["combatants"]}
        self.assertIn("player", ids)
        self.assertIn("enemy_dock_thug", ids)
        # player always acts first in initiative
        self.assertEqual(enc["turn_order"][0], "player")

    def test_start_combat_unknown_enemy_fails(self):
        result = mcp_server.start_combat(canon=["no_such_enemy"])
        self.assertFalse(result["ok"])

    def test_cannot_start_combat_twice(self):
        self.assertTrue(mcp_server.start_combat(canon=["dock_thug"])["ok"])
        again = mcp_server.start_combat(canon=["dock_thug"])
        self.assertFalse(again["ok"])

    def test_improvised_enemy_count_spawns_multiple(self):
        result = mcp_server.start_combat(
            improvised=[{"name": "醉汉", "archetype": "brute_low", "count": 2}]
        )
        self.assertTrue(result["ok"])
        enemies = [c for c in result["encounter"]["combatants"] if c["side"] == "enemy"]
        self.assertEqual(len(enemies), 2)

    def test_unknown_archetype_fails(self):
        result = mcp_server.start_combat(
            improvised=[{"name": "X", "archetype": "godzilla", "count": 1}]
        )
        self.assertFalse(result["ok"])

    # ── declare_intent attack：命中判定 + 伤害 + 死亡 ──────────────

    def test_attack_hit_deals_damage(self):
        mcp_server.start_combat(canon=["dock_thug"])
        # pad the thug's hp so a single crit hit wounds rather than kills,
        # keeping combat live so the encounter snapshot still has combatants
        thug = mcp_server.SESSION.encounter.combatants["enemy_dock_thug"]
        thug.hp = thug.max_hp = 50
        # crit-success roll (nat 20) guarantees a hit; fixed damage roll
        with patch("mcp_server.random.randint", return_value=20):
            result = mcp_server.declare_intent(
                actor="player", intent="attack", target="enemy_dock_thug"
            )
        self.assertTrue(result["ok"])
        kinds = [e["kind"] for e in result["events"]]
        self.assertIn("hit", kinds)
        thug_snap = next(c for c in result["encounter"]["combatants"]
                         if c["id"] == "enemy_dock_thug")
        self.assertLess(thug_snap["hp"], thug_snap["max_hp"])

    def test_attack_miss_no_damage(self):
        mcp_server.start_combat(canon=["dock_thug"])
        # nat 1 is a critical failure → miss regardless of AC
        with patch("mcp_server.random.randint", return_value=1):
            result = mcp_server.declare_intent(
                actor="player", intent="attack", target="enemy_dock_thug"
            )
        self.assertTrue(result["ok"])
        kinds = [e["kind"] for e in result["events"]]
        self.assertIn("miss", kinds)
        thug = next(c for c in result["encounter"]["combatants"]
                    if c["id"] == "enemy_dock_thug")
        self.assertEqual(thug["hp"], thug["max_hp"])

    def test_killing_only_enemy_ends_combat(self):
        # 1-hp improvised enemy dies to any hit and ends the encounter
        mcp_server.start_combat(
            improvised=[{"name": "纸人", "archetype": "brute_low", "count": 1}]
        )
        enemy_id = next(
            c["id"] for c in mcp_server._encounter_snapshot()["combatants"]
            if c["side"] == "enemy"
        )
        # force the enemy to 1 hp so one hit kills
        mcp_server.SESSION.encounter.combatants[enemy_id].hp = 1
        with patch("mcp_server.random.randint", return_value=20):
            result = mcp_server.declare_intent(
                actor="player", intent="attack", target=enemy_id
            )
        self.assertTrue(result["ok"])
        kinds = [e["kind"] for e in result["events"]]
        self.assertIn("kill", kinds)
        self.assertTrue(result["encounter"].get("combat_ended"))
        self.assertFalse(mcp_server.SESSION.in_combat)

    def test_declare_intent_wrong_turn_rejected(self):
        mcp_server.start_combat(canon=["dock_thug"])
        # not the enemy's turn yet (player is active)
        result = mcp_server.declare_intent(
            actor="enemy_dock_thug", intent="attack", target="player"
        )
        self.assertFalse(result["ok"])

    def test_defend_grants_temp_ac(self):
        mcp_server.start_combat(canon=["dock_thug"])
        before = next(c for c in mcp_server._encounter_snapshot()["combatants"]
                      if c["id"] == "player")["ac"]
        result = mcp_server.declare_intent(actor="player", intent="defend")
        self.assertTrue(result["ok"])
        after = next(c for c in result["encounter"]["combatants"]
                     if c["id"] == "player")["ac"]
        self.assertEqual(after, before + 2)

    # ── 敌人 buff 在战斗轮 tick（流血/灼烧）───────────────────────

    def test_enemy_hp_buff_ticks_each_round(self):
        mcp_server.start_combat(canon=["dock_thug"])
        bleed = mcp_server.add_improvised_buff(
            name="流血", desc="伤口不止", polarity="debuff",
            target="hp", op="add", value=-2, duration=5,
            timing="turn_start", bearer_id="enemy_dock_thug",
        )
        self.assertTrue(bleed["ok"])
        thug = mcp_server.SESSION.encounter.combatants["enemy_dock_thug"]
        hp_before = thug.hp
        # player then enemy act → wrap to player bumps the round → tick
        with patch("mcp_server.random.randint", return_value=1):
            mcp_server.declare_intent(actor="player", intent="defend")
            mcp_server.declare_intent(
                actor="enemy_dock_thug", intent="attack", target="player"
            )
        self.assertLess(thug.hp, hp_before)

    # ── end_combat 写回玩家 hp ────────────────────────────────────

    def test_end_combat_writes_back_player_hp(self):
        mcp_server.start_combat(canon=["dock_thug"])
        player = mcp_server.SESSION.encounter.combatants["player"]
        player.hp = 3
        result = mcp_server.end_combat(reason="负伤撤退")
        self.assertTrue(result["ok"])
        self.assertEqual(mcp_server.SESSION.state.vitals.hp, 3)
        self.assertFalse(mcp_server.SESSION.in_combat)


class ActionEconomyTest(unittest.TestCase):
    """§14-R2：action_economy=True 下，每回合 1 大动 + 1 小动。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.start_combat(canon=["dock_thug"])
        self.enc = mcp_server.SESSION.encounter
        self.enc.action_economy = True
        # 敌人血量拉满，避免一刀斩杀提前结束遭遇
        thug = self.enc.combatants["enemy_dock_thug"]
        thug.hp = thug.max_hp = 999

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_major_keeps_turn_then_minor_advances(self):
        # 大动（攻击）后回合不过，仍是 player，且小动可用
        r1 = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_dock_thug")
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["next_actor"], "player")
        self.assertEqual(r1["actions_left"], {"major": False, "minor": True})
        # 小动（走位）耗尽第二槽 → 回合推进给敌人
        r2 = mcp_server.declare_intent(
            actor="player", intent="move", target="retreat")
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["next_actor"], "enemy_dock_thug")

    def test_second_major_rejected(self):
        mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_dock_thug")
        r = mcp_server.declare_intent(
            actor="player", intent="defend")
        self.assertFalse(r["ok"])
        self.assertIn("大动", r["error"])

    def test_end_turn_forfeits_remaining(self):
        # 直接 end_turn，放弃两槽 → 立刻轮到敌人
        r = mcp_server.declare_intent(actor="player", intent="end_turn")
        self.assertTrue(r["ok"])
        self.assertEqual(r["next_actor"], "enemy_dock_thug")

    def test_move_changes_rank_and_clamps(self):
        self.enc.rank_depth = 2
        player = self.enc.combatants["player"]
        player.rank = 0
        r = mcp_server.declare_intent(
            actor="player", intent="move", target="retreat")
        self.assertTrue(r["ok"])
        self.assertEqual(player.rank, 1)
        # 再退一步被 rank_depth 钳制（仍是同回合的大动尚未用，回合不过）
        # 此时小动已用完，move 应被拒
        r2 = mcp_server.declare_intent(
            actor="player", intent="move", target="retreat")
        self.assertFalse(r2["ok"])
        self.assertIn("小动", r2["error"])

    def test_next_actor_slots_reset(self):
        # 玩家用满两槽推进 → 敌人回合开始，敌人两槽应为初始 False
        mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_dock_thug")
        mcp_server.declare_intent(actor="player", intent="end_turn")
        thug = self.enc.combatants["enemy_dock_thug"]
        self.assertFalse(thug.acted_major)
        self.assertFalse(thug.acted_minor)

    def test_legacy_mode_unchanged(self):
        # action_economy=False 时，一动即过（回归保证）
        self.enc.action_economy = False
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_dock_thug")
        self.assertTrue(r["ok"])
        self.assertEqual(r["next_actor"], "enemy_dock_thug")

    def test_reach_gates_attack_out_of_range(self):
        # 近战 reach=1：玩家在前排(0)，敌人在后排(1) → gap=1≥reach → 打不到
        player = self.enc.combatants["player"]
        thug = self.enc.combatants["enemy_dock_thug"]
        player.rank, player.reach = 0, 1
        thug.rank = 1
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_dock_thug")
        self.assertFalse(r["ok"])
        self.assertIn("触及范围外", r["error"])
        # 敌人移到前排 → gap=0 < reach → 可打
        thug.rank = 0
        r2 = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_dock_thug")
        self.assertTrue(r2["ok"])

    def test_default_reach_unlimited(self):
        # 默认 reach=99：无论排位都打得到（现状行为）
        player = self.enc.combatants["player"]
        thug = self.enc.combatants["enemy_dock_thug"]
        player.rank, thug.rank = 0, 1
        self.assertEqual(player.reach, 99)
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_dock_thug")
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    unittest.main()
