"""callable_verbs：get_scene 暴露此刻真正能调的 verb，GM 不必猜/试。"""
import unittest

import mcp_server


def _obj(scene, oid):
    return next(o for o in scene["objects"] if o["id"] == oid)


class CallableVerbsTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def test_callable_verbs_present_on_each_object(self):
        sc = mcp_server.get_scene()["scene"]
        for o in sc["objects"]:
            self.assertIn("callable_verbs", o)
            self.assertIn("inspect", o["callable_verbs"])  # inspect 永远可用

    def test_callable_verbs_match_actual_affordances(self):
        sc = mcp_server.get_scene()["scene"]
        letter = _obj(sc, "field_notes")
        # 信件的真实可调动作
        for v in ("read", "tear", "burn"):
            self.assertIn(v, letter["callable_verbs"])
        # takable 物有 take
        self.assertIn("take", letter["callable_verbs"])

    def test_semantic_methods_not_in_callable_verbs(self):
        # base_methods 里的纯语义词（如 copy/compare/confront）不应混进 callable_verbs
        sc = mcp_server.get_scene()["scene"]
        letter = _obj(sc, "field_notes")
        noise = set(letter["base_methods"]) - set(letter["callable_verbs"])
        # base_methods 比 callable_verbs 多（有语义噪声），证明两者已区分
        self.assertTrue(noise, "base_methods 应含 callable_verbs 之外的语义词")
        # 且这些语义词调了确实报错（证明它们不是真动作）
        for v in noise:
            if v == "inspect":
                continue
            r = mcp_server.call_affordance("field_notes", v)
            self.assertFalse(r["ok"])

    def test_every_callable_verb_actually_works(self):
        # callable_verbs 里的每个 verb（除 take 改背包外）调用都不该因"无此方法"失败
        sc = mcp_server.get_scene()["scene"]
        letter = _obj(sc, "field_notes")
        for v in letter["callable_verbs"]:
            if v in ("inspect", "take"):
                continue
            r = mcp_server.call_affordance("field_notes", v)
            # 可能因 consume_self 后续不可重复，但首次调用应 ok
            self.assertTrue(r["ok"], f"{v} 应可调用")
            mcp_server.start_game()  # 重置，逐个独立验证

    def test_callable_verbs_respect_requires_flag(self):
        # rune_door 的 solve 有前置 flag(read_wall_glyph)，未满足时不出现在 callable_verbs
        mcp_server.SESSION.state.position = "labyrinth"
        rd = _obj(mcp_server.get_scene()["scene"], "rune_door")
        self.assertNotIn("solve", rd["callable_verbs"])   # 需先读懂墙上刻印

        mcp_server.SESSION.state.flags["read_wall_glyph"] = True
        rd2 = _obj(mcp_server.get_scene()["scene"], "rune_door")
        self.assertIn("solve", rd2["callable_verbs"])     # 满足前置后现身

    def test_wrong_verb_error_lists_available(self):
        # 万一猜错，报错带可用清单（兜底，让 GM 一次纠正）
        r = mcp_server.call_affordance("field_notes", "open")
        self.assertFalse(r["ok"])
        self.assertIn("read", r["error"])  # 列出了真实可用 verb


if __name__ == "__main__":
    unittest.main()
