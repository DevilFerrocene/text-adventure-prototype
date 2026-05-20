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


if __name__ == "__main__":
    unittest.main()
