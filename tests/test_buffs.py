import unittest
from unittest.mock import patch

import mcp_server


class BuffEngineTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    # ── add_improvised_buff 的 7 关校验 ──────────────────────────

    def test_improvised_roll_buff_applies_and_lists(self):
        result = mcp_server.add_improvised_buff(
            name="临战专注", desc="呼吸沉稳", polarity="buff",
            target="roll", op="add", value=2, duration=3, timing="on_check",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["bearer"], "player")
        self.assertEqual(result["timing"], "on_check")
        buffs = mcp_server.get_state()["buffs"]
        self.assertTrue(any(b["id"] == result["buff_id"] for b in buffs))

    def test_gate_value_out_of_range_rejected(self):
        result = mcp_server.add_improvised_buff(
            name="作弊", desc="", polarity="buff",
            target="roll", op="add", value=99, duration=2,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["rejected"])
        self.assertTrue(any("value" in r for r in result["reasons"]))

    def test_gate_forbidden_target_rejected(self):
        result = mcp_server.add_improvised_buff(
            name="刷钱", desc="", polarity="buff",
            target="gold", op="add", value=3, duration=2,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("target" in r for r in result["reasons"]))

    def test_gate_one_improvised_per_turn(self):
        first = mcp_server.add_improvised_buff(
            name="第一", desc="", polarity="buff",
            target="roll", op="add", value=1, duration=2,
        )
        self.assertTrue(first["ok"])
        second = mcp_server.add_improvised_buff(
            name="第二", desc="", polarity="buff",
            target="roll", op="add", value=1, duration=2,
        )
        self.assertFalse(second["ok"])
        self.assertTrue(any("每回合" in r for r in second["reasons"]))

    def test_gate_duplicate_name_rejected(self):
        self.assertTrue(mcp_server.add_improvised_buff(
            name="湿冷", desc="", polarity="debuff",
            target="roll", op="add", value=-1, duration=2,
        )["ok"])
        # advance a turn so the per-turn gate resets, isolating the dup-name gate
        mcp_server.inspect_object("teleport_crystal")
        dup = mcp_server.add_improvised_buff(
            name="湿冷", desc="", polarity="debuff",
            target="roll", op="add", value=-1, duration=2,
        )
        self.assertFalse(dup["ok"])
        self.assertTrue(any("已存在" in r for r in dup["reasons"]))

    # ── on_check buff 真正影响掷骰 ────────────────────────────────

    def test_on_check_roll_buff_changes_total(self):
        self.assertTrue(mcp_server.add_improvised_buff(
            name="专注", desc="", polarity="buff",
            target="roll", op="add", value=3, duration=3, timing="on_check",
        )["ok"])
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="撬锁", sides=20)
        self.assertEqual(rolled["raw"], 10)
        self.assertEqual(rolled["total"], 17)  # 10 + 3(on_check buff) + 4(敏)

    # ── turn_end hp buff 直接改 hp + 回合过期 ─────────────────────

    def test_turn_based_buff_expires_after_duration(self):
        self.assertTrue(mcp_server.add_improvised_buff(
            name="短暂祝福", desc="", polarity="buff",
            target="roll", op="add", value=2, duration=1, timing="on_check",
        )["ok"])
        # one narrative turn ticks expiry (duration=1 → expires this turn)
        mcp_server.inspect_object("teleport_crystal")
        buffs = mcp_server.get_state()["buffs"]
        self.assertFalse(any(b["name"] == "短暂祝福" for b in buffs))

    # ── remove_buff 清理 buff 及其 modifier ──────────────────────

    def test_remove_buff_clears_modifier_from_pool(self):
        created = mcp_server.add_improvised_buff(
            name="缓回血", desc="", polarity="buff",
            target="hp", op="add", value=1, duration=4, timing="turn_start",
        )
        self.assertTrue(created["ok"])
        buff_id = created["buff_id"]
        # turn_start buffs push a persistent modifier into the global pool
        self.assertTrue(any(m.source_id == buff_id for m in mcp_server.SESSION.modifiers))
        removed = mcp_server.remove_buff(buff_id)
        self.assertTrue(removed["ok"])
        self.assertFalse(any(m.source_id == buff_id for m in mcp_server.SESSION.modifiers))

    def test_remove_unknown_buff_fails(self):
        result = mcp_server.remove_buff("does_not_exist")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
