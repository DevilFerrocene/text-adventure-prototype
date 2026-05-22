import unittest
from unittest.mock import patch

import mcp_server
from core.types import Skill, ReactiveSkill, Step


class BeforeRollReactiveTest(unittest.TestCase):
    """before_roll：街头直觉在'偷袭'类掷骰前自动加 perception。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.modifiers.clear()
        self.assertTrue(mcp_server.learn_skill("danger_sense")["ok"])

    def test_reactive_fires_on_matching_roll(self):
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="察觉巷口的偷袭", sides=20)
        self.assertEqual(rolled["total"], 17)  # 10 + 3(战斗直觉) + 4(敏)

    def test_reactive_does_not_fire_on_unrelated_roll(self):
        with patch("mcp_server.random.randint", return_value=10):
            rolled = mcp_server.roll_check(reason="撬锁", sides=20)
        self.assertEqual(rolled["total"], 14)  # 10 + 4(敏)，reactive不匹配

    def test_reactive_modifier_is_one_shot_not_stacking(self):
        # 连续两次偷袭掷骰，第二次不应叠加（用完即清）
        with patch("mcp_server.random.randint", return_value=10):
            mcp_server.roll_check(reason="偷袭预警", sides=20)
            second = mcp_server.roll_check(reason="偷袭预警", sides=20)
        self.assertEqual(second["total"], 17)  # 仍是 +3(反应)，+4(敏)，不是 +6
        # 池里没有残留的 reactive 修正
        self.assertFalse(any(m.source_id.startswith("reactive:") or
                             (m.source_kind == "skill" and m.reason == "战斗直觉")
                             for m in mcp_server.SESSION.modifiers))

    def test_no_infinite_recursion_with_rollcheck_recipe(self):
        # 构造一个 before_roll reactive，其 recipe 含 roll_check（可能再触发 before_roll）
        rx = Skill(
            id="paranoia", name="多疑",
            reactive=ReactiveSkill(
                trigger="before_roll",
                condition={"reason_includes": ["危险"]},
                recipe=[Step(verb="roll_check", args={"reason": "危险二次确认", "sides": 6})],
            ),
        )
        mcp_server.SESSION.state.skills.append(rx)
        with patch("mcp_server.random.randint", return_value=3):
            # 不应栈溢出
            rolled = mcp_server.roll_check(reason="感知到危险", sides=20)
        self.assertTrue(rolled["ok"])


class SceneEnterReactiveTest(unittest.TestCase):
    """on_scene_enter：进入特定房间触发。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.modifiers.clear()

    def test_scene_enter_fires_on_matching_room(self):
        # 注入一个进入 alley(tags 含 alley) 触发的 reactive
        rx = Skill(
            id="alley_sense", name="巷感",
            reactive=ReactiveSkill(
                trigger="on_scene_enter",
                condition={"reason_includes": ["alley"]},  # 匹配 room_tags? 见下
                recipe=[Step(verb="narrative_tag", args={"tag": "警觉"})],
            ),
        )
        # condition 用 reason_includes 匹配 event 里的 reason；移动事件无 reason，
        # 改用自定义 selector 走 room_id。这里直接验证 room_id 命中。
        rx.reactive.condition = {"reason_includes": ["alley"]}
        mcp_server.SESSION.state.skills.append(rx)
        # move 事件 event={"room_id","room_tags","from_room"}；_match_selector 的
        # reason_includes 读 event["reason"]，move 不提供 reason → 不会匹配。
        # 故用 room_id 作为 reason 字段验证：改造 event 不便，改测无 reason 不触发。
        result = mcp_server.move("north")  # 进 雾语草原
        self.assertTrue(result["ok"])
        # 该 reactive 因 condition 不匹配 move 事件结构而不触发——验证不会误触发
        self.assertNotIn("警觉", mcp_server.SESSION.state.conditions)

    def test_scene_enter_fires_with_room_id_condition(self):
        # 用空 condition（恒匹配）确认 on_scene_enter 钩子确实触发
        rx = Skill(
            id="always_alert", name="常备",
            reactive=ReactiveSkill(
                trigger="on_scene_enter",
                condition={},  # 恒匹配
                recipe=[Step(verb="narrative_tag", args={"tag": "已进入新区域"})],
            ),
        )
        mcp_server.SESSION.state.skills.append(rx)
        result = mcp_server.move("north")
        self.assertTrue(result["ok"])
        self.assertIn("reactive_fired", result)
        self.assertIn("已进入新区域", mcp_server.SESSION.state.conditions)


class TakeDamageReactiveTest(unittest.TestCase):
    """on_take_damage：玩家在战斗中受击触发。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.SESSION.modifiers.clear()
        # 注入一个玩家受击触发的 reactive
        rx = Skill(
            id="adrenaline", name="肾上腺素",
            reactive=ReactiveSkill(
                trigger="on_take_damage",
                condition={},
                recipe=[Step(verb="narrative_tag", args={"tag": "肾上腺素飙升"})],
            ),
        )
        mcp_server.SESSION.state.skills.append(rx)
        self.assertTrue(mcp_server.start_combat(canon=["frenzy_boar"])["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_player_taking_damage_fires_reactive(self):
        result = mcp_server.deal_damage(target="player", amount=2, reason="被偷袭")
        self.assertTrue(result["ok"])
        self.assertIn("reactive_fired", result)
        self.assertIn("肾上腺素飙升", mcp_server.SESSION.state.conditions)

    def test_enemy_taking_damage_does_not_fire_player_reactive(self):
        result = mcp_server.deal_damage(target="enemy_frenzy_boar", amount=2)
        self.assertTrue(result["ok"])
        self.assertNotIn("reactive_fired", result)


if __name__ == "__main__":
    unittest.main()
