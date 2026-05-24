"""无界面 CLI：自检 + 命令行一问一答，验证 agent loop 跑得通（富界面见 standalone.web）。

用法：
    python -m standalone.cli          # 开一局，命令行一问一答
    python -m standalone.cli --check  # 只自检（工具桥/prompt/配置），不调 LLM
"""
from __future__ import annotations

import sys

from .config import LLMConfig
from .prompt import load_system_prompt
from .tools import build_tools


def self_check() -> int:
    """不调 LLM 的自检：工具桥、prompt、配置是否就绪。"""
    print("=== 独立运行层自检 ===")
    specs, dispatch = build_tools()
    print(f"✓ 工具桥：{len(specs)} 个工具就绪")
    sp = load_system_prompt()
    print(f"✓ system prompt：{len(sp)} 字")
    # 世界引用完整性（悬空 id 在作者期就抓出来，别等玩到那里才崩）
    import mcp_server
    from runtime.game_world import GameWorld
    for wname, wmod in mcp_server.WORLDS.items():
        probs = GameWorld(content_module=wmod).validate()
        if probs:
            print(f"⚠️  世界 {wname} 有 {len(probs)} 处引用问题：")
            for p in probs:
                print(f"     - {p}")
        else:
            print(f"✓ 世界 {wname}：引用完整性干净")
    cfg = LLMConfig.from_env()
    err = cfg.validate()
    if err:
        print(f"⚠️  LLM 配置：{err}")
    else:
        print(f"✓ LLM 配置：model={cfg.model} base_url={cfg.base_url}")
    print("自检完成。" + ("（补好 key 即可真玩）" if err else "（可 python -m standalone.cli 开玩）"))
    return 0


def play() -> int:
    from .agent import make_agent
    cfg = LLMConfig.from_env()
    err = cfg.validate()
    if err:
        print(f"无法启动：{err}")
        return 1

    agent = make_agent(cfg)
    if cfg.debug:
        agent.on_tool_call = lambda name, args: print(f"  [tool] {name}({args})", file=sys.stderr)

    print("=== 文字冒险（独立版）===")
    print("（直接输入行动；输入 quit 退出）\n")

    # 开局：空输入让 GM 起手
    opening = agent.run_turn("")
    print(opening + "\n")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0
        if line.lower() in ("quit", "exit", "退出"):
            print("再见。")
            return 0
        if not line:
            continue
        reply = agent.run_turn(line)
        print("\n" + reply + "\n")


def main() -> int:
    if "--check" in sys.argv:
        return self_check()
    return play()


if __name__ == "__main__":
    raise SystemExit(main())
