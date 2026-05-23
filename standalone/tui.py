"""TUI 前端（textual）：状态栏顶 + 叙事中 + 输入底，流式 + Markdown 渲染。

运行：python -m standalone.tui
LLM 配置从 .env 读（OpenAI 兼容：OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL）。

设计要点：
- 高级终端美学：精调主题（tokyo-night）+ 带标题面板 + IDE 式左色条角色标记（非聊天气泡）。
- 流式期逐字写纯文本 Static（便宜），整段完成才换 Markdown 一次性渲染（代码块/加粗/列表），
  避免每 chunk 重排 markdown 的 O(n²) 卡顿。
- 玩家行 = 次色左条；GM 叙事 = 强调色左条 + markdown 渲染。
"""
from __future__ import annotations

import mcp_server
from textual import work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Input, Markdown, Static

from .agent import make_agent
from .config import LLMConfig

FLUSH_CHARS = 24   # 流式节流：缓冲超过这么多字符（或遇换行）才刷一次（纯文本刷新便宜，可较密）


def live_hud() -> str:
    """从引擎实时取状态条，供顶部状态栏常驻显示。"""
    s = mcp_server.SESSION
    if not s.started:
        return "（未开局）"
    try:
        if s.encounter is not None:
            return mcp_server._build_combat_hud(s.encounter)
        return mcp_server._build_hud(s.state, s.world)
    except Exception:
        return "（状态读取失败）"


class TextAdventureApp(App):
    # 高级终端美学：用精调主题（tokyo-night 等）+ 带标题面板 + IDE 式左色条角色标记，
    # 不做聊天气泡。配色全走主题变量，整体协调克制（lazygit/k9s 风）。
    CSS = """
    Screen { layout: vertical; }

    /* 顶部状态面板：圆角标题边框，HUD 居中留白 */
    #status {
        height: auto; min-height: 3; padding: 0 2;
        color: $text;
        border: round $primary 60%;
        border-title-color: $primary;
        border-title-align: left;
        margin: 1 2 0 2;
    }

    /* 中部叙事面板：占满，标题边框，内部滚动 */
    #convo {
        height: 1fr; padding: 1 2;
        border: round $surface-lighten-2;
        border-title-color: $accent;
        border-title-align: left;
        margin: 1 2 0 2;
        scrollbar-gutter: stable;
        scrollbar-color: $primary 40%;
        scrollbar-background: $surface;
    }

    /* 玩家行：左侧次色条，无框，简洁缩进 */
    .msg-player {
        margin: 1 0 0 0; padding: 0 0 0 1;
        color: $text-muted; text-style: italic;
        border-left: thick $secondary;
    }

    /* GM 叙事：左侧强调色条，渲染 markdown */
    .msg-gm {
        margin: 1 0 0 0; padding: 0 0 0 1;
        border-left: thick $accent;
    }

    /* 思考中占位 */
    .thinking {
        margin: 1 0 0 1; color: $text-muted; text-style: italic;
        border-left: thick $warning;
    }

    /* 底部输入：标题边框，聚焦时强调 */
    #input {
        dock: bottom; margin: 1 2; border: round $surface-lighten-2;
        border-title-color: $text-muted; border-title-align: left;
    }
    #input:focus { border: round $accent; }
    """
    BINDINGS = [("ctrl+c", "quit", "退出"), ("ctrl+l", "clear", "清屏")]

    def __init__(self, config: LLMConfig):
        super().__init__()
        self.config = config
        self.agent = make_agent(config)
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("（启动中…）", id="status")
        yield VerticalScroll(id="convo")
        yield Input(placeholder="输入你的行动…", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "tokyo-night"
        self.title = "文字冒险"
        self.sub_title = self.config.model
        # 面板标题（lazygit 式）
        self.query_one("#status", Static).border_title = "状 态"
        self.query_one("#convo", VerticalScroll).border_title = "叙 事"
        self.query_one("#input", Input).border_title = "你的行动"
        self._run_turn("")   # 开局：空输入让 GM 起手

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self._busy:
            return
        # 玩家行（左侧次色条标记，无框）
        convo = self.query_one("#convo", VerticalScroll)
        convo.mount(Static(f"❯ {text}", classes="msg-player"))
        convo.scroll_end(animate=False)
        self._run_turn(text)

    def action_clear(self) -> None:
        """清屏（保留游戏状态，只清叙事区显示）。"""
        self.query_one("#convo", VerticalScroll).remove_children()

    def _run_turn(self, player_input: str) -> None:
        self._busy = True
        self.query_one("#input", Input).disabled = True
        self._stream_worker(player_input)

    @work(thread=True, exclusive=True)
    def _stream_worker(self, player_input: str) -> None:
        convo = self.query_one("#convo", VerticalScroll)
        # 思考占位（首个 delta 到达前显示）
        placeholder = Static("⋯ GM 正在推演", classes="thinking")
        self.call_from_thread(convo.mount, placeholder)
        self.call_from_thread(convo.scroll_end, animate=False)

        # 流式期：纯文本 Static 逐字显示（便宜，不解析 markdown）。
        # 整段结束(final)：换成 Markdown 一次性渲染（代码块/加粗/列表才出来）。
        # 这样既流畅又能渲染——避免每个 chunk 都重排整段 markdown 的 O(n²) 卡顿。
        state = {"live": None, "placeholder": placeholder, "text": ""}
        buf: list[str] = []

        def ensure_live():
            """首次有文字时：移除占位，挂上纯文本流式气泡。"""
            if state["live"] is None:
                if state["placeholder"] is not None:
                    self.call_from_thread(state["placeholder"].remove)
                    state["placeholder"] = None
                live = Static("", classes="msg-gm")
                self.call_from_thread(convo.mount, live)
                state["live"] = live

        def flush():
            """把缓冲并入累计文本，整体刷新纯文本气泡（纯文本 update 极便宜）。"""
            if not buf:
                return
            ensure_live()
            state["text"] += "".join(buf)
            buf.clear()
            self.call_from_thread(state["live"].update, state["text"])
            self.call_from_thread(convo.scroll_end, animate=False)

        def finalize_markdown():
            """整段完成：把纯文本气泡换成渲染好的 Markdown。"""
            if state["live"] is None or not state["text"].strip():
                return
            md = Markdown(state["text"], classes="msg-gm")
            self.call_from_thread(convo.mount, md, after=state["live"])
            self.call_from_thread(state["live"].remove)
            state["live"] = None
            self.call_from_thread(convo.scroll_end, animate=False)

        try:
            for kind, payload in self.agent.run_turn_stream(player_input):
                if kind == "tool":
                    if state["placeholder"] is not None:
                        self.call_from_thread(
                            state["placeholder"].update, f"⋯ GM 正在查看（{payload['name']}）")
                elif kind == "delta":
                    buf.append(payload)
                    if "\n" in payload or sum(len(x) for x in buf) >= FLUSH_CHARS:
                        flush()
                elif kind == "final":
                    flush()
                    finalize_markdown()
        except Exception as exc:
            ensure_live()
            self.call_from_thread(
                state["live"].update, state["text"] + f"\n\n✗ 出错：{type(exc).__name__}: {exc}")
        finally:
            if state["live"] is None and state["placeholder"] is not None:
                self.call_from_thread(state["placeholder"].remove)
            self.call_from_thread(self._finish_turn)

    def _finish_turn(self) -> None:
        self.query_one("#status", Static).update(live_hud())
        inp = self.query_one("#input", Input)
        inp.disabled = False
        inp.focus()
        self.query_one("#convo", VerticalScroll).scroll_end(animate=False)
        self._busy = False


def main() -> int:
    cfg = LLMConfig.from_env()
    err = cfg.validate()
    if err:
        print(f"无法启动 TUI：{err}")
        return 1
    TextAdventureApp(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
