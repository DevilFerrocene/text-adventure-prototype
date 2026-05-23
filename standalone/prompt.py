"""System prompt：把 play/SKILL.md 当 GM 的行为规范，按前端形态【二选一】拼装。

SKILL.md 一份双用：既是 MCP 宿主的 skill 文件，也是独立运行的 GM 行为规范。
独立运行（standalone）时本模块在它之上做几件事，省得宿主味儿的东西混进提示词：
- 剥掉 skill 的 YAML frontmatter（name/description/触发词——那是宿主用的，独立运行无意义）；
- 前面接一段【运行机制】说明（独立程序里工具自动执行、结果喂回，文字回复=玩家画面）；
- 【前台输出格式】按前端形态**二选一**，不再"全量塞 + 末尾否定"：
    · 纯文本前端（CLI/TUI/MCP 宿主）→ 用 SKILL 里的"粘贴版"（GM 自己贴 HUD/骰子/场景/战斗块）；
    · 富 UI 前端（web，自渲染面板）→ 整章替换成"散文版"（面板交给界面，GM 只写散文）。
  这样富 UI 模式既不读那一大段会被否定的死重，也没有自相矛盾的"覆盖便签"。
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).parent.parent

# 优先用 .claude 版（权威），回退 .agents
_SKILL_CANDIDATES = [
    _HERE / ".claude" / "skills" / "play" / "SKILL.md",
    _HERE / ".agents" / "skills" / "play" / "SKILL.md",
]

# SKILL.md 里"前台输出格式·粘贴版"那一章被这对 HTML 注释标记包住，便于按前端整章替换。
# 用 startswith 匹配，START 标记后面允许带说明文字。
_FE_START = "<!-- FRONTEND:PASTE:START"
_FE_END = "<!-- FRONTEND:PASTE:END -->"

# 运行机制说明：独立运行特有（宿主模式由宿主自己交代），接在 SKILL 正文前。
_RUNTIME_INTRO = """你是一个文字冒险游戏的 GM（游戏主持人），运行在一个独立程序里。

【运行机制——必读】
- 你能调用一组游戏引擎工具（见下方行为规范）。你调用工具后，程序会自动执行并把结果返回给你；
  工具结果只有你能看到，玩家看不到。
- 你的每条**文字回复**（不含工具调用）会原样显示给玩家——这就是玩家看到的游戏画面。
  所以：调完工具拿到状态后，再写给玩家的那段沉浸式回复，严格遵守下方【前台输出格式】与【叙事风格】。
- 一个回合内可以调多个工具；全部调完、信息够了，再输出给玩家的那段文字。

以下是你作为 GM 的完整行为规范：

"""

_TAIL = ("\n\n（记住：先调工具拿权威状态，再写贴合世界文风的叙事。"
         "绝不脑补数值，绝不用叙事替代机制。）\n")

# 富 UI 前端的"前台输出格式·散文版"——整章替换粘贴版（不再否定覆盖）。
_FRONTEND_PROSE = """## 前台输出格式（本局运行在带界面的前端）

HUD 状态条、场景清单（物件 / 出口）、明骰骰子卡、战斗面板（血条 / 列阵 / 行动序）——\
全部由**界面自动渲染**：界面直接读引擎工具结果来画，不经你的手。

所以：
- 你照常调用【所有】该调的工具拿权威状态（`get_scene`；`roll_check` 后照旧 `explain_last_roll`；\
战斗里照旧 `declare_intent` / `deal_damage` 等）——界面正是靠这些工具结果渲染面板的，少调一个面板就空。
- 你的【文字回复只写叙事散文】：沉浸的故事、对白、描写、玩家行动的后果。\
**不要**粘贴任何 HUD 状态条、场景清单、骰子卡、战斗面板——那些界面会出，你再贴就重复了。\
玩家从界面看状态，从你的文字读故事。
- **尤其别罗列清单**：不准写「能看见的：A、B、C」「出口：北/东」这种 bullet 物件表或出口表——\
那是场景面板的活。要带出某个物件/出口，就把它【自然织进散文】（"墙角那座剑痕累累的誓约碑"），\
最多点一两个有戏的，**绝不列表、不写 bullet、不报全场清单**。"""


def _strip_frontmatter(text: str) -> str:
    """剥掉 SKILL.md 顶部的 YAML frontmatter（--- … ---）。宿主靠它识别 skill，
    独立运行嵌进提示词只是噪音（还含 /play 触发词等无关内容）。"""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    nl = text.find("\n", end + 1)
    return text[nl + 1:] if nl != -1 else ""


def _select_frontend(skill: str, rich_ui: bool) -> str:
    """把 SKILL 里被标记的"前台输出格式"章节按前端【二选一】替换；两种模式都剥掉标记。
    没找到标记时原样返回（容错，不至于把整段提示词搞没）。"""
    start = skill.find(_FE_START)
    if start == -1:
        return skill
    start_close = skill.find("-->", start)
    if start_close == -1:
        return skill
    end = skill.find(_FE_END, start_close)
    if end == -1:
        return skill
    pre = skill[:start].rstrip()
    paste_block = skill[start_close + len("-->"):end].strip()
    post = skill[end + len(_FE_END):].lstrip()
    middle = _FRONTEND_PROSE if rich_ui else paste_block
    return f"{pre}\n\n{middle}\n\n{post}"


def load_system_prompt(rich_ui: bool = False) -> str:
    """组装 system prompt：运行机制说明 + SKILL 正文（前台格式按前端二选一）。

    rich_ui=True（web 等自渲染面板的前端）：前台格式用散文版，GM 不贴状态块。
    rich_ui=False（CLI/TUI 纯文本前端，或 MCP 宿主直读 SKILL）：用粘贴版，GM 照常贴 HUD/骰子/场景。
    """
    skill_text = ""
    for path in _SKILL_CANDIDATES:
        if path.exists():
            skill_text = path.read_text(encoding="utf-8")
            break
    if not skill_text:
        skill_text = "（未找到 SKILL.md，按通用 TRPG GM 行事。）"
    skill_text = _strip_frontmatter(skill_text)
    skill_text = _select_frontend(skill_text, rich_ui)
    return _RUNTIME_INTRO + skill_text.strip() + _TAIL
