"""TUI 前端（textual）：状态栏顶 + 叙事中 + 输入底，流式 + Markdown 渲染。

运行：python -m standalone.tui
LLM 配置从 .env 读（OpenAI 兼容：OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL）。

设计要点（针对硬伤）：
- 用 Markdown widget 真渲染代码块/加粗/列表（HUD、骰子卡、场景清单都是 md），不再是纯文本。
- 流式往 Markdown.append() 节流写入（攒到换行或 ~60 字才刷一次），避免每个 delta 重绘卡顿。
- 玩家输入与 GM 叙事用不同气泡样式区分；间距、配色、状态栏走 CSS。
"""
from __future__ import annotations

import mcp_server
from textual import work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Input, Markdown, Static

from .agent import make_agent
from .config import LLMConfig

FLUSH_CHARS = 60   # 流式节流：缓冲超过这么多字符（或遇换行）才刷一次


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
    CSS = """
    Screen { layout: vertical; background: $surface; }

    #status {
        height: auto; min-height: 2; padding: 1 2;
        background: $boost; color: $text;
        border: round $primary; margin: 0 1;
    }

    #convo { height: 1fr; padding: 1 2; scrollbar-gutter: stable; }

    /* 玩家输入气泡：靠右、青色、缩进 */
    .player-msg {
        width: auto; max-width: 80%; margin: 1 0 0 8;
        padding: 0 2; color: $text;
        background: $primary 20%; border: round $primary; text-align: right;
    }

    /* GM 叙事气泡：左侧、留边、左侧强调线 */
    .gm-msg { margin: 1 4 0 0; padding: 0 1; border-left: thick $accent; }

    /* 思考中占位 */
    .thinking { margin: 1 0 0 0; color: $text-muted; text-style: italic; }

    #input { dock: bottom; margin: 0 1 1 1; border: round $accent; }
    """
    BINDINGS = [("ctrl+c", "quit", "退出")]

    def __init__(self, config: LLMConfig):
        super().__init__()
        self.config = config
        self.agent = make_agent(config)
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("（启动中…）", id="status")
        yield VerticalScroll(id="convo")
        yield Input(placeholder="输入你的行动…（回车提交）", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "文字冒险 · 独立版"
        self.sub_title = f"{self.config.model}"
        self._run_turn("")   # 开局：空输入让 GM 起手

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self._busy:
            return
        # 玩家气泡
        convo = self.query_one("#convo", VerticalScroll)
        bubble = Static(text, classes="player-msg")
        convo.mount(bubble)
        convo.scroll_end(animate=False)
        self._run_turn(text)

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

        state = {"md": None, "placeholder": placeholder}
        buf: list[str] = []

        def ensure_bubble():
            """首次有文字时：移除占位，挂上 GM 的 Markdown 气泡。"""
            if state["md"] is None:
                if state["placeholder"] is not None:
                    self.call_from_thread(state["placeholder"].remove)
                    state["placeholder"] = None
                md = Markdown("", classes="gm-msg")
                self.call_from_thread(convo.mount, md)
                state["md"] = md

        def flush():
            if not buf:
                return
            ensure_bubble()
            text = "".join(buf)
            buf.clear()
            self.call_from_thread(state["md"].append, text)
            self.call_from_thread(convo.scroll_end, animate=False)

        try:
            for kind, payload in self.agent.run_turn_stream(player_input):
                if kind == "tool":
                    # 工具调用：更新占位文字（若还在），不污染叙事气泡
                    if state["placeholder"] is not None:
                        self.call_from_thread(
                            state["placeholder"].update, f"⋯ GM 正在查看（{payload}）")
                elif kind == "delta":
                    buf.append(payload)
                    if "\n" in payload or sum(len(x) for x in buf) >= FLUSH_CHARS:
                        flush()
                elif kind == "final":
                    flush()
        except Exception as exc:
            ensure_bubble()
            self.call_from_thread(
                state["md"].append, f"\n\n> ✗ 出错：{type(exc).__name__}: {exc}")
        finally:
            # 收尾：没产生任何气泡（纯报错前）也清掉占位
            if state["md"] is None and state["placeholder"] is not None:
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
