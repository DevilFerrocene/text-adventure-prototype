"""Web 前端后端（FastAPI + SSE）：把 agent loop 推流给浏览器。

运行：python -m standalone.web   （默认 http://127.0.0.1:8000）
- GET  /         单文件 HTML 前端（仿-TUI 视觉）
- GET  /state    结构化状态（状态条用，去-CoC 动态属性）
- POST /turn     {input, mode} → SSE 流（event: delta/tool/final/hud）

设计：单会话（SESSION 是引擎全局单例），回合用锁串行化——MVP 不支持并发多人。
sync 生成器交给 StreamingResponse，Starlette 自动在线程池迭代，不阻塞事件循环。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import mcp_server
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .agent import make_agent
from .config import LLMConfig

_HERE = Path(__file__).parent
_INDEX = _HERE / "web" / "index.html"

app = FastAPI(title="文字冒险 · Web")
_agent = None
_lock = threading.Lock()   # 单会话回合串行化


def _get_agent():
    global _agent
    if _agent is None:
        _agent = make_agent(LLMConfig.from_env())
    return _agent


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def hud_payload() -> dict:
    """状态条结构化数据（去-CoC：属性来自当前世界 RuleBook，不写死）。"""
    s = mcp_server.SESSION
    if not s.started:
        return {"started": False}
    v = s.state.vitals
    rb = getattr(s.world, "rulebook", None)
    attr_labels = (rb.attributes if rb else {}) or {}
    room = s.world.get_room(s.state.position)
    quest = s.state.quest_log[0] if s.state.quest_log else None
    return {
        "started": True,
        "world": s.world_name,
        "in_combat": s.encounter is not None,
        "vitals": {
            "hp": v.hp, "max_hp": v.max_hp,
            "stamina": v.stamina, "max_stamina": v.max_stamina,
            "gold": v.gold, "level": v.level, "exp": v.exp,
        },
        # 动态属性：[{key,label,value}]，前端遍历出条，不写死 HP/SAN
        "attributes": [
            {"key": k, "label": attr_labels.get(k, k), "value": v.attributes.get(k, 0)}
            for k in attr_labels
        ],
        "position": room.name if room else s.state.position,
        "quest": ({"title": quest.title, "stage": quest.stage} if quest else None),
    }


_MODE_PREFIX = {
    "say": "（说话）", "act": "（行动）", "ooc": "（场外）",
}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    if _INDEX.exists():
        return _INDEX.read_text(encoding="utf-8")
    return "<h1>前端文件缺失：standalone/web/index.html</h1>"


@app.get("/state")
def state() -> JSONResponse:
    return JSONResponse(hud_payload())


@app.post("/turn")
async def turn(request: Request) -> StreamingResponse:
    body = await request.json()
    text = (body.get("input") or "").strip()
    mode = body.get("mode", "say")

    def gen():
        with _lock:
            agent = _get_agent()
            # mode 作为轻量前缀提示 GM（说话/行动/场外）；空 input = 开局
            full = (_MODE_PREFIX.get(mode, "") + text) if text else ""
            try:
                for kind, payload in agent.run_turn_stream(full):
                    if kind == "delta":
                        yield _sse("delta", {"text": payload})
                    elif kind == "tool":
                        yield _sse("tool", {"name": payload})
                    elif kind == "final":
                        yield _sse("final", {"text": payload})
            except Exception as exc:
                yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
            # 回合末推一次最新状态条
            yield _sse("hud", hud_payload())

    return StreamingResponse(gen(), media_type="text/event-stream")


def main() -> int:
    cfg = LLMConfig.from_env()
    err = cfg.validate()
    if err:
        print(f"无法启动 Web：{err}")
        return 1
    import uvicorn
    print("文字冒险 Web 服务：http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
