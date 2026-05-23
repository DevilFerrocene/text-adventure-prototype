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

# 富 UI 覆盖：web 等带界面的前端会从工具结果【自动渲染】HUD/场景/骰子/战斗，
# 所以 GM 不该再把这些粘进文字。只写散文。（CLI 这类纯文本前端不加这段，仍照常粘贴。）
_RICH_UI_OVERRIDE = """
========================================
⚠️ 富 UI 覆盖（本局运行在带界面的前端，最高优先级，覆盖上面【前台输出格式】）
========================================
HUD 状态条、场景清单（可查看物件/出口）、明骰骰子卡、战斗面板（血条/列阵/行动序）——
全部由界面【自动渲染】，直接读引擎工具结果，不经你的手。

所以：
- 你照常调【所有】工具拿权威状态（get_scene / roll_check 后照旧调 explain_last_roll /
  战斗工具等）——界面正是靠这些工具结果来渲染面板的，少调一个面板就空。
- 但你的【文字回复只写叙事散文】：沉浸的故事、对白、描写。**不要**再粘贴任何 HUD 代码块、
  场景清单、骰子卡、combat_hud——那些【前台输出格式】里要你贴的状态块，在这里【一律作废】，
  贴了反而和界面重复。玩家从界面看状态，从你的文字读故事。
"""


def load_system_prompt(rich_ui: bool = False) -> str:
    """组装 system prompt：适配头 + SKILL.md 正文（+ 富 UI 覆盖）。

    rich_ui=True（web/未来 TUI 等会自渲染面板的前端）：追加散文模式覆盖，GM 不再粘状态块。
    rich_ui=False（CLI 等纯文本前端、或 MCP 宿主）：保持原样，GM 照常粘贴 HUD/骰子/场景。
    """
    skill_text = ""
    for path in _SKILL_CANDIDATES:
        if path.exists():
            skill_text = path.read_text(encoding="utf-8")
            break
    if not skill_text:
        skill_text = "（未找到 SKILL.md，按通用 TRPG GM 行事。）"
    prompt = _ADAPTER_HEAD + skill_text + _ADAPTER_TAIL
    if rich_ui:
        prompt += _RICH_UI_OVERRIDE
    return prompt
