import unittest
from unittest.mock import patch

import mcp_server


class LearnSkillTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def test_learn_skill_adds_to_state(self):
        result = mcp_server.learn_skill("stealth_training")
        self.assertTrue(result["ok"])
        self.assertEqual(result["learned"]["id"], "stealth_training")
        self.assertEqual(result["learned"]["rank"], 1)
        skills = mcp_server.get_state()["state_context"]["skills"]
        self.assertTrue(any(s["id"] == "stealth_training" for s in skills))

    def test_learn_unknown_skill_fails(self):
        result = mcp_server.learn_skill("no_such_skill")
        self.assertFalse(result["ok"])

    def test_cannot_learn_same_skill_twice(self):
        self.assertTrue(mcp_server.learn_skill("stealth_training")["ok"])
        again = mcp_server.learn_skill("stealth_training")
        self.assertFalse(again["ok"])

    def test_learned_skill_is_independent_clone(self):
        # 学两局，给一局加 xp，模板和另一局不受影响
        mcp_server.learn_skill("stealth_training")
        mcp_server.grant_xp("stealth_training", 5)
        # 模板未被污染：新开一局重新学，xp 应为 0
        mcp_server.start_game()
        mcp_server.learn_skill("stealth_training")
        sk = mcp_server.get_state()["state_context"]["skills"][0]
        self.assertEqual(sk["xp"], 0)


class PassiveModifierTest(unittest.TestCase):
    """passive_modifiers 在相关掷骰自动生效，进 audit trail。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.modifiers.clear()

    def test_passive_applies_to_matching_roll(self):
        mcp_server.learn_skill("stealth_training")  # 潜行/察觉 +2
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="潜行躲过守卫", sides=20)
        self.assertEqual(rolled["raw"], 10)
        self.assertEqual(rolled["total"], 15)  # 10 + 2(潜行passive) + 3(敏)

    def test_passive_does_not_apply_to_unrelated_roll(self):
        mcp_server.learn_skill("stealth_training")
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="撬锁", sides=20)
        self.assertEqual(rolled["total"], 13)  # selector 不匹配，无被动加值，但敏+3

    def test_passive_shows_in_audit_trail(self):
        mcp_server.learn_skill("stealth_training")
        with patch("mcp_server.random.randint", return_value=8):
            mcp_server.roll_check(reason="察觉暗处的动静", sides=20)
        audit = mcp_server.explain_last_roll()
        self.assertTrue(audit["ok"])
        joined = " ".join(audit["modifiers_full"])
        self.assertIn("潜行训练", joined)

    def test_no_passive_without_skill(self):
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="潜行", sides=20)
        self.assertEqual(rolled["total"], 13)  # 10 + 3(敏)


class GrantXpRankUpTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        self.assertTrue(mcp_server.learn_skill("stealth_training")["ok"])

    def test_xp_accumulates(self):
        r = mcp_server.grant_xp("stealth_training", 2, reason="蹲点观察")
        self.assertTrue(r["ok"])
        self.assertEqual(r["total_xp"], 2)
        self.assertFalse(r["ranked_up"])
        self.assertEqual(r["rank_after"], 1)

    def test_crossing_threshold_ranks_up(self):
        # 默认阈值 [3,10,25]；给 3 xp 应升到 rank 2
        r = mcp_server.grant_xp("stealth_training", 3, reason="完成潜入任务")
        self.assertTrue(r["ranked_up"])
        self.assertEqual(r["rank_after"], 2)

    def test_big_xp_multi_rank(self):
        r = mcp_server.grant_xp("stealth_training", 25)
        self.assertEqual(r["rank_after"], 4)  # 跨过 3/10/25 三道阈值

    def test_grant_xp_unknown_skill_fails(self):
        r = mcp_server.grant_xp("not_learned", 5)
        self.assertFalse(r["ok"])

    def test_nonpositive_xp_rejected(self):
        r = mcp_server.grant_xp("stealth_training", 0)
        self.assertFalse(r["ok"])


class SkillSaveLoadTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def test_skill_round_trips_through_save(self):
        mcp_server.learn_skill("stealth_training")
        mcp_server.grant_xp("stealth_training", 3)  # rank 2
        saved = mcp_server.save_game("skill_save_test")
        self.assertTrue(saved["ok"])

        loaded = mcp_server.load_game("skill_save_test")
        self.assertTrue(loaded["ok"])
        skills = loaded["state_context"]["skills"]
        sk = next(s for s in skills if s["id"] == "stealth_training")
        self.assertEqual(sk["rank"], 2)
        self.assertEqual(sk["xp"], 3)

        # 载入后 passive 仍生效
        mcp_server.SESSION.modifiers.clear()
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="潜行", sides=20)
        self.assertEqual(rolled["total"], 15)  # 10 + 2(rank2潜行被动) + 3(敏)

        from pathlib import Path
        Path(saved["path"]).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
