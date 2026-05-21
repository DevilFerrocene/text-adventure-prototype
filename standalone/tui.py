"""TUI 前端（textual）：状态栏顶 + 叙事中 + 输入底，带流式输出。

运行：python -m standalone.tui
LLM 配置从 .env 读（OpenAI 兼容：OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL）。
"""
from __future__ import annotations

import mcp_server
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static

from .agent import make_agent
from .config import LLMConfig


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


class StatusBar(Static):
    """顶部常驻 HUD。"""
    def refresh_hud(self) -> None:
        self.update(live_hud())


class TextAdventureApp(App):
    CSS = """
    Screen { layout: vertical; }
    #status { height: auto; min-height: 2; padding: 0 1; background: $panel; color: $text; border-bottom: solid $primary; }
    #log { height: 1fr; padding: 0 1; }
    #input { dock: bottom; }
    """
    BINDINGS = [("ctrl+c", "quit", "退出")]

    def __init__(self, config: LLMConfig):
        super().__init__()
        self.config = config
        self.agent = make_agent(config)
        self._streaming = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusBar("（启动中…）", id="status")
        yield RichLog(id="log", wrap=True, markup=True, highlight=False)
        yield Input(placeholder="输入你的行动…（回车提交）", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "文字冒险 · 独立版"
        self.query_one("#log", RichLog).write("[dim]GM 正在准备开场…[/dim]")
        # 开局：空输入让 GM 起手
        self._run_turn("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self._streaming:
            return
        log = self.query_one("#log", RichLog)
        log.write(f"\n[bold cyan]» {text}[/bold cyan]")
        self._run_turn(text)

    def _run_turn(self, player_input: str) -> None:
        self._streaming = True
        self.query_one("#input", Input).disabled = True
        self._stream_worker(player_input)

    # ── 后台线程跑 LLM 流式（避免阻塞 UI 事件循环）──
    @work(thread=True, exclusive=True)
    def _stream_worker(self, player_input: str) -> None:
        log = self.query_one("#log", RichLog)
        buf: list[str] = []
        try:
            for kind, payload in self.agent.run_turn_stream(player_input):
                if kind == "tool":
                    self.call_from_thread(log.write, f"[dim]› GM 在调用 {payload}…[/dim]")
                elif kind == "delta":
                    buf.append(payload)
                    # 逐行刷新：积累到换行或一定长度就 flush 一段
                    if "\n" in payload or sum(len(x) for x in buf) > 40:
                        self.call_from_thread(log.write, "".join(buf))
                        buf.clear()
                elif kind == "final":
                    if buf:
                        self.call_from_thread(log.write, "".join(buf))
                        buf.clear()
        except Exception as exc:
            self.call_from_thread(log.write, f"[red]✗ 出错：{type(exc).__name__}: {exc}[/red]")
        finally:
            self.call_from_thread(self._finish_turn)

    def _finish_turn(self) -> None:
        self.query_one("#status", StatusBar).refresh_hud()
        inp = self.query_one("#input", Input)
        inp.disabled = False
        inp.focus()
        self._streaming = False


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
