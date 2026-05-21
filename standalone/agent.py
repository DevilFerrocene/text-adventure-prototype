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


@dataclass
class GameAgent:
    """一局游戏的 agent：持有 LLM 客户端、工具桥、对话历史。"""
    config: LLMConfig
    client: OpenAI = field(init=False)
    tool_specs: list = field(init=False)
    dispatch: dict = field(init=False)
    messages: list = field(default_factory=list)
    on_tool_call: Callable[[str, dict], None] | None = None  # 调试/UI 回调

    def __post_init__(self):
        self.client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
        self.tool_specs, self.dispatch = build_tools()
        self.messages = [{"role": "system", "content": load_system_prompt()}]

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
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": s["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })

        yield ("final", "（GM 在本回合调用工具过多，已中断。请再试一次。）")


def make_agent(config: LLMConfig | None = None) -> GameAgent:
    return GameAgent(config or LLMConfig.from_env())
