import unittest
from unittest.mock import patch

import mcp_server


class UseSkillTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.modifiers.clear()
        # 给玩家耐力以施放潜行术（cost stamina:2）
        mcp_server.SESSION.state.vitals.stamina = 5
        mcp_server.SESSION.state.vitals.max_stamina = 5
        self.assertTrue(mcp_server.learn_skill("stealth_art")["ok"])

    def test_use_active_skill_pays_cost_and_runs_recipe(self):
        result = mcp_server.use_skill("stealth_art")
        self.assertTrue(result["ok"])
        # 扣了 2 耐力
        self.assertEqual(mcp_server.SESSION.state.vitals.stamina, 3)
        # recipe 跑了 2 步：apply_buff + narrative_tag
        verbs = [s["verb"] for s in result["steps"]]
        self.assertIn("apply_buff", verbs)
        self.assertIn("narrative_tag", verbs)

    def test_apply_buff_step_creates_working_buff(self):
        mcp_server.use_skill("stealth_art")
        # 挂上的 "隐入暗处" buff 让潜行检定 +5
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="潜行穿过院子", sides=20)
        self.assertEqual(rolled["total"], 15)  # 10 + 5

    def test_narrative_tag_step_adds_condition(self):
        mcp_server.use_skill("stealth_art")
        self.assertIn("隐匿中", mcp_server.SESSION.state.conditions)

    def test_cooldown_blocks_immediate_reuse(self):
        self.assertTrue(mcp_server.use_skill("stealth_art")["ok"])
        again = mcp_server.use_skill("stealth_art")
        self.assertFalse(again["ok"])
        self.assertIn("冷却", again["error"])

    def test_cooldown_decrements_over_turns(self):
        mcp_server.use_skill("stealth_art")  # cooldown 3
        skill = mcp_server._get_skill(mcp_server.SESSION.state, "stealth_art")
        self.assertEqual(skill.active.remaining_cooldown, 3)
        # 推进 3 个叙事回合
        for _ in range(3):
            mcp_server.inspect_object("cracked_window")
        self.assertEqual(skill.active.remaining_cooldown, 0)
        # 冷却结束后可再用
        self.assertTrue(mcp_server.use_skill("stealth_art")["ok"])

    def test_insufficient_stamina_rejected(self):
        mcp_server.SESSION.state.vitals.stamina = 1  # 不够 cost 2
        result = mcp_server.use_skill("stealth_art")
        self.assertFalse(result["ok"])
        self.assertIn("耐力", result["error"])
        # 失败不扣资源
        self.assertEqual(mcp_server.SESSION.state.vitals.stamina, 1)

    def test_use_unlearned_skill_fails(self):
        result = mcp_server.use_skill("street_instinct")  # 没学
        self.assertFalse(result["ok"])

    def test_use_passive_only_skill_fails(self):
        mcp_server.learn_skill("stealth_training")  # 纯 passive
        result = mcp_server.use_skill("stealth_training")
        self.assertFalse(result["ok"])
        self.assertIn("没有主动效果", result["error"])


class StepExecutorTest(unittest.TestCase):
    """直接测 _run_recipe 各 verb 与分支。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.modifiers.clear()

    def test_emit_modifier_step(self):
        from core.types import Step
        steps = _ = mcp_server._run_recipe(
            [Step(verb="emit_modifier",
                  args={"target": "roll", "op": "add", "value": 4, "reason": "测试"})],
            source="test",
        )
        self.assertTrue(steps[0]["ok"])
        # 修正进了池
        self.assertTrue(any(m.reason == "测试" for m in mcp_server.SESSION.modifiers))

    def test_spawn_improvised_step(self):
        from core.types import Step
        steps = mcp_server._run_recipe(
            [Step(verb="spawn_improvised", args={"name": "烟雾弹", "category": "tool"})],
            source="test",
        )
        self.assertTrue(steps[0]["ok"])
        self.assertTrue(any("烟雾弹" in i.name for i in mcp_server.SESSION.state.inventory))

    def test_unknown_verb_rejected(self):
        from core.types import Step
        steps = mcp_server._run_recipe(
            [Step(verb="launch_nuke", args={})], source="test"
        )
        self.assertFalse(steps[0]["ok"])
        self.assertIn("白名单", steps[0]["error"])

    def test_roll_check_branch_on_success(self):
        from core.types import Step
        # nat 20 → success → 走 on_success 子步
        recipe = [
            Step(verb="roll_check", args={"reason": "撬锁", "sides": 20, "dc": 10},
                 on_success=[Step(verb="narrative_tag", args={"tag": "锁开了"})],
                 on_failure=[Step(verb="narrative_tag", args={"tag": "失败了"})]),
        ]
        with patch("mcp_server.random.randint", return_value=20):
            steps = mcp_server._run_recipe(recipe, source="test")
        self.assertTrue(steps[0]["success"])
        self.assertIn("锁开了", mcp_server.SESSION.state.conditions)
        self.assertNotIn("失败了", mcp_server.SESSION.state.conditions)

    def test_roll_check_branch_on_failure(self):
        from core.types import Step
        recipe = [
            Step(verb="roll_check", args={"reason": "撬锁", "sides": 20, "dc": 18},
                 on_success=[Step(verb="narrative_tag", args={"tag": "锁开了"})],
                 on_failure=[Step(verb="narrative_tag", args={"tag": "失败了"})]),
        ]
        with patch("mcp_server.random.randint", return_value=1):  # nat 1 → crit fail
            steps = mcp_server._run_recipe(recipe, source="test")
        self.assertFalse(steps[0]["success"])
        self.assertIn("失败了", mcp_server.SESSION.state.conditions)


if __name__ == "__main__":
    unittest.main()
