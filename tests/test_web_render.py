"""Web 富 UI：从工具结果抽结构面板 + 散文模式提示词。"""
import unittest

from standalone.web import _render_events
from standalone.prompt import load_system_prompt


class RenderEventsTest(unittest.TestCase):
    def test_scene_extracted_excludes_locked_exits(self):
        result = {"scene": {
            "objects": [{"name": "武器架"}, {"name": "篝火"}],
            "exits": {"north": {"target": "plains", "locked": False},
                      "in": {"target": "hut", "locked": True}}}}
        d = dict(_render_events("get_scene", result))
        self.assertEqual(d["scene"]["objects"], ["武器架", "篝火"])
        self.assertEqual(d["scene"]["exits"], ["north"])   # 锁住的 in 排除

    def test_dice_extracted(self):
        d = dict(_render_events("explain_last_roll",
                                {"line_format": "📊 测试 d20=19 +4 = 23", "outcome": "success"}))
        self.assertIn("dice", d)
        self.assertEqual(d["dice"]["outcome"], "success")
        self.assertIn("d20=19", d["dice"]["line"])

    def test_combat_extracted(self):
        result = {"encounter": {
            "active": True, "round": 2, "active_combatant": "player",
            "combatants": [
                {"id": "player", "name": "你", "hp": 6, "max_hp": 6,
                 "side": "player", "is_dead": False},
                {"id": "enemy_killer_rabbit", "name": "杀人兔", "hp": 3, "max_hp": 8,
                 "side": "enemy", "is_dead": False}]}}
        d = dict(_render_events("declare_intent", result))
        self.assertEqual(d["combat"]["round"], 2)
        self.assertEqual(d["combat"]["active"], "player")
        self.assertEqual(len(d["combat"]["combatants"]), 2)

    def test_inactive_encounter_no_combat_card(self):
        d = dict(_render_events("get_state", {"encounter": {"active": False}}))
        self.assertNotIn("combat", d)

    def test_non_dict_result_safe(self):
        self.assertEqual(_render_events("x", "not a dict"), [])
        self.assertEqual(_render_events("x", None), [])

    def test_plain_result_yields_nothing(self):
        self.assertEqual(_render_events("learn_skill", {"ok": True, "learned": {}}), [])


class PromptModeTest(unittest.TestCase):
    def test_rich_ui_appends_override(self):
        p = load_system_prompt(rich_ui=True)
        self.assertIn("富 UI 覆盖", p)
        self.assertIn("只写叙事散文", p)

    def test_default_keeps_paste_instructions(self):
        p = load_system_prompt(rich_ui=False)
        self.assertNotIn("富 UI 覆盖", p)


if __name__ == "__main__":
    unittest.main()
