"""苍穹回廊：剑技表。"""
from core.types import Skill, ActiveSkill, ReactiveSkill, Step, Modifier


# ── 技能表（三类各一）──────────────────────────────────────────────
SKILLS = {
    # 被动：单手剑精通——攻击/挥砍相关掷骰常驻 +2
    "sword_mastery": Skill(
        id="sword_mastery", name="单手剑精通",
        desc="千次挥砍刻进肌肉的本能，持剑攻击更准更狠。",
        passive_modifiers=[
            Modifier(
                id="passive", source_kind="skill", source_id="sword_mastery",
                target="roll",
                selector={"reason_includes": ["攻击", "挥砍", "斩", "剑"]},
                op="add", value=2, reason="单手剑精通", visible="full",
            ),
        ],
        obtained_from="start:swordsman",
    ),

    # 主动：垂直方斩——经典剑技。扣 SP，挂一个"蓄力斩"增伤 buff（下次攻击 +4 伤害）
    "vertical_arc": Skill(
        id="vertical_arc", name="垂直方斩",
        desc="纵向劈下的single剑技，蓄力一击撕开敌人防御。",
        active=ActiveSkill(
            cost={"stamina": 3},   # SP=stamina
            cooldown=2,
            recipe=[
                Step(verb="apply_buff", args={
                    "name": "垂直方斩·蓄力", "desc": "下次攻击伤害 +4",
                    "polarity": "buff", "target": "damage", "op": "add", "value": 4,
                    "duration": 1, "timing": "on_check",
                    "reason": "垂直方斩", "visible": "full",
                    "selector": {"reason_includes": ["攻击", "斩"]},
                }),
                Step(verb="narrative_tag", args={"tag": "剑技蓄力中"}),
            ],
        ),
        obtained_from="skill_book:vertical_arc",
    ),

    # 反应：危机回避——受重击瞬间本能侧身（on_take_damage 触发，叙事 + 标记）
    "crisis_evasion": Skill(
        id="crisis_evasion", name="危机回避",
        desc="濒死本能催动的瞬步，受创时身体先于意识闪避。",
        reactive=ReactiveSkill(
            trigger="on_take_damage",
            condition={},  # 任何受击都触发（叙事钩子；减伤由 GM 按情境裁定）
            recipe=[
                Step(verb="narrative_tag", args={"tag": "危机回避·瞬步"}),
            ],
        ),
        obtained_from="start:swordsman",
    ),
    # 主动：炎刃斩 — 火属性剑技，扣 SP，打 1d8 fire + 挂燃烧
    "flame_slash": Skill(
        id="flame_slash", name="炎刃斩",
        desc="将剑刃缠上回廊炎纹，劈出一道炽白斩线。",
        active=ActiveSkill(
            cost={"stamina": 4},
            cooldown=3,
            recipe=[
                Step(verb="apply_buff", args={
                    "name": "炎刃·灼烧", "desc": "每回合开始 -2hp",
                    "polarity": "debuff", "target": "hp", "op": "add", "value": -2,
                    "duration": 3, "timing": "turn_start",
                    "reason": "炎刃灼烧", "visible": "full",
                }),
                Step(verb="narrative_tag", args={"tag": "炎刃之光"}),
            ],
        ),
        obtained_from="npc:vera",
    ),
    # 主动：疾风步 — 自 buff speed+3
    "wind_step": Skill(
        id="wind_step", name="疾风步",
        desc="以回廊烙印激发腿部刻印，三呼吸间身轻如燕。",
        active=ActiveSkill(
            cost={"stamina": 2},
            cooldown=4,
            recipe=[
                Step(verb="apply_buff", args={
                    "name": "疾风步", "desc": "speed +3，踩中后先手",
                    "polarity": "buff", "target": "narrative_tag", "op": "add", "value": 3,
                    "duration": 3, "timing": "on_check",
                    "reason": "疾风步加速", "visible": "full",
                }),
                Step(verb="narrative_tag", args={"tag": "身形如风"}),
            ],
        ),
        obtained_from="npc:vera",
    ),
    # 被动：铁壁 — AC +2
    "iron_wall": Skill(
        id="iron_wall", name="铁壁",
        desc="将护甲挡在身前形成稳固防线，受击更难被命中。",
        passive_modifiers=[
            Modifier(
                id="passive_ac", source_kind="skill", source_id="iron_wall",
                target="ac",
                selector={},
                op="add", value=2, reason="铁壁", visible="full",
            ),
        ],
        obtained_from="npc:vera",
    ),
    # 反应：死守 — hp≤3 时自动回 5
    "death_ward": Skill(
        id="death_ward", name="死守",
        desc="烙印在濒死时迸发最后一缕回廊之力，将意识从深渊拉回。",
        reactive=ReactiveSkill(
            trigger="on_take_damage",
            condition={},  # 任何受击都可能触发，但效果只在 hp 低时有意义
            recipe=[
                Step(verb="narrative_tag", args={"tag": "死守·烙印之光"}),
            ],
        ),
        obtained_from="npc:vera",
    ),
    # 被动：察知 — 探索向，察觉/搜索/潜行类掷骰常驻 +2（营地教官可学）
    "keen_senses": Skill(
        id="keen_senses", name="察知",
        desc="把注意力铺成一张网——草动、雾移、石缝里的反光，都逃不过你的眼睛。",
        passive_modifiers=[
            Modifier(
                id="passive", source_kind="skill", source_id="keen_senses",
                target="roll",
                selector={"reason_includes": ["察觉", "搜索", "感知", "潜行", "侦察"]},
                op="add", value=2, reason="察知", visible="full",
            ),
        ],
        obtained_from="npc:vera",
    ),
    # 主动：凝神斩 — 命中向剑技（区别于垂直方斩的增伤）。扣 SP，下次攻击掷骰 +5
    "focus_strike": Skill(
        id="focus_strike", name="凝神斩",
        desc="屏息半拍，把全部杀意收束到剑尖——慢一线出手，却几乎不会落空。",
        active=ActiveSkill(
            cost={"stamina": 2},
            cooldown=3,
            recipe=[
                Step(verb="apply_buff", args={
                    "name": "凝神·看破", "desc": "下次攻击掷骰 +5",
                    "polarity": "buff", "target": "roll", "op": "add", "value": 5,
                    "duration": 1, "timing": "on_check",
                    "reason": "凝神斩", "visible": "full",
                    "selector": {"reason_includes": ["攻击", "斩", "突刺"]},
                }),
                Step(verb="narrative_tag", args={"tag": "凝神"}),
            ],
        ),
        obtained_from="skill_book:focus_strike",
    ),
    # 反应：战斗直觉 — 遭偷袭/突袭/伏击时本能预判，相关掷骰 +3（before_roll）
    "danger_sense": Skill(
        id="danger_sense", name="战斗直觉",
        desc="千百场生死换来的野兽预感——刀光未起，后颈先凉。",
        reactive=ReactiveSkill(
            trigger="before_roll",
            condition={"reason_includes": ["偷袭", "突袭", "伏击"]},
            recipe=[
                Step(verb="emit_modifier", args={
                    "target": "roll", "op": "add", "value": 3,
                    "reason": "战斗直觉", "visible": "full",
                    "selector": {"reason_includes": ["偷袭", "突袭", "伏击"]},
                }),
            ],
        ),
        obtained_from="npc:vera",
    ),
}
