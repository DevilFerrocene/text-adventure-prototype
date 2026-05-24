"""独立运行层上下文压缩（仿 agent compact）：超预算时 LLM 把旧段压成【前情提要】，
最近若干回合逐字保留；reasoning 剥离；摘要失败安全回退到整回合丢弃；配对恒不破。"""
import types
import unittest

import mcp_server
from standalone.agent import GameAgent, RECAP_PREFIX
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
        self.sys = self.a.messages[0]            # 系统提示词（messages[0]）
        self.base = self.a._base_system          # 基础提示词正文（不含前情提要）
        # 离线替身：摘要不发网络，返回可识别的假提要。想测"被调到了"就查 self.summarized。
        self.summarized = []

        def fake_summarize(text):
            self.summarized.append(text)
            return "假前情提要：玩家在营地一路破局，砍了树、登了记。"
        self.a._summarize = fake_summarize

    def _fill(self, n):
        self.a.messages = [self.sys]
        for k in range(n):
            self.a.messages += _round(k)

    def _users(self):
        return [m for m in self.a.messages if m.get("role") == "user"]

    def _sys_has_recap(self):
        return RECAP_PREFIX in self.a.messages[0].get("content", "")

    def test_small_history_untouched_no_summarize(self):
        # 小历史（未超预算）不丢回合、不摘要，只剥 reasoning
        self._fill(2)
        self.a._compress_history()
        self.assertEqual(len(self._users()), 2)               # 回合没被动
        self.assertEqual(self.summarized, [])                 # 没触发摘要 LLM
        self.assertFalse(self._sys_has_recap())               # system 没被追加提要

    def test_reasoning_content_stripped(self):
        self._fill(2)
        self.assertTrue(any("reasoning_content" in m for m in self.a.messages))
        self.a._compress_history()
        self.assertFalse(any("reasoning_content" in m for m in self.a.messages))

    def test_over_budget_compacts_old_into_system_recap(self):
        # 30 个大回合 → 远超预算 → 旧段被 LLM 压成前情提要【追加进 system】，最近 keep 回合逐字留
        self._fill(30)
        self.a._compress_history()
        keep = self.a.config.keep_recent_turns
        sys_content = self.a.messages[0]["content"]
        self.assertTrue(sys_content.startswith(self.base))    # 基础提示词完整在场
        self.assertIn(RECAP_PREFIX, sys_content)              # 提要追加在 system
        self.assertIn("假前情提要", sys_content)
        self.assertEqual(len(self.summarized), 1)             # 触发了一次摘要
        # system 之后第一条就是真实玩家回合（无连续同角色消息）
        self.assertEqual(self.a.messages[1]["role"], "user")
        # 玩家回合只剩最近 keep 个，逐字保留
        self.assertEqual(len(self._users()), keep)

    def test_no_consecutive_same_role_after_compaction(self):
        # 关键稳健性：压缩后不得出现连续同角色消息（部分思考模型会 400）
        self._fill(30)
        self.a._compress_history()
        roles = [m["role"] for m in self.a.messages]
        # system 只在开头一条
        self.assertEqual(roles.count("system"), 1)
        self.assertEqual(roles[0], "system")
        # 相邻不连续 user/user 或 assistant/assistant（tool 紧跟 assistant 属正常）
        for a_, b_ in zip(roles, roles[1:]):
            self.assertFalse(a_ == b_ == "user")
            self.assertFalse(a_ == b_ == "assistant")

    def test_summarize_failure_falls_back_to_drop(self):
        # 摘要 LLM 抛错 → 安全回退：整回合丢弃旧段，system 不追加提要，绝不搞坏回合
        def boom(text):
            raise RuntimeError("summary endpoint down")
        self.a._summarize = boom
        self._fill(30)
        self.a._compress_history()
        keep = self.a.config.keep_recent_turns
        self.assertEqual(self.a.messages[0]["content"], self.base)   # system 原样（无提要）
        self.assertFalse(self._sys_has_recap())
        self.assertEqual(self.a.messages[1]["role"], "user")         # 砍口落在回合边界
        self.assertEqual(len(self._users()), keep)

    def test_budget_zero_disables_compression(self):
        # history_char_budget ≤ 0 → 整体关闭，历史原样不动、reasoning 不剥、不摘要
        self.a.config.history_char_budget = 0
        self._fill(30)
        before = len(self.a.messages)
        self.a._compress_history()
        self.assertEqual(len(self.a.messages), before)
        self.assertEqual(self.summarized, [])
        self.assertTrue(any("reasoning_content" in m for m in self.a.messages))

    def test_pairing_integrity_after_compaction(self):
        # 压缩后：每个 tool 消息都有配对的 assistant.tool_calls，且每个 tool_calls 都紧跟其 tool 响应
        self._fill(30)
        self.a._compress_history()
        msgs = self.a.messages
        call_ids = set()
        for m in msgs:
            for tc in (m.get("tool_calls") or []):
                call_ids.add(tc["id"])
        for m in msgs:
            if m.get("role") == "tool":
                self.assertIn(m["tool_call_id"], call_ids)   # 没有孤儿 tool 响应
        # 反向：每个 assistant.tool_calls 后面都跟着对应 tool 响应（没有孤儿 tool_calls）
        for i, m in enumerate(msgs):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                ids = {tc["id"] for tc in m["tool_calls"]}
                following = {fm.get("tool_call_id") for fm in msgs[i + 1:i + 1 + len(ids)]
                             if fm.get("role") == "tool"}
                self.assertTrue(ids <= following)

    def test_recap_input_carries_narrative_not_tool_json(self):
        # 喂给摘要 LLM 的文本应含玩家/GM 叙事，不夹带原始工具结果 JSON（机制数据引擎里查）
        self._fill(30)
        self.a._compress_history()
        text = self.summarized[0]
        self.assertIn("【玩家】", text)
        self.assertIn("【GM】", text)
        self.assertNotIn("XXX", text)        # _round 的工具结果是 "X"*3000，不该进摘要文本

    def test_recompaction_folds_prior_recap_no_unbounded_growth(self):
        # 二次压缩：把"已有前情提要 + 新旧段"一起重压，system 里只保留【一份】提要（不堆叠）
        self._fill(30)
        self.a._compress_history()
        self.assertEqual(self.a.messages[0]["content"].count(RECAP_PREFIX), 1)
        # 再灌一批回合，再次超预算压缩
        for k in range(30, 50):
            self.a.messages += _round(k)
        self.a._compress_history()
        self.assertEqual(self.a.messages[0]["content"].count(RECAP_PREFIX), 1)  # 仍只一份
        # 第二次摘要的输入应包含上一份提要（折叠进去，不丢老剧情）
        self.assertIn("假前情提要", self.summarized[-1])


def _chunk(content=None, tool_calls=None):
    delta = types.SimpleNamespace(content=content, tool_calls=tool_calls,
                                  reasoning_content=None, model_extra=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


def _tc(index, cid, name, args):
    return types.SimpleNamespace(
        index=index, id=cid,
        function=types.SimpleNamespace(name=name, arguments=args))


class ToolTracePayloadTest(unittest.TestCase):
    """run_turn_stream 的 tool 事件须带 {name, args}，前端才能留痕显示 GM 在做什么。"""

    def test_tool_event_carries_name_and_args(self):
        mcp_server.start_game("aincrad")
        a = _agent()
        # 第一轮：GM 调一个工具 get_scene{}；第二轮：输出最终叙事
        rounds = [
            [_chunk(tool_calls=[_tc(0, "call_1", "get_scene", "{}")])],
            [_chunk(content="你环顾四周。")],
        ]
        a.client.chat.completions.create = lambda **kw: rounds.pop(0)
        events = list(a.run_turn_stream("看看周围"))
        tool_events = [p for k, p in events if k == "tool"]
        self.assertEqual(len(tool_events), 1)
        self.assertEqual(tool_events[0]["name"], "get_scene")
        self.assertIn("args", tool_events[0])           # 带参数，供前端展开
        # 仍正常产出最终叙事
        self.assertTrue(any(k == "final" for k, _ in events))

    def test_lead_in_narration_committed_not_dropped(self):
        # 先叙事再调工具（"你扑上去——"接 deal_damage）是正式叙事，不能吞：
        # 该段须先逐字流出(delta)，再发 commit 封存（保留在流里），最后才是结算后叙事。
        mcp_server.start_game("aincrad")
        a = _agent()
        rounds = [
            # 第一轮：先喷一段先导叙事、再调工具
            [_chunk(content="你扑上去——"),
             _chunk(tool_calls=[_tc(0, "call_1", "get_scene", "{}")])],
            # 第二轮：结算后叙事
            [_chunk(content="剑刃没入野猪颈侧。")],
        ]
        a.client.chat.completions.create = lambda **kw: rounds.pop(0)
        events = list(a.run_turn_stream("揍它"))
        kinds = [k for k, _ in events]
        deltas = "".join(p for k, p in events if k == "delta")
        self.assertIn("commit", kinds)
        self.assertIn("final", kinds)
        self.assertLess(kinds.index("commit"), kinds.index("final"))     # commit 在 final 之前
        # 先导叙事必须流出去（没被吞），且 commit 在它之后、工具之前
        self.assertIn("你扑上去——", deltas)
        self.assertIn("剑刃没入野猪颈侧。", deltas)
        self.assertLess(kinds.index("commit"), kinds.index("tool"))
        # 两段叙事都进了历史（刷新后 transcript 能恢复全部叙事）
        narrations = [m.get("content") for m in a.messages if m.get("role") == "assistant"]
        self.assertTrue(any("你扑上去——" in (c or "") for c in narrations))

    def test_clean_tool_round_no_commit(self):
        # 调工具那轮【没喷叙事】（先结算后叙事的规矩做法）→ 不该有多余的 commit
        mcp_server.start_game("aincrad")
        a = _agent()
        rounds = [
            [_chunk(tool_calls=[_tc(0, "call_1", "get_scene", "{}")])],   # 纯工具，无 content
            [_chunk(content="结算后的叙事。")],
        ]
        a.client.chat.completions.create = lambda **kw: rounds.pop(0)
        kinds = [k for k, _ in a.run_turn_stream("看看")]
        self.assertNotIn("commit", kinds)


if __name__ == "__main__":
    unittest.main()
