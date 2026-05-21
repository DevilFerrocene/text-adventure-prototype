"""工具桥：把引擎的 40 个 MCP 工具暴露给 LLM，进程内直接派发。

不走 MCP-over-stdio 协议——独立版是单进程，引擎工具就是 mcp_server 里的普通函数。
从引擎自己的 FastMCP 注册表（mcp._tool_manager）拿 name/description/JSON-schema/fn，
零手写 schema。LLM 调工具 → 直接 fn(**args) → 共享同一个 SESSION。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import mcp_server


def build_tools() -> tuple[list[dict], dict[str, Callable]]:
    """返回 (OpenAI tool specs, name→fn 派发表)。"""
    specs: list[dict] = []
    dispatch: dict[str, Callable] = {}
    for tool in mcp_server.mcp._tool_manager.list_tools():
        specs.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "parameters": tool.parameters,
            },
        })
        dispatch[tool.name] = tool.fn
    return specs, dispatch


def call_tool(dispatch: dict[str, Callable], name: str, args_json: str) -> dict[str, Any]:
    """执行一次工具调用。永不抛异常——失败也返回结构化结果，喂回 LLM 让它自己纠。"""
    fn = dispatch.get(name)
    if fn is None:
        return {"ok": False, "error": f"未知工具 {name!r}"}
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"参数不是合法 JSON: {exc}"}
    if not isinstance(args, dict):
        return {"ok": False, "error": "参数必须是对象"}
    try:
        result = fn(**args)
        return result if isinstance(result, dict) else {"ok": True, "result": result}
    except TypeError as exc:
        return {"ok": False, "error": f"参数不匹配: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
