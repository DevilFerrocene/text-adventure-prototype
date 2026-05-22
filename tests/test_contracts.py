"""§12 危机合约：take_contract → 强化敌人 → 胜利按难度确定性缩放奖励。"""
import unittest

import mcp_server


class TakeContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_take_contract_stores_pending_with_scaling(self):
        r = mcp_server.take_contract(["bulwark", "aegis"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["contract"]["clauses"], ["bulwark", "aegis"])
        self.assertEqual(r["contract"]["difficulty"], 4)        # 2 + 2
        self.assertEqual(r["contract"]["reward_mult"], 1.8)     # 1 + 0.2*4
        self.assertEqual(mcp_server.SESSION.state.pending_contract["difficulty"], 4)

    def test_unknown_clause_dropped_valid_kept(self):
        r = mcp_server.take_contract(["fury", "nonsense"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["contract"]["clauses"], ["fury"])
        self.assertIn("nonsense", r["unknown"])

    def test_no_valid_clause_returns_available(self):
        r = mcp_server.take_contract(["nope"])
        self.assertFalse(r["ok"])
        ids = {c["id"] for c in r["available"]}
        self.assertEqual(ids, {"fury", "bulwark", "aegis", "swift"})

    def test_duplicate_clauses_collapsed(self):
        r = mcp_server.take_contract(["fury", "fury"])
        self.assertEqual(r["contract"]["clauses"], ["fury"])

    def test_cannot_take_contract_in_combat(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        r = mcp_server.take_contract(["fury"])
        self.assertFalse(r["ok"])


class ContractApplyTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_clauses_buff_enemy_stats_at_spawn(self):
        base = mcp_server.SESSION.world.get_enemy("frenzy_boar")
        mcp_server.take_contract(["bulwark", "aegis", "fury", "swift"])
        mcp_server.start_combat(canon=["frenzy_boar"])
        e = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        self.assertEqual(e.max_hp, round(base.hp * 1.5))   # bulwark ×1.5
        self.assertEqual(e.ac, base.ac + 3)                # aegis +3
        self.assertEqual(e.speed, base.speed + 6)          # swift +6
        self.assertEqual(e.damage_expr, base.damage_expr + "+2")  # fury +2

    def test_contract_consumed_and_attached_to_encounter(self):
        mcp_server.take_contract(["fury"])
        mcp_server.start_combat(canon=["frenzy_boar"])
        self.assertIsNone(mcp_server.SESSION.state.pending_contract)  # 用掉即清
        self.assertIsNotNone(mcp_server.SESSION.encounter.contract)

    def test_contract_does_not_touch_player(self):
        before = mcp_server.SESSION.state.vitals
        hp0, ac0, spd0 = before.hp, before.ac, before.speed
        mcp_server.take_contract(["bulwark", "aegis", "swift"])
        mcp_server.start_combat(canon=["frenzy_boar"])
        p = mcp_server.SESSION.encounter.combatants["player"]
        # 玩家投影血量/AC/速度不被契约改动（契约只强化敌人）
        self.assertEqual(p.max_hp, before.max_hp)
        self.assertEqual(p.speed, spd0)

    def test_only_next_fight_affected(self):
        mcp_server.take_contract(["fury"])
        mcp_server.start_combat(canon=["frenzy_boar"])
        mcp_server.end_combat(reason="done")
        # 第二场没有契约
        base = mcp_server.SESSION.world.get_enemy("frenzy_boar")
        mcp_server.start_combat(canon=["frenzy_boar"])
        e = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        self.assertEqual(e.damage_expr, base.damage_expr)  # 无 +2
        self.assertIsNone(mcp_server.SESSION.encounter.contract)


class ContractRewardTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_victory_scales_xp_and_grants_bonus_gold(self):
        mcp_server.take_contract(["fury", "bulwark"])   # 难度 4 → ×1.8，金币 +80
        mcp_server.start_combat(canon=["frenzy_boar"])
        gold0 = mcp_server.SESSION.state.vitals.gold
        # 击杀全敌 → 胜利
        mcp_server.deal_damage(target="enemy_frenzy_boar", amount=999)
        res = mcp_server.end_combat(reason="victory")
        cb = res["contract_bonus"]
        self.assertIsNotNone(cb)
        self.assertEqual(cb["difficulty"], 4)
        self.assertEqual(cb["reward_mult"], 1.8)
        self.assertEqual(cb["scaled_char_xp"], round(cb["base_char_xp"] * 1.8))
        self.assertEqual(cb["bonus_gold"], 80)
        self.assertEqual(mcp_server.SESSION.state.vitals.gold - gold0, 80)

    def test_no_bonus_without_victory(self):
        mcp_server.take_contract(["fury", "bulwark"])
        mcp_server.start_combat(canon=["frenzy_boar"])
        # 敌人没死就结束（撤退/手动）→ 无奖励缩放
        res = mcp_server.end_combat(reason="撤退")
        self.assertIsNone(res["contract_bonus"])


class ContractSaveLoadTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_pending_contract_round_trips(self):
        mcp_server.take_contract(["fury", "aegis"])
        saved = mcp_server.save_game("contract_save_test")
        self.assertTrue(saved["ok"])
        loaded = mcp_server.load_game("contract_save_test")
        self.assertTrue(loaded["ok"])
        pc = mcp_server.SESSION.state.pending_contract
        self.assertIsNotNone(pc)
        self.assertEqual(pc["clauses"], ["fury", "aegis"])
        from pathlib import Path
        Path(saved["path"]).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
