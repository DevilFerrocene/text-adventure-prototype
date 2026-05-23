"""软重生：死亡 → 回满血 + 掉一半金币 + 拽回营地水晶。"""
import unittest
from unittest.mock import patch

import mcp_server


class RespawnToolTest(unittest.TestCase):
    """respawn 工具：探索/叙事死亡由 GM 裁定后收尾。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_respawn_restores_hp_halves_gold_returns_to_camp(self):
        st = mcp_server.SESSION.state
        st.vitals.max_hp = 6
        st.vitals.hp = 1
        st.vitals.gold = 10
        st.position = "labyrinth"   # 死在迷宫里
        r = mcp_server.respawn(reason="踩中陷阱")
        self.assertTrue(r["ok"])
        self.assertEqual(st.vitals.hp, 6)         # 回满血
        self.assertEqual(st.vitals.gold, 5)       # 掉一半
        self.assertEqual(st.position, "camp")     # 拽回营地
        self.assertEqual(r["gold_lost"], 5)

    def test_half_gold_floors(self):
        st = mcp_server.SESSION.state
        st.vitals.gold = 7
        mcp_server.respawn()
        self.assertEqual(st.vitals.gold, 4)       # 7 - 7//2 = 4

    def test_respawn_with_zero_gold_safe(self):
        st = mcp_server.SESSION.state
        st.vitals.gold = 0
        r = mcp_server.respawn()
        self.assertTrue(r["ok"])
        self.assertEqual(st.vitals.gold, 0)
        self.assertEqual(r["gold_lost"], 0)


class CombatDeathRespawnTest(unittest.TestCase):
    """战斗中玩家倒下 → 自动软重生。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_player_down_in_combat_auto_respawns(self):
        st = mcp_server.SESSION.state
        st.vitals.gold = 10
        st.position = "plains"
        mcp_server.start_combat(canon=["killer_rabbit"])
        enc = mcp_server.SESSION.encounter
        # 兔子拉满血不会被秒；玩家危在旦夕
        rab = enc.combatants["enemy_killer_rabbit"]
        rab.hp = rab.max_hp = 50
        enc.combatants["player"].hp = 1
        with patch("mcp_server.random.randint", return_value=20):  # 全命中
            mcp_server.declare_intent(
                actor="player", intent="attack", target="enemy_killer_rabbit")
            r = mcp_server.declare_intent(
                actor="enemy_killer_rabbit", intent="attack", target="player")
        self.assertTrue(r["player_died"])
        self.assertFalse(mcp_server.SESSION.in_combat)          # 战斗收尾
        self.assertEqual(st.position, "camp")                   # 回营地
        self.assertEqual(st.vitals.hp, st.vitals.max_hp)        # 满血
        self.assertEqual(st.vitals.gold, 5)                     # 掉一半
        self.assertIsNotNone(r["respawn"])

    def test_no_respawn_while_player_alive(self):
        mcp_server.SESSION.state.position = "plains"
        mcp_server.start_combat(canon=["killer_rabbit"])
        rab = mcp_server.SESSION.encounter.combatants["enemy_killer_rabbit"]
        rab.hp = rab.max_hp = 50
        with patch("mcp_server.random.randint", return_value=1):  # 玩家挥空，没人死
            r = mcp_server.declare_intent(
                actor="player", intent="attack", target="enemy_killer_rabbit")
        self.assertIsNone(r.get("player_died"))
        self.assertTrue(mcp_server.SESSION.in_combat)


if __name__ == "__main__":
    unittest.main()
