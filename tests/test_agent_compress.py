"""独立运行层上下文压缩：滑窗 + 旧工具结果截断 + reasoning 剥离，不破坏配对。"""
import unittest

from standalone.agent import (
    GameAgent, KEEP_RECENT_TURNS, OLD_TOOL_RESULT_CAP, HISTORY_CHAR_BUDGET,
)
from standalone.config import LLMConfig


def _agent():
    # 离线构造：OpenAI() 构造器不发网络请求；build_tools/load_system_prompt 纯本地
    return GameAgent(LLMConfig(api_key="test", base_url="http://x", model="x"))


def _round(n: int, narrative_chars: int = 2000, tool_chars: int = 3000) -> list:
    """造一个完整回合：user → assistant(tool_call + reasoning) → tool → assistant(final)。"""
    cid = f"call_{n}"
    return [
        {"role": "user", "content": f"回合{n}：我做某事"},
        {"role": "assistant", "content": "叙" * (narrative_chars // 2),
         "reasoning_content": "想" * 500,
         "tool_calls": [{"id": cid, "type": "function",
                         "function": {"name": "get_state", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": cid, "content": "X" * tool_chars},
        {"role": "assistant", "content": "终" * (narrative_chars // 2)},
    ]


class CompressTest(unittest.TestCase):
    def setUp(self):
        self.a = _agent()
        self.sys = self.a.messages[0]   # 系统提示词

    def test_small_history_untouched_rounds(self):
        # 小历史（少于阈值）不丢回合，但仍剥离 reasoning + 截旧工具
        self.a.messages = [self.sys] + _round(1) + _round(2)
        self.a._compress_history()
        users = [m for m in self.a.messages if m.get("role") == "user"]
        self.assertEqual(len(users), 2)            # 回合没被丢
        self.assertEqual(self.a.messages[0], self.sys)

    def test_reasoning_content_stripped(self):
        self.a.messages = [self.sys] + _round(1) + _round(2)
        self.assertTrue(any("reasoning_content" in m for m in self.a.messages))
        self.a._compress_history()
        self.assertFalse(any("reasoning_content" in m for m in self.a.messages))

    def test_old_tool_results_truncated_last_round_full(self):
        self.a.messages = [self.sys] + _round(1) + _round(2) + _round(3)
        self.a._compress_history()
        tool_msgs = [m for m in self.a.messages if m.get("role") == "tool"]
        # 最后一轮的工具结果完整；之前的被截断
        self.assertGreater(len(tool_msgs[-1]["content"]), OLD_TOOL_RESULT_CAP)
        for tm in tool_msgs[:-1]:
            self.assertLessEqual(len(tm["content"]), OLD_TOOL_RESULT_CAP + 60)

    def test_over_budget_drops_oldest_rounds(self):
        # 30 个大回合 → 远超预算 → 砍到只剩最近 KEEP_RECENT_TURNS 轮
        self.a.messages = [self.sys]
        for n in range(30):
            self.a.messages += _round(n)
        self.a._compress_history()
        users = [m for m in self.a.messages if m.get("role") == "user"]
        self.assertEqual(len(users), KEEP_RECENT_TURNS)
        self.assertEqual(self.a.messages[0], self.sys)            # 系统提示词恒保留
        self.assertEqual(self.a.messages[1]["role"], "user")     # 砍口落在回合边界

    def test_pairing_integrity_after_compression(self):
        self.a.messages = [self.sys]
        for n in range(30):
            self.a.messages += _round(n)
        self.a._compress_history()
        # 每个 tool 消息的 tool_call_id 都能在某个 assistant 的 tool_calls 里找到（配对未断）
        call_ids = set()
        for m in self.a.messages:
            for tc in (m.get("tool_calls") or []):
                call_ids.add(tc["id"])
        for m in self.a.messages:
            if m.get("role") == "tool":
                self.assertIn(m["tool_call_id"], call_ids)


if __name__ == "__main__":
    unittest.main()
