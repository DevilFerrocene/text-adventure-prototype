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
        # rich_ui：web 自己渲染 HUD/场景/骰子/战斗面板，GM 走散文模式（不粘状态块）
        _agent = make_agent(LLMConfig.from_env(), rich_ui=True)
    return _agent


def _render_events(name: str, result) -> list:
    """从工具结果抽出要 UI 渲染的结构面板。返回 [(type, data), ...]。
    web 直接渲染这些（GM 散文模式不再粘贴），消除重复 + 保证精确。"""
    out = []
    if not isinstance(result, dict):
        return out
    # 场景：get_scene / move / start_game 的返回带 scene（隐藏物已被快照排除）
    scene = result.get("scene")
    if isinstance(scene, dict):
        objs = [o.get("name") for o in scene.get("objects", []) if o.get("name")]
        exits = [d for d, info in (scene.get("exits") or {}).items()
                 if not (isinstance(info, dict) and info.get("locked"))]
        out.append(("scene", {"objects": objs, "exits": exits}))
    # 敌在场（未开战）：刷怪/进场后把在场敌人显成一张"敌在场"卡（开战后由 combat 面板接管，故跳过）
    profiles = result.get("enemy_profiles")
    if isinstance(profiles, list) and profiles and mcp_server.SESSION.encounter is None:
        out.append(("enemies", {
            "list": [{"name": p.get("name"), "hp": p.get("hp"), "max_hp": p.get("max_hp"),
                      "damage": p.get("damage_expr", "")} for p in profiles],
        }))
    # 明骰：explain_last_roll 的 line_format
    if result.get("line_format"):
        out.append(("dice", {"line": result["line_format"],
                             "outcome": result.get("outcome", "")}))
    # 战斗：任何带 active encounter 的结果（开战/declare_intent/deal_damage…）
    enc = result.get("encounter")
    if isinstance(enc, dict) and enc.get("active"):
        out.append(("combat", {
            "round": enc.get("round"),
            "active": enc.get("active_combatant"),
            "combatants": [
                {"id": c.get("id"), "name": c.get("name"),
                 "hp": c.get("hp"), "max_hp": c.get("max_hp"),
                 "side": c.get("side"), "is_dead": c.get("is_dead")}
                for c in enc.get("combatants", [])
            ],
        }))
    # 战斗结算日志：仅 declare_intent（单个行动）——显出 d 点掷骰 + 伤害结算过程
    if name == "declare_intent":
        events = result.get("events")
        if isinstance(events, list) and events:
            names = {}
            if isinstance(enc, dict):
                names = {c.get("id"): c.get("name") for c in enc.get("combatants", [])}
            lines = _combat_log_lines(events, names)
            if lines:
                out.append(("combat_log", {"lines": lines}))
    return out


def _combat_log_lines(events: list, names: dict) -> list:
    """把一次行动的事件翻成可读结算行：明骰命中/未命中 + 伤害过程 + 倒下。"""
    lines = []
    for e in events:
        if not isinstance(e, dict):
            continue
        k = e.get("kind")
        d = e.get("detail") or {}
        # 名字优先取事件自带（战斗结束后 encounter 快照没了也准），回退 id→name 映射
        actor = d.get("actor_name") or names.get(e.get("actor")) or e.get("actor") or ""
        target = d.get("target_name") or names.get(e.get("target")) or e.get("target") or ""
        if k in ("attack", "miss") and d.get("line"):
            lines.append(d["line"])             # 明骰加值链（含 → success/failure）
        elif k == "hit":
            dr, res, dmg = d.get("damage_raw"), d.get("resist", 1.0), d.get("damage")
            chain = []
            if dr is not None:
                chain.append(str(dr))
                if res not in (None, 1.0):
                    chain.append(f"×{res:g}")    # 抗性
                if d.get("crit"):
                    chain.append("×2")           # 大成功暴击翻倍
            if len(chain) > 1:
                proc = "".join(chain) + f"={dmg}"   # 有变换才显 =最终
            elif chain:
                proc = chain[0]
            else:
                proc = f"{dmg}"
            crit = "💥暴击 " if d.get("crit") else ""
            lines.append(f"  → {crit}{proc} 伤害（{target} {d.get('target_hp', '')}）")
        elif k == "kill":
            lines.append(f"  💀 {target} 倒下")
        elif k == "buff_applied":
            lines.append(f"{actor}：{d.get('effect', '获得增益')}")
        elif k == "move":
            lines.append(f"{actor} 移动 → 第 {d.get('to_rank')} 排")
        elif k == "flee":
            lines.append(f"{actor} 逃跑" + ("成功" if d.get("success") else "失败"))
    return lines


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
    # 战斗中 hp/stamina 的权威在 Combatant 上（end_combat 才写回 vitals）——直接读 vitals
    # 会让 HUD 显示过期血量。在场就从 encounter 的 player combatant 取，和战斗面板对齐。
    hp, max_hp = v.hp, v.max_hp
    stamina, max_stamina = v.stamina, v.max_stamina
    if s.encounter is not None:
        pc = s.encounter.combatants.get("player")
        if pc is not None:
            hp, max_hp = pc.hp, pc.max_hp
            stamina, max_stamina = pc.stamina, pc.max_stamina
    return {
        "started": True,
        "world": s.world_name,
        "in_combat": s.encounter is not None,
        "vitals": {
            "hp": hp, "max_hp": max_hp,
            "stamina": stamina, "max_stamina": max_stamina,
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


def panels_payload() -> dict:
    """侧栏面板数据：背包 / 技能 / 任务 / 地图。只读看板，每回合刷新。"""
    s = mcp_server.SESSION
    if not s.started:
        return {"started": False}
    st = s.state
    # 背包：名字 + 权威能力清单 + 有限 ttl
    inventory = [
        {"name": it["name"], "kind": it.get("kind", ""),
         "ttl": it.get("ttl", -1), "capabilities": it.get("capabilities", [])}
        for it in mcp_server._inventory_snapshot(st)
    ]
    # 技能：按 被动/主动/反应 分组，带 rank + 主动的 cost/冷却
    skills = []
    for sk in st.skills:
        if sk.active:
            kind = "active"
        elif getattr(sk, "reactive", None):
            kind = "reactive"
        else:
            kind = "passive"
        entry = {"id": sk.id, "name": sk.name, "desc": sk.desc,
                 "kind": kind, "rank": sk.rank}
        if sk.active:
            entry["cost"] = sk.active.cost
            entry["cooldown"] = sk.active.cooldown
            entry["remaining_cooldown"] = sk.active.remaining_cooldown
        skills.append(entry)
    # 任务：当前任务全量（stage / 已知事实 / 未解疑问）
    quests = [{"title": q.title, "stage": q.stage, "summary": q.summary,
               "known_facts": list(q.known_facts), "unresolved": list(q.unresolved)}
              for q in st.quest_log]
    # 地图：当前层全图（同 area 的所有房间 + 出口连线 + 当前/已访问标记）
    cur = st.position
    cur_room = s.world.get_room(cur)
    area = cur_room.area if cur_room else ""
    rooms = []
    for rid, room in s.world.rooms.items():
        if area and room.area != area:
            continue
        rooms.append({
            "id": rid, "name": room.name, "zone": room.zone,
            "x": room.coords[0], "y": room.coords[1],
            "exits": dict(room.exits),
            "locked": list(room.locked_exits.keys()),
            "current": rid == cur,
            "visited": (rid in st.room_snapshots) or rid == cur,
            "safe": ("safe_zone" in room.tags) or ("no_combat" in room.tags),
        })
    return {"started": True, "inventory": inventory, "skills": skills,
            "quests": quests, "map": {"rooms": rooms, "area": area}}


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


@app.get("/panels")
def panels() -> JSONResponse:
    return JSONResponse(panels_payload())


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
                        yield _sse("tool", {"name": payload["name"],
                                            "args": payload.get("args", "")})
                    elif kind == "tool_result":
                        # 从工具结果渲染结构面板（场景/骰子/战斗）
                        for rtype, rdata in _render_events(payload.get("name"),
                                                           payload.get("result")):
                            yield _sse("render", {"type": rtype, "data": rdata})
                    elif kind == "reset":
                        # 中间轮抢跑叙事 → 让前端清掉，等最后一轮重新流
                        yield _sse("reset", {})
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
