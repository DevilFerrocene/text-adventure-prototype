"""System prompt：把 play/SKILL.md 当 GM 的 system prompt。

SKILL.md 几乎原样可用（它本就是给 LLM 当 GM 的指令）。只加一段适配头，
说明独立运行的上下文：你就是 GM，工具会被自动执行，结果喂回给你。
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).parent.parent

# 优先用 .claude 版（权威），回退 .agents
_SKILL_CANDIDATES = [
    _HERE / ".claude" / "skills" / "play" / "SKILL.md",
    _HERE / ".agents" / "skills" / "play" / "SKILL.md",
]

_ADAPTER_HEAD = """\
你是一个文字冒险游戏的 GM（游戏主持人），运行在独立程序里。

【运行机制——必读】
- 你能调用一组游戏引擎工具（见下方 SKILL 说明）。你调用工具后，程序会自动执行并把
  结果返回给你；工具结果只有你能看到，玩家看不到。
- 你的每条**文字回复**（不含工具调用）会原样显示给玩家——这就是玩家看到的游戏画面。
  所以：调完工具拿到状态后，写一段给玩家的沉浸式回复（严格遵守下方【前台输出格式】
  和【叙事风格】）。
- 一个回合内可以调多个工具；全部调完、信息够了，再输出给玩家的那段文字。

下面是你作为 GM 的完整行为规范（SKILL）：

----- SKILL 开始 -----
"""

_ADAPTER_TAIL = """
----- SKILL 结束 -----

记住：先调工具拿权威状态，再写贴合世界文风的叙事 + HUD。绝不脑补数值，绝不用叙事替代机制。
"""


def load_system_prompt() -> str:
    """组装 system prompt：适配头 + SKILL.md 正文。"""
    skill_text = ""
    for path in _SKILL_CANDIDATES:
        if path.exists():
            skill_text = path.read_text(encoding="utf-8")
            break
    if not skill_text:
        skill_text = "（未找到 SKILL.md，按通用 TRPG GM 行事。）"
    return _ADAPTER_HEAD + skill_text + _ADAPTER_TAIL
