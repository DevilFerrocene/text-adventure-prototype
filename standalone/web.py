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
import time
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

# ── 会话持久化 ─────────────────────────────────────────────────────
# 一个"会话" = 引擎状态(mcp_server 的 save_game/autosave) + 对话历史(agent.messages)。
# 引擎状态本就自动存档；这里补上【对话】的持久化(sidecar)，并提供 新建/保存/列表/恢复。
# 当前会话的对话存在 _autosave.session.json，与引擎 _autosave.json 对齐，刷新/重启即恢复。
_SESSION_SUFFIX = ".session.json"
_CURRENT_SLOT = mcp_server.AUTOSAVE_SLOT   # "_autosave"


def _session_path(slot: str):
    return mcp_server.SAVE_DIR / f"{slot}{_SESSION_SUFFIX}"


def _auto_title() -> str:
    s = mcp_server.SESSION
    if s.started:
        room = s.world.get_room(s.state.position)
        loc = room.name if room else s.state.position
        return f"{s.world_name} · {loc} · 第{s.state.turn}回合"
    return time.strftime("%m-%d %H:%M")


def _save_conversation(slot: str, title: str = "") -> dict:
    s = mcp_server.SESSION
    meta = {
        "id": slot,
        "title": title or _auto_title(),
        "world": s.world_name if s.started else "",
        "turn": s.state.turn if s.started else 0,
        "updated": time.strftime("%Y-%m-%d %H:%M"),
    }
    try:
        payload = dict(meta, messages=_get_agent().messages)
        _session_path(slot).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return meta


def _load_conversation(slot: str) -> bool:
    p = _session_path(slot)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return False
    _get_agent().messages = msgs
    return True


def _autosave_conversation():
    """每回合末把当前会话的对话落盘（与引擎 autosave 对齐）。失败不阻塞。"""
    _save_conversation(_CURRENT_SLOT, _auto_title())


_SEED_MARK = "（系统提示"   # 开场喂给 GM 的权威种子前缀；不算玩家发言，叙事流里跳过


def _opening_seed() -> str:
    """全新开局：服务端先把游戏 start_game 起来，再把权威开场信息打包成给 GM 的种子，
    强制它【只依据真实场景】写开场，杜绝"不调工具、凭空脑补开场"。"""
    try:
        sg = mcp_server.start_game()
    except Exception:
        return ""
    scene = sg.get("scene", {}) or {}
    objs = "、".join(o.get("name", "") for o in scene.get("objects", []) if o.get("name"))
    exits_raw = scene.get("exits", {})
    exits = "、".join(exits_raw.keys()) if isinstance(exits_raw, dict) else ""
    canon = sg.get("world_canon", "")
    blurb = ""
    if isinstance(canon, dict):
        blurb = canon.get("setting_blurb", "")
    elif isinstance(canon, str):
        blurb = canon[:400]
    return (
        f"{_SEED_MARK}，非玩家发言：新游戏已开始、引擎已就位。请【只依据下列权威信息】"
        "写一段沉浸式开场叙事，严禁脑补任何武器/物品/尸体/未提及的地点，也不要再调用 start_game。）\n"
        f"世界基调：{blurb}\n当前位置：{scene.get('name', '')}\n"
        f"在场可见：{objs or '（无显著物件）'}\n出口：{exits or '（无）'}\n"
        "开场处境：你只有 6 点血、赤手空拳、身无分文、谁也不认识——这是一个『破局』开局。"
    )


def _transcript(messages: list) -> list:
    """从对话历史抽出【玩家可见叙事流】：玩家输入 + GM 那几段散文（跳过工具调用/抢跑/开场种子）。"""
    out = []
    for m in messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "user":
            if content.startswith(_SEED_MARK):    # 开场种子是喂给 GM 的，不是玩家发言
                continue
            for pref in _MODE_PREFIX.values():    # 去掉 说话/行动/场外 前缀
                if content.startswith(pref):
                    content = content[len(pref):]
                    break
            if content:
                out.append({"role": "player", "text": content})
        elif role == "assistant" and content and not m.get("tool_calls"):
            out.append({"role": "gm", "text": content})
    return out


def _get_agent():
    global _agent
    if _agent is None:
        # rich_ui：web 自己渲染 HUD/场景/骰子/战斗面板，GM 走散文模式（不粘状态块）
        _agent = make_agent(LLMConfig.from_env(), rich_ui=True)
        # 进程重启：把当前会话的对话从盘上接回来（引擎状态另由 autosave 惰性恢复）
        try:
            _load_conversation(_CURRENT_SLOT)
        except Exception:
            pass
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
        ambient = [a.get("name") for a in scene.get("ambient", []) if a.get("name")]
        out.append(("scene", {"objects": objs, "exits": exits, "ambient": ambient}))
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


def _board_payload(world, st) -> dict | None:
    """房间二维棋盘的渲染数据（仅供前端 UI 画图——这是宿主界面，不是 LLM，可用真坐标）。
    没挂 grid 的房间返回 None。"""
    room = world.get_room(st.position)
    grid = getattr(room, "grid", None) if room else None
    if not grid:
        return None
    tokens = []
    for oid, (x, y) in grid.objects.items():
        obj = world.get_object(oid)
        if not obj or obj.hidden:
            continue
        if obj.hidden_when_flag and st.flags.get(obj.hidden_when_flag):
            continue
        tokens.append({"x": x, "y": y, "name": obj.name, "kind": "object"})
    for nm, (x, y) in grid.ambient.items():
        tokens.append({"x": x, "y": y, "name": nm, "kind": "ambient"})
    for nm, (x, y) in grid.landmarks.items():
        tokens.append({"x": x, "y": y, "name": nm, "kind": "landmark"})
    for direction, (x, y) in grid.exits.items():
        target = room.exits.get(direction, "")
        troom = world.get_room(target)
        tokens.append({"x": x, "y": y, "name": (troom.name if troom else direction),
                       "dir": direction, "kind": "exit"})
    # 探索点：未揭示的画成 ?（只给 hint，payload 不外泄）
    for p in mcp_server._active_pois(st, grid):
        tokens.append({"x": p.cell[0], "y": p.cell[1], "name": p.hint, "kind": "poi"})
    # 敌人 + 玩家位置：战斗中读【实时战局】（combatant.cell 随走位更新），否则读探索层
    enc = mcp_server.SESSION.encounter
    in_cell_combat = enc is not None and any(c.cell is not None for c in enc.combatants.values())
    px, py = st.cell
    if in_cell_combat:
        for cid, c in enc.combatants.items():
            if c.cell is None or c.is_dead:
                continue
            if c.side == "enemy":
                tokens.append({"x": c.cell[0], "y": c.cell[1], "name": c.name,
                               "kind": "enemy", "state": "hostile",
                               "hp": c.hp, "max_hp": c.max_hp})
            elif cid == "player":
                px, py = c.cell
    else:
        for fe in st.enemy_field:
            tmpl = world.get_enemy(fe["enemy_id"])
            tokens.append({"x": fe["cell"][0], "y": fe["cell"][1],
                           "name": (tmpl.name if tmpl else fe["enemy_id"]),
                           "kind": "enemy", "state": fe.get("state", "idle")})
    return {
        "room": room.name if room else st.position,
        "width": grid.width, "height": grid.height,
        "player": {"x": px, "y": py},
        "blocked": [list(b) for b in grid.blocked],
        "tokens": tokens, "in_combat": in_cell_combat,
    }


_KIND_LABEL = {"npc": "人物", "scenery": "景物", "container": "容器", "document": "文书",
               "item": "物品", "陈设": "陈设", "生物": "生物"}
_WEATHER_LABEL = {"clear": "晴", "misty": "雾", "mist": "雾", "rain": "雨",
                  "storm": "暴风", "snow": "雪", "fog": "雾", "overcast": "阴"}
_PHASE_LABEL = {"dawn": "破晓", "morning": "清晨", "noon": "正午", "afternoon": "午后",
                "dusk": "黄昏", "evening": "傍晚", "night": "夜", "midnight": "深夜"}


def _dist_label(sp: dict | None) -> str:
    """把棋盘 spatial（方位/步/远近）压成一行距离标签。无 grid/未钉格 → 空串。"""
    if not sp:
        return ""
    if sp.get("in_reach"):
        return "手边"
    bearing = sp.get("bearing", "")
    steps = sp.get("steps")
    if steps is not None and steps <= 3:
        return f"{steps} 步·{bearing}" if bearing else f"{steps} 步"
    return f"{sp.get('proximity', '')}·{bearing}" if bearing else sp.get("proximity", "")


def _scene_objects(world, st) -> dict:
    """当前场景对象清单（名/类/类别/距离·方位），供右栏「场景对象」面板。距离取棋盘真值。"""
    room = world.get_room(st.position)
    if not room:
        return {"room": st.position, "objects": [], "exits": []}
    snap = mcp_server._room_snapshot(world, st)
    out = []

    def push(name, kind, cat, sp, extra=None):
        row = {"name": name, "kind": kind, "kind_label": _KIND_LABEL.get(kind, kind),
               "cat": cat, "dist": _dist_label(sp), "steps": (sp or {}).get("steps")}
        if extra:
            row.update(extra)
        out.append(row)

    for o in snap.get("objects", []):
        verbs = o.get("callable_verbs", [])
        interactable = bool(o.get("takable")) or any(v != "inspect" for v in verbs)
        kind = o.get("kind", "")
        cat = "生物" if kind == "npc" else ("可交互" if interactable else "地形")
        push(o["name"], kind, cat, o.get("spatial"))
    for a in snap.get("ambient", []):
        push(a["name"], "陈设", "地形", a.get("spatial"))
    for fe in st.enemy_field:
        tmpl = world.get_enemy(fe["enemy_id"])
        nm = tmpl.name if tmpl else fe["enemy_id"]
        sp = mcp_server._cell_annotation(st, room, fe["cell"])
        push(nm, "生物", "生物", sp, {"state": fe.get("state", "idle")})

    out.sort(key=lambda e: (e.get("steps") is None, e.get("steps") or 0))
    exits = [{"dir": d, "locked": d in (room.locked_exits or {})} for d in room.exits]
    return {"room": room.name, "objects": out, "exits": exits}


def _environment(st) -> dict:
    wt = st.world_time
    return {"weather": _WEATHER_LABEL.get(wt.weather, wt.weather or "—"),
            "phase": _PHASE_LABEL.get(wt.phase, wt.phase or "—"),
            "day": wt.day}


def panels_payload() -> dict:
    """侧栏面板数据：背包 / 技能 / 任务 / 地图 / 场地（棋盘）+ 场景对象 / 环境。只读看板，每回合刷新。"""
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
            "quests": quests, "map": {"rooms": rooms, "area": area},
            "board": _board_payload(s.world, st),
            "scene": _scene_objects(s.world, st), "environment": _environment(st)}


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


@app.post("/combat_move")
async def combat_move(request: Request) -> JSONResponse:
    """战斗中点棋盘空格走位：引擎直接 declare_intent move 到 (x,y)（坐标不进 GM）。
    回传走位事件(含借机攻击)、新战局 hud/panels、next_actor——前端据此渲染 + 决定是否让 GM 续敌方回合。"""
    s = mcp_server.SESSION
    if not s.started or s.encounter is None:
        return JSONResponse({"ok": False, "error": "不在战斗中。"})
    body = await request.json()
    res = mcp_server.declare_intent("player", "move", target=f"{int(body.get('x', -1))},{int(body.get('y', -1))}")
    out = dict(res)
    if res.get("ok"):
        enc = s.encounter
        names = {c.id: c.name for c in enc.combatants.values()} if enc else {}
        steps = next((ev.get("detail", {}).get("steps") for ev in res.get("events", [])
                      if ev.get("kind") == "move"), None)
        out["note"] = f"你走位 {steps} 步。" if steps else "你走位。"
        out["combat_log"] = _combat_log_lines(res.get("events", []), names)
        out["hud"] = hud_payload()
        out["panels"] = panels_payload()
        # 让 GM 知情（无需它再操作）：把这步走位 + 借机攻击注入下个回合上下文
        note = f"玩家在战斗中点棋盘走位（{steps or '若干'} 步）。"
        if out["combat_log"]:
            note += "（其间：" + "；".join(out["combat_log"]) + "）"
        bf = mcp_server._battlefield_text(s.encounter)
        if bf:
            note += f" 当前战场精确坐标：{bf}。"
        _get_agent().note_event(note)
    return JSONResponse(out)


@app.post("/move_cell")
async def move_cell(request: Request) -> JSONResponse:
    """前端点击棋盘空格走位：引擎直接寻路移动（不走 GM、不泄坐标）。
    回传移动结果 + 揭示/进战信息 + 刷新后的 hud/panels，供前端就地渲染。"""
    body = await request.json()
    res = mcp_server.goto_cell(int(body.get("x", -1)), int(body.get("y", -1)))
    if res.get("ok"):
        res["hud"] = hud_payload()
        res["panels"] = panels_payload()
        # 让 GM 知情（无需它再操作）：把这步走位 + 揭示/进战注入下个回合上下文
        locale = (((res.get("scene") or {}).get("grid") or {}) or {}).get("player_locale", "")
        note = f"玩家点击棋盘自行走位（{res.get('steps', 0)} 步）" + (f"，现在{locale}" if locale else "") + "。"
        rv = res.get("revealed")
        if rv:
            note += f" 途中揭示了探索点：{rv.get('reveal', '')}"
            if rv.get("kind") == "ambush":
                note += "（伏击，已进入战斗）"
        if res.get("spotted"):
            note += f" {('、'.join(res['spotted']))} 发现了他，已进入战斗。"
        bf = mcp_server._battlefield_text(mcp_server.SESSION.encounter)
        if bf:
            note += f" 当前战场精确坐标：{bf}。"
        _get_agent().note_event(note)
    return JSONResponse(res)


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
            # 全新开局：服务端【确定性】start_game 并把权威开场喂给 GM——
            # 否则 GM 可能不调工具、凭空脑补一个错的开场（实测会，且 SESSION 没起）。
            if not text and not mcp_server.SESSION.started:
                full = _opening_seed()
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
            # 回合末推一次最新状态条 + 落盘对话（与引擎 autosave 对齐）
            _autosave_conversation()
            yield _sse("hud", hud_payload())

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── 会话管理端点（前端会话菜单用）──────────────────────────────────
@app.get("/session/current")
def session_current() -> JSONResponse:
    """页面加载时调：恢复进行中的会话（引擎状态 + 对话叙事流）。"""
    _get_agent()                                  # 创建时已尝试接回对话
    if not mcp_server.SESSION.started:
        try:
            mcp_server._maybe_restore_autosave()  # 引擎状态接回
        except Exception:
            pass
    started = mcp_server.SESSION.started
    tr = _transcript(_get_agent().messages) if started else []
    return JSONResponse({"started": started, "transcript": tr, "hud": hud_payload()})


@app.post("/session/new")
async def session_new() -> JSONResponse:
    """新对话：清当前自动存档（引擎+对话）+ 重置引擎为未开局 + 全新对话。
    之后前端发空开局回合，GM 干净起手。"""
    global _agent
    with _lock:
        for p in (mcp_server.SAVE_DIR / f"{_CURRENT_SLOT}.json", _session_path(_CURRENT_SLOT)):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        mcp_server.SESSION = mcp_server.Session()              # 引擎置未开局
        _agent = make_agent(LLMConfig.from_env(), rich_ui=True)  # 全新对话
    return JSONResponse({"ok": True})


@app.post("/session/save")
async def session_save(request: Request) -> JSONResponse:
    """把当前会话存成命名快照（引擎 slot + 对话 sidecar）。"""
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not mcp_server.SESSION.started:
        return JSONResponse({"ok": False, "error": "尚未开局，没有可保存的会话。"})
    with _lock:
        slot = "sess_" + time.strftime("%Y%m%d_%H%M%S")
        eng = mcp_server.save_game(slot)
        if not eng.get("ok"):
            return JSONResponse(eng)
        meta = _save_conversation(eng["slot"], title)
    return JSONResponse({"ok": True, **meta})


@app.get("/session/list")
def session_list() -> JSONResponse:
    """列出所有命名会话快照（不含当前自动存档）。"""
    out = []
    for p in mcp_server.SAVE_DIR.glob(f"*{_SESSION_SUFFIX}"):
        slot = p.name[: -len(_SESSION_SUFFIX)]
        if slot == _CURRENT_SLOT:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"id": slot, "title": d.get("title", slot),
                    "world": d.get("world", ""), "turn": d.get("turn", 0),
                    "updated": d.get("updated", "")})
    out.sort(key=lambda x: x["updated"], reverse=True)
    return JSONResponse({"sessions": out})


@app.post("/session/resume")
async def session_resume(request: Request) -> JSONResponse:
    """恢复某个命名会话：引擎状态 + 对话 + 叙事流，并设为当前会话。"""
    body = await request.json()
    sid = (body.get("id") or "").strip()
    with _lock:
        eng = mcp_server.load_game(sid)
        if not eng.get("ok"):
            return JSONResponse(eng)
        if not _load_conversation(sid):
            return JSONResponse({"ok": False, "error": "该会话的对话记录缺失。"})
        # 设为当前会话：引擎 + 对话都同步到自动存档槽，后续自动存延续这一局
        mcp_server._autosave()
        _autosave_conversation()
        tr = _transcript(_get_agent().messages)
    return JSONResponse({"ok": True, "transcript": tr, "hud": hud_payload()})


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
