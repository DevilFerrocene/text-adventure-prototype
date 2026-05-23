"""Agent loop：LLM ↔ 工具 ↔ 引擎，跑完一个玩家回合。

这正是 Claude Code 一直替我们做的事。一个回合：
  把玩家输入喂给 LLM → LLM 可能要调工具 → 执行工具、结果喂回 → 循环 →
  直到 LLM 输出一段不带工具调用的文字（= 给玩家的叙事）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from openai import OpenAI

from .config import LLMConfig
from .prompt import load_system_prompt
from .tools import build_tools, call_tool

MAX_TOOL_ITERS = 16   # 单回合内最多几轮工具调用，防失控

# ── 上下文压缩 ────────────────────────────────────────────────────
# 对话历史无界增长会撑爆窗口、每回合烧更多 token。但本游戏【引擎才是长程记忆】
# （HUD/任务/线索/对话日志/房间快照/背包全在引擎里，每回合用 get_state/recall 重查），
# 所以历史只需保留最近若干回合的叙事流，旧回合可整轮丢弃——事实都在引擎里。
# 三个阈值由 LLMConfig 提供（可经 .env 配：HISTORY_CHAR_BUDGET / KEEP_RECENT_TURNS /
# OLD_TOOL_RESULT_CAP）。HISTORY_CHAR_BUDGET ≤ 0 表示关闭压缩。


@dataclass
class GameAgent:
    """一局游戏的 agent：持有 LLM 客户端、工具桥、对话历史。"""
    config: LLMConfig
    client: OpenAI = field(init=False)
    tool_specs: list = field(init=False)
    dispatch: dict = field(init=False)
    messages: list = field(default_factory=list)
    on_tool_call: Callable[[str, dict], None] | None = None  # 调试/UI 回调
    rich_ui: bool = False   # 富前端（web）：UI 自渲染面板，GM 走散文模式

    def __post_init__(self):
        self.client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
        self.tool_specs, self.dispatch = build_tools()
        self.messages = [{"role": "system", "content": load_system_prompt(self.rich_ui)}]

    def _history_chars(self) -> int:
        """粗估历史体量（字符数；中文≈token 同量级，够用来当压缩阈值）。"""
        total = 0
        for m in self.messages:
            total += len(m.get("content") or "")
            tcs = m.get("tool_calls")
            if tcs:
                total += len(json.dumps(tcs, ensure_ascii=False))
        return total

    def _compress_history(self):
        """回合开始时压缩历史。三招，全都不破坏 tool_call↔tool 配对：
        ① 剥离已完成回合的 reasoning_content（思考链是死重，DeepSeek 也不该回传旧的）；
        ② 截断旧回合的工具结果（最新一轮保留完整，旧的可重新 get_state/recall）；
        ③ 仍超预算 → 按【玩家回合】边界整轮丢最老的，保 system + 最近 keep_recent_turns 轮。
        阈值取自 self.config（可经 .env 配）；history_char_budget ≤ 0 时整体关闭压缩。
        """
        budget = self.config.history_char_budget
        keep_turns = self.config.keep_recent_turns
        tool_cap = self.config.old_tool_result_cap
        msgs = self.messages
        if budget <= 0 or len(msgs) <= 3:
            return
        # ① 剥离历史里的 reasoning_content（仅当前回合循环内需要，跨回合是死重）
        for m in msgs[1:]:
            m.pop("reasoning_content", None)
        # ② 截断旧工具结果（保留最近一轮的完整结果）
        user_idx = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
        last_round_start = user_idx[-1] if user_idx else len(msgs)
        for i in range(1, last_round_start):
            m = msgs[i]
            if m.get("role") == "tool":
                c = m.get("content") or ""
                if len(c) > tool_cap:
                    m["content"] = (c[:tool_cap]
                                    + " …[旧工具结果已截断；最新状态以 get_state/recall 为准]")
        # ③ 仍超预算 → 整轮丢最老的（系统消息恒保留）
        if self._history_chars() > budget:
            user_idx = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
            if len(user_idx) > keep_turns:
                cut = user_idx[-keep_turns]   # 倒数第 K 个玩家回合的起点
                del msgs[1:cut]               # 砍掉 system 之后、到该点之前的整段旧历史

    def _complete(self):
        return self.client.chat.completions.create(
            model=self.config.model,
            messages=self.messages,
            tools=self.tool_specs,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def run_turn(self, player_input: str) -> str:
        """跑一个玩家回合，返回给玩家看的叙事文字。

        player_input 为空字符串时表示"开局"（让 GM 自己起手 start_game + 开场）。
        """
        if player_input:
            self.messages.append({"role": "user", "content": player_input})
        self._compress_history()   # 回合开始先压缩，控住上下文体量

        for _ in range(MAX_TOOL_ITERS):
            resp = self._complete()
            msg = resp.choices[0].message

            # 把 assistant 消息原样入历史（含 tool_calls，OpenAI 协议要求）
            self.messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                return (msg.content or "").strip()

            # 执行每个工具调用，结果以 role=tool 喂回
            for tc in msg.tool_calls:
                name = tc.function.name
                args_json = tc.function.arguments or "{}"
                if self.on_tool_call:
                    try:
                        self.on_tool_call(name, json.loads(args_json or "{}"))
                    except Exception:
                        pass
                result = call_tool(self.dispatch, name, args_json)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        return "（GM 在本回合调用工具过多，已中断。请再试一次或换个说法。）"

    def run_turn_stream(self, player_input: str):
        """流式版回合：生成器，逐事件 yield。

        事件元组 (kind, payload)：
          ("tool", name)   —— GM 调了某工具（内部思考，UI 可显示"在查看…"）
          ("delta", text)  —— 最终叙事的一小段，逐字流给玩家
          ("final", text)  —— 整段叙事（流完，给 UI 收尾/留存）

        只流"最终那轮叙事"；工具调用轮次不流（那不是给玩家看的）。
        """
        if player_input:
            self.messages.append({"role": "user", "content": player_input})
        self._compress_history()   # 回合开始先压缩，控住上下文体量

        for _ in range(MAX_TOOL_ITERS):
            stream = self.client.chat.completions.create(
                model=self.config.model,
                messages=self.messages,
                tools=self.tool_specs,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=True,
            )

            content_parts: list[str] = []
            reasoning_parts: list[str] = []   # DeepSeek 思考模式：须回传 reasoning_content
            # 累积 tool_calls 的流式增量：index -> {id, name, args}
            tc_accum: dict[int, dict] = {}

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    content_parts.append(delta.content)
                    yield ("delta", delta.content)
                # 思考模型的推理流（OpenAI 标准字段没有，从属性或 model_extra 取）
                rc = getattr(delta, "reasoning_content", None)
                if rc is None and getattr(delta, "model_extra", None):
                    rc = delta.model_extra.get("reasoning_content")
                if rc:
                    reasoning_parts.append(rc)
                for tc in (getattr(delta, "tool_calls", None) or []):
                    slot = tc_accum.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments

            full_content = "".join(content_parts)
            full_reasoning = "".join(reasoning_parts)

            if not tc_accum:
                # 这轮是最终叙事——已经逐字流过了
                final_msg = {"role": "assistant", "content": full_content}
                if full_reasoning:
                    final_msg["reasoning_content"] = full_reasoning
                self.messages.append(final_msg)
                yield ("final", full_content.strip())
                return

            # 这轮是工具调用：组装 assistant 消息（含 tool_calls）入历史
            # 思考模型要求把 reasoning_content 一并回传，否则下一轮 400。
            ordered = [tc_accum[i] for i in sorted(tc_accum)]
            assistant_msg = {
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": [
                    {"id": s["id"], "type": "function",
                     "function": {"name": s["name"], "arguments": s["args"] or "{}"}}
                    for s in ordered
                ],
            }
            if full_reasoning:
                assistant_msg["reasoning_content"] = full_reasoning
            self.messages.append(assistant_msg)
            for s in ordered:
                if self.on_tool_call:
                    try:
                        self.on_tool_call(s["name"], json.loads(s["args"] or "{}"))
                    except Exception:
                        pass
                yield ("tool", s["name"])
                result = call_tool(self.dispatch, s["name"], s["args"] or "{}")
                # 把工具结果也带出来，供富前端从中渲染 HUD/场景/骰子/战斗面板
                yield ("tool_result", {"name": s["name"], "result": result})
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": s["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })

        yield ("final", "（GM 在本回合调用工具过多，已中断。请再试一次。）")


def make_agent(config: LLMConfig | None = None, rich_ui: bool = False) -> GameAgent:
    return GameAgent(config or LLMConfig.from_env(), rich_ui=rich_ui)
