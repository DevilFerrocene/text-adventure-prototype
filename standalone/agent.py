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

# ── 上下文压缩（仿 agent compact / 即 Claude Code 自动压缩那套思路）──────────────
# 对话历史无界增长会撑爆窗口、每回合烧更多 token。本游戏【引擎才是长程记忆】
# （HUD/任务/线索/对话日志/房间快照/背包全在引擎里，每回合用 get_state/recall 重查），
# 所以历史只需保叙事连贯。做法：超预算时，把【较早那段对话】交给 LLM 压成一份
# 简洁的【前情提要】，替换掉那段原始消息；最近 keep_recent_turns 个回合【逐字保留】。
#
# 谨慎原则（这是处理"提示词"，必须稳）：
#   · 整回合粒度 + LLM 摘要——绝不逐条截断/改写消息内容（截半的 JSON 会让模型掉格式）。
#   · 摘要替换只发生在回合【边界】，tool_call↔tool 配对天然不破。
#   · 摘要只管【叙事】，明令不记机制数值（hp/金币/属性/坐标——引擎里有实时权威值）。
#   · 摘要 LLM 调用失败 → 安全回退到"整回合丢弃旧段"，绝不让压缩本身搞坏一个回合。
# 阈值经 .env：HISTORY_CHAR_BUDGET（触发阈值，≤0 关闭压缩）/ KEEP_RECENT_TURNS（逐字窗口）。

# 压缩用记录员 prompt：把旧对话压成供 GM 续写的【前情提要】，刻意不碰机制数值。
COMPACT_SYSTEM = """你是这局 TRPG 文字冒险的记录员。下面是一段较早的游戏对话，请把它压成一份简洁、客观的【前情提要】，供 GM 继续主持时快速回顾。

只保留对【后续叙事连贯】重要的信息：
- 玩家是谁、当前处境与目标
- 已发生的关键事件、抉择、转折（按时间顺序）
- 重要人物 / 关系、达成或破裂的约定
- 尚未了结的线索、伏笔、承诺、威胁
- 这局的基调与文风提示

不要记录具体机制数值（hp / 金币 / 属性 / 坐标 / 骰点——这些引擎里有实时权威值，GM 会自己查）。
紧凑分点、能省则省，不复述无关闲笔。直接输出提要正文，不要任何前言或客套。"""

# 前情提要【追加进 system 提示词】的分隔块头。放进 system 而非单独消息，是为了：
#   ① 保证 user/assistant 严格交替（部分思考模型不接受连续同角色消息，会 400）；
#   ② 把"剧情回顾"明确归位成上下文，而非玩家发言或真实数值；
#   ③ 让格式锚（system 里的输出规范）始终完整在场、不被冲淡。
RECAP_PREFIX = ("\n\n========================================\n"
                "【前情提要】先前剧情的压缩回顾，仅供你延续叙事与基调；"
                "具体机制数值（hp / 金币 / 属性 / 位置等）一律以引擎实时查询为准。\n"
                "========================================\n")


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
        # 基础 system 提示词单独存一份：压缩时把前情提要【追加】在它后面（不污染原文，
        # 再压缩时整体重算，避免提要无限增长）。messages[0] = _base_system [+ RECAP + 提要]。
        self._base_system = load_system_prompt(self.rich_ui)
        self.messages = [{"role": "system", "content": self._base_system}]

    def _history_chars(self) -> int:
        """粗估历史体量（字符数；中文≈token 同量级，够用来当压缩阈值）。"""
        total = 0
        for m in self.messages:
            total += len(m.get("content") or "")
            tcs = m.get("tool_calls")
            if tcs:
                total += len(json.dumps(tcs, ensure_ascii=False))
        return total

    def _render_for_summary(self, msgs: list) -> str:
        """把一段消息摊平成可读剧情文本，喂给摘要 LLM。
        只取叙事相关：玩家输入 + GM 叙事 + GM 调了哪些工具（动作线索）；
        工具【结果】跳过——那是机制数据，引擎里有权威值，进摘要既无益又会塞回 JSON。"""
        lines = []
        for m in msgs:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role == "user":
                lines.append(f"【玩家】{content}")
            elif role == "assistant":
                if content:
                    lines.append(f"【GM】{content}")
                for tc in (m.get("tool_calls") or []):
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    name = fn.get("name", "")
                    args = (fn.get("arguments", "") or "")[:80]
                    lines.append(f"（GM 用了工具 {name} {args}）".rstrip())
            # role == "tool"：机制结果，跳过
        return "\n".join(lines)

    def _summarize(self, text: str) -> str:
        """让 LLM 把一段剧情文本压成【前情提要】正文。一次性、无工具、无流式。
        失败抛异常，由调用方回退处理。（独立成法便于测试替身注入。）"""
        if not text.strip():
            return ""
        resp = self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "system", "content": COMPACT_SYSTEM},
                      {"role": "user", "content": text}],
            temperature=0.3,
            max_tokens=900,
        )
        return (resp.choices[0].message.content or "").strip()

    def _extract_recap(self) -> str:
        """从 system 消息里取出上一次的前情提要正文（没有则空串）。"""
        content = self.messages[0].get("content", "") if self.messages else ""
        idx = content.find(RECAP_PREFIX)
        return content[idx + len(RECAP_PREFIX):].strip() if idx != -1 else ""

    def _compress_history(self):
        """回合开始时压缩历史（仿 agent compact）：
        ① 先剥离历史里的 reasoning_content（跨回合是死重，部分思考模型回传旧的还会 400）；
        ② 未超预算 → 不动（绝不做任何逐条改写）；
        ③ 超预算 → 把【旧段 + 已有前情提要】LLM 压成新【前情提要】，追加进 system；旧段整段删除，
           最近 keep_recent_turns 回合逐字保留。删除只落在回合边界，tool 配对天然不破；
           摘要失败则安全回退到"整回合丢弃旧段"，绝不让压缩本身搞坏一个回合。
        阈值取自 self.config（可经 .env 配）；history_char_budget ≤ 0 时整体关闭压缩。
        """
        budget = self.config.history_char_budget
        keep_turns = self.config.keep_recent_turns
        msgs = self.messages
        if budget <= 0 or len(msgs) <= 3:
            return
        # ① 剥离 reasoning_content（仅当前回合循环内需要，跨回合死重）
        for m in msgs[1:]:
            m.pop("reasoning_content", None)
        # ② 未超预算 → 到此为止，不改任何内容
        if self._history_chars() <= budget:
            return
        # ③ 超预算 → 旧段压成前情提要（追加进 system），最近若干回合逐字保留
        user_idx = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
        n = len(user_idx)
        if n <= 1:
            return                       # 只有一个回合，没有可安全压缩的旧段
        eff_keep = min(keep_turns, n - 1)   # 逐字窗口 ≤ keep_turns，但总留 ≥1 回合给压缩腾地
        cut = user_idx[-eff_keep]        # 逐字窗口的起点（一个玩家回合边界）
        head = msgs[1:cut]               # system 之后、逐字窗口之前的旧段（含开局叙事）
        if not head:
            return
        # 把已有的前情提要一并卷进去重压，避免提要随局数无限增长
        prior = self._extract_recap()
        text = self._render_for_summary(head)
        if prior:
            text = f"（此前的前情提要）\n{prior}\n\n（之后又发生）\n{text}"
        try:
            summary = self._summarize(text)
        except Exception:
            summary = ""                 # 摘要 LLM 失败/超时 → 走回退
        if summary:
            # system 重算 = 基础提示词 + 新前情提要（不堆叠旧提要，整体替换）
            msgs[0] = {"role": "system", "content": self._base_system + RECAP_PREFIX + summary}
        del msgs[1:cut]                  # 旧段整段删除（摘要成功=已入 system；失败=安全丢弃）

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

            # 这轮是【工具调用轮】，但它也喷了叙事（抢在工具结果出来前的"抢跑草稿"）——
            # 玩家该看到的是最后一轮结算后的叙事，不是这段抢跑文。让前端把已流出的这段清掉。
            if full_content.strip():
                yield ("reset", "")

            # 组装 assistant 消息（含 tool_calls）入历史
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
                yield ("tool", {"name": s["name"], "args": s["args"] or "{}"})
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
