"""苍穹回廊 · Skybound Spire — 日式异世界逐层攻略。

世界观：一座悬浮在云海之上、向上无限延伸的层状巨塔「苍穹回廊」。
每层是一片独立界域，尽头有「楼层首领」把守通往上层的回廊门——击败它才能上行。
进塔者被「回廊烙印」标记：死亡即真死，只能向上、无法回头。传说登顶可实现一愿。

第一层「雾语草原」：新手界域。营地（安全区）→ 草原（刷怪/支线）→
迷宫 → 首领战场。核心循环：探索 → 打怪升级 → 学剑技 → 攻略首领 → 解锁上层。

术语（简洁现代风）：剑技=技能 / 属性=炎霜雷影 / 等级=等级 / Boss=首领 / 战技点=SP。
"""

from core.types import (
    Room, GameObject, Affordance, GameState, WorldCanon, InventoryItem,
    ActorProfile, VitalStats, WorldTime, QuestEntry, EnemyTemplate,
    Skill, ActiveSkill, ReactiveSkill, Step, Modifier,
    RuleBook,
)
from runtime.game_world import GameWorld


SPIRE_CANON = WorldCanon(
    setting_blurb=(
        "苍穹回廊：悬浮于云海之上的层状巨塔，逐层攻略向上。剑与少量魔法共存，"
        "日式异世界冒险风。死亡即真死（回廊烙印），只能上行。属性相克：炎/霜/雷/影。"
    ),
    forbidden=["现代科技", "枪械", "现代俚语", "汽车", "电子设备", "回到地面/逃离塔"],
    aesthetic_tags=["日式异世界", "浮空塔", "剑技", "热血战斗", "迷宫探索", "升级变强"],
    name_style="日式幻想风人名地名，可带欧式奇幻词根（界域、回廊、烙印、刻印）",
)


# ── 怪物表（第一层 + 楼层首领）──────────────────────────────────────
# damage_types_resist：>1.0 易伤（被克制），<1.0 抗性。空 dict = 全 1.0。
ENEMIES = {
    # 破局门槛怪：杀人兔——城外第一道坎，赤手空拳弄不死，有把武器才敢碰
    "killer_rabbit": EnemyTemplate(
        id="killer_rabbit", name="杀人兔",
        archetype="brute_low", hp=8, max_hp=8, ac=10, speed=11,
        damage_expr="1d4", damage_type="pierce",
        behavior_profile="aggressive", skills=[],
        damage_types_resist={},
        loot=["rabbit_pelt"],
        flavor=(
            "一团雪白的、看起来人畜无害的长耳兔子，蹲在草地上抽动鼻子——"
            "直到它转过头，你看见那不该长在兔子嘴里的两排尖牙，和沾着暗褐色干渍的爪子。"
            "新人坟堆里十有八九埋的不是被首领杀的，是被它咬断脚筋、再慢慢啃死的。"
            "赤手空拳别碰它：你 1d1 的拳头要打它八下，它 1d4 的牙打你两口就够。"
        ),
    ),
    # 草原杂兵：冲撞型野猪，皮糙肉厚但慢
    "frenzy_boar": EnemyTemplate(
        id="frenzy_boar", name="狂奔野猪",
        archetype="brute_low", hp=9, max_hp=9, ac=9, speed=7,
        damage_expr="1d6", damage_type="blunt",
        behavior_profile="aggressive", skills=[],
        damage_types_resist={"fire": 1.5},  # 怕火（烤猪）
        loot=["boar_hide"],
        flavor=(
            "鬃毛硬如钢针的草原杂兵，一对充血的小眼只会锁定一个目标——"
            "然后直线撞上去。低阶攻略者往往不是被牙挑翻，是被撞下回廊边缘。"
        ),
    ),
    # 疾风狼：敏捷游斗，抗霜
    "gale_wolf": EnemyTemplate(
        id="gale_wolf", name="疾风狼",
        archetype="scout", hp=6, max_hp=6, ac=13, speed=13,
        damage_expr="1d6", damage_type="pierce",
        behavior_profile="cautious", skills=[],
        damage_types_resist={"frost": 0.5, "lightning": 1.5},  # 抗霜、惧雷
        loot=["wolf_fang"],
        flavor=(
            "瘦长的灰影在雾中无声穿梭，从不单只现身。它们用腹语般的低嗥协调包围——"
            "等你听见第一声嗥叫时，后路已经被第三只封死了。"
        ),
    ),
    # 食人花：固定不动的远程，弱点炎
    "mistbloom": EnemyTemplate(
        id="mistbloom", name="雾语食人花",
        archetype="caster_low", hp=5, max_hp=5, ac=8, speed=4,
        damage_expr="1d4+2", damage_type="frost",
        behavior_profile="opportunist", skills=[],
        damage_types_resist={"fire": 2.0},  # 极惧火
        loot=["bloom_pollen"],
        flavor=(
            "藏在齐膝雾气中的球茎植物，花瓣边缘结着细密冰晶。根须深深扎进回廊土层——"
            "不能移动，但这不代表它无害。它的寒雾花粉会让你的剑变慢，然后是你的腿。"
        ),
    ),
    # 第一层首领：雾语草原的霸主（§14 战术：前排近战重锤 + 破防条）
    "warden_gorehoof": EnemyTemplate(
        id="warden_gorehoof", name="层守·裂蹄牛魔王",
        archetype="boss", hp=24, max_hp=24, ac=12, speed=9,
        damage_expr="2d6", damage_type="blunt",
        behavior_profile="aggressive", skills=[],
        damage_types_resist={"fire": 1.5, "frost": 0.5},  # 弱炎、抗霜
        loot=["warden_horn", "floor_2_key"],
        rank=0, reach=1, max_poise=12,   # 前排冲撞，触及仅前排；破防条 12（待 R4 结算）
        flavor=(
            "肩高两米的牛头巨兽，断角上缠着历代挑战者留下的碎布。蹄子每踏一步，"
            "石殿地砖就多一道白茬裂痕。最可畏的是它的沉默——不像杂兵那样嘶吼，"
            "只是缓慢地、笃定地朝你走来。弱点在炎属剑技。"
        ),
    ),
    # 首领的后排援护：角鸣巫祝——站在牛魔王身后吹响骨角，从远处降下寒雾
    "horn_shaman": EnemyTemplate(
        id="horn_shaman", name="角鸣巫祝",
        archetype="caster_low", hp=6, max_hp=6, ac=11, speed=8,
        damage_expr="1d4+1", damage_type="frost",
        behavior_profile="opportunist", skills=[],
        damage_types_resist={"fire": 2.0},  # 极惧火（炎属剑技/法术速杀）
        loot=["shaman_horn"],
        rank=1, reach=99,   # §14：后排远程——近战 build 够不到，得用远程或绕位
        flavor=(
            "披着牛皮、头戴弯角骨冠的瘦小身影，缩在牛魔王巨大的阴影里。"
            "它不近身——只是把一支磨得发亮的骨角举到唇边，每一次低沉的呜鸣，"
            "都让殿中的温度跌下一截，寒雾顺着地缝朝你的脚踝爬来。"
            "想让牛魔王少一只帮凶，先得够得着躲在后面的它。"
        ),
    ),
    # 迷宫暗影虫
    "shadow_lurker": EnemyTemplate(
        id="shadow_lurker", name="影匿虫",
        archetype="scout", hp=5, max_hp=5, ac=14, speed=14,
        damage_expr="1d4", damage_type="pierce",
        behavior_profile="opportunist", skills=[],
        damage_types_resist={"lightning": 1.5, "slash": 0.5},  # 惧雷、刃物半伤
        loot=["lurker_carapace"],
        flavor=(
            "巴掌大的甲虫伏在迷宫石壁阴影里，甲壳灰黑如青苔。独居时无害——"
            "但三只以上会共振鸣翅，发出的高频脉冲能让攻略者眩晕三秒。"
            "迷宫里的老手都有一条铁律：看见一只，先找另外两只。"
        ),
    ),
    # 裂蹄殿守卫
    "warden_bladeguard": EnemyTemplate(
        id="warden_bladeguard", name="裂蹄殿守卫",
        archetype="brute_mid", hp=10, max_hp=10, ac=12, speed=9,
        damage_expr="1d8", damage_type="slash",
        behavior_profile="aggressive", skills=[],
        damage_types_resist={"fire": 0.5},
        loot=["guard_crest"],
        rank=0, reach=2, max_poise=6,   # §14：长柄战斧——前排，触及可及中排；精英破防条

        flavor=(
            "身披锈铁胸甲的牛头战士，长柄战斧的斧刃上有暗褐色的旧渍——"
            "那是之前叩门者的血。它不巡逻，只是站在首领殿前的甬道正中，像一座活雕像。"
            "「打不倒它，就没资格见层守。」"
        ),
    ),
}


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


def register(world: GameWorld):
    world.set_world_canon(SPIRE_CANON)
    world.register_enemies(ENEMIES)
    world.register_skills(SKILLS)

    # §11：苍穹回廊 RuleBook（力敏体智）
    world.rulebook = RuleBook(
        attributes={"str": "力量", "dex": "敏捷", "con": "体质", "int": "智力"},
        roles={"accuracy": "dex", "hp_growth": "con", "stamina_pool": "int"},
        equip_slots={"weapon": "主手", "armor": "护甲", "accessory": "饰品", "boots": "鞋"},
        level_curve="quadratic",
        unarmed_damage="1d1",   # 冷开局：赤手空拳，一拳只有 1d1——逼玩家破局找武器
    )

    # ── 第一层「雾语草原」房间链 ──────────────────────────────────
    # camp(安全区) → plains(刷怪) → labyrinth(迷宫) → warden_gate(首领)
    world.add_room(Room(
        id="camp",
        name="回廊脚下·营地",
        base_description=(
            "回廊塔底层那座靠老攻略者们撑起来的边境小镇——与其说是镇，不如说是营寨。"
            "中央篝火终年不熄，磨剑的、打盹的、对着刻印石板念叨的，没人多看你一眼。"
            "你身上还带着昨天那顿淤青，兜里一个铜板都没有。这里的规矩很简单也很冷："
            "谁都不欠新人一根头发，想要东西，自己挣。补给摊的老马罗、墙边的武器架、"
            "教剑技的薇拉……每一样都标着看不见的价码。东边那间锈角酒馆倒是热闹——"
            "热闹得正要打起来。北边镇门外就是草原，杀人兔在那儿等着没武器的傻瓜。"
            "唯一的好消息：「镇子里安全」，至少没人会在火堆边捅你。"
        ),
        exits={"north": "plains", "east": "tavern"},
        objects=["weapon_rack", "rack_iron_sword", "rack_dagger",
                 "teleport_crystal", "skill_trainer", "campfire",
                 "camp_merchant", "lost_scout", "coin_pouch", "field_notes",
                 "oath_altar"],
        area="苍穹回廊·第一层",
        zone="雾语草原·营地",
        coords=(0, 0),
        tags=["safe_zone", "no_combat", "respawn_point", "floor_1"],
    ))

    # ── 破局路一：锈角酒馆 + 必触发的斗殴 ───────────────────────────
    world.add_room(Room(
        id="tavern",
        name="锈角酒馆",
        base_description=(
            "门一推开，劣酒、汗味和松烟糊脸而来。十几号人挤在长条桌之间，"
            "可此刻没人在喝——屋子正中，一队风尘仆仆的冒险者和两名披甲的镇卫吵得脸红脖子粗，"
            "为的是一桩赏金该归谁。话越说越短，手越握越紧，木凳已经被人攥在手里。"
            "再有一句不对付，这屋子就要炸。你一个新人卡在两拨人中间——可以缩到墙角看戏，"
            "也可以挑一边搭把手。无论帮谁，凭你这身板，多半是挨一拳的份；"
            "但回廊里的人认一个理：肯下场的，事后总有人记着这份情。"
        ),
        exits={"west": "camp"},
        objects=["tavern_brawl", "tavern_keeper"],
        area="苍穹回廊·第一层",
        zone="锈角酒馆",
        coords=(1, 0),
        tags=["safe_zone", "social", "floor_1"],
    ))

    world.add_room(Room(
        id="plains",
        name="雾语草原",
        base_description=(
            "出了镇门就是草原：草高及腰，雾低过膝，十步之外的景物开始在乳白里融化。"
            "风吹草动时你以为是眼花，但那些晃动里总有几处逆着风向——那是怪。"
            "近处一棵孤零零的枯树杵在草里，断枝横七竖八，一看就经得起几下踹。"
            "西边草色压暗，连成一道黑黢黢的树林轮廓；北面雾最浓处立着几根青石柱，是迷宫的入口。"
            "脚边的草丛里，一团雪白的东西抽动着鼻子，长耳朵转向了你。"
        ),
        exits={"south": "camp", "north": "labyrinth", "west": "forest_edge"},
        objects=["lone_tree", "field_chest", "mist_shrine", "tall_grass",
                 "erin_talisman", "mist_cave_entrance"],
        area="苍穹回廊·第一层",
        zone="雾语草原",
        coords=(0, 1),
        tags=["field", "spawn_ground", "floor_1", "misty"],
        enemies=["killer_rabbit", "frenzy_boar", "gale_wolf", "mistbloom"],
    ))

    # ── 林边 / 树林（破局路三：闯林进守林员小屋取手斧）──────────────
    world.add_room(Room(
        id="forest_edge",
        name="雾语树林",
        base_description=(
            "草原西侧的树林，松木黑而密，针叶在脚下铺了厚厚一层，踩上去几乎没声。"
            "雾在这里更重，能见度不足五步——你听得见自己绕过每一棵树时呼吸的回声。"
            "林子里没有路，方向感很快就会被树干和雾吃掉；老话说，进雾语林靠的不是地图，是运气。"
            "隐约地，深处有个方方正正的轮廓，像是一座被遗忘的小木屋。"
        ),
        exits={"east": "plains", "in": "forester_hut"},
        # 闯进深处的小屋需要一点运气——GM 让玩家掷一把（迷路/野兽/雾），
        # 过了再 gm_set_flag("forest_path_found", True, unlock_exit="in")。
        locked_exits={"in": "forest_path_found"},
        objects=["dense_pines"],
        area="苍穹回廊·第一层",
        zone="雾语树林",
        coords=(-1, 1),
        tags=["forest", "risky", "floor_1", "misty"],
        enemies=["gale_wolf"],
    ))
    world.add_room(Room(
        id="forester_hut",
        name="废弃守林员小屋",
        base_description=(
            "一间塌了半边屋顶的原木小屋，门虚掩着，铰链锈成了橙红色。"
            "屋里积着厚灰，桌上一盏熄了很久的油灯，墙角一张吊床烂成了网。"
            "但工具墙还在——守林员走得匆忙，留下了几样吃饭的家伙。"
            "其中一把短柄手斧斜插在劈柴墩上，斧刃蒙尘却没怎么卷口。"
        ),
        exits={"out": "forest_edge"},
        objects=["chopping_block", "forester_hatchet", "dusty_shelf"],
        area="苍穹回廊·第一层",
        zone="守林员小屋",
        coords=(-2, 1),
        tags=["hidden", "shelter", "floor_1"],
    ))

    world.add_room(Room(
        id="labyrinth",
        name="雾语迷宫",
        base_description=(
            "草原尽头的石造迷宫，墙壁由整块青石切出，高处遮住了天光，"
            "让所有通道永远笼在青灰色的暗调里。墙上刻着古老的剑技图解和炎之纹章——"
            "既是谜题也是提示。地面有些石砖颜色微妙地深了一层，踩错的代价不是闹着玩的。"
            "深处据说封着一卷纵斩剑技书，尽头那扇符文门沉默地等着能读懂它的人。"
            "走通迷宫，才能叩首领之门。"
        ),
        exits={"south": "plains", "north": "warden_gate"},
        # 首领门需迷宫通关
        locked_exits={"north": "labyrinth_cleared"},
        objects=["rune_door", "trap_floor", "treasure_chest", "wall_glyph"],
        area="苍穹回廊·第一层",
        zone="雾语迷宫",
        coords=(0, 2),
        tags=["dungeon", "trap", "floor_1", "labyrinth"],
        enemies=["gale_wolf", "shadow_lurker"],
    ))

    world.add_room(Room(
        id="warden_gate",
        name="首领之间·裂蹄殿",
        base_description=(
            "圆形石殿，直径三十步。穹顶高得消失在暗处，地面满是大大小小的蹄印和裂痕——"
            "有些旧的已被青苔填平，新的还泛着石粉的白茬。殿北端立着一扇巨大的石门，"
            "门框浮雕刻着向上的螺旋阶梯——那是通往第二层的回廊门。"
            "殿正中，层守在等。这里的空气比别处重，你听不见风声、听不见远处草原上的怪叫，"
            "只能听见自己的心跳和殿深处某种巨大、缓慢的呼吸。"
        ),
        exits={"south": "labyrinth", "north": "floor_2_gate"},
        # 击败首领后解锁的回廊门（上行）
        locked_exits={"north": "warden_defeated"},
        objects=["corridor_gate", "warden_arena"],
        area="苍穹回廊·第一层",
        zone="首领之间",
        coords=(0, 3),
        tags=["boss_room", "floor_1", "climax"],
        enemies=["warden_bladeguard", "warden_gorehoof"],
    ))

    # 雾隐洞窟（草原隐藏分支）
    world.add_room(Room(
        id="mist_cave",
        name="雾隐洞窟",
        base_description=(
            "草原西侧石壁上一个被藤蔓半掩的裂隙，窄到得侧身挤进去。里面意外地宽敞——"
            "洞壁泛着微弱的青蓝色磷光，是从岩缝里渗出的某种发光菌。"
            "空气阴凉湿黏，能听见深处有水滴规律地敲着石笋，像某种缓慢的心跳。"
            "角落里堆着不知谁留下的补给箱，和一副散落的白骨——"
            "他大概是进来躲怪，却撞上了洞里更糟的东西。"
        ),
        exits={"out": "plains"},
        objects=["cave_chest", "cave_crystal"],
        area="苍穹回廊·第一层",
        zone="雾隐洞窟",
        coords=(-1, 1),
        tags=["hidden", "treasure", "floor_1"],
    ))

    # 第二层入口（击败层守后解锁）
    world.add_room(Room(
        id="floor_2_gate",
        name="回廊门·第二层入口",
        base_description=(
            "石殿北端的巨门在你走近时无声滑开——没有机关，没有铰链，"
            "仿佛它一直在等你。门后是一道螺旋上升的石梯，每一级台阶上都浮着微弱的蓝光，"
            "那是历代登顶者留下的烙印残影。往上望不见尽头，往下……已没有回头的路。"
            "第一层的雾气和野草味被一股干燥、带着金属气息的冷风取代。"
            "第二层在等。传送水晶在这里立了一根新的——回廊承认了你的抵达。"
        ),
        exits={"up": ""},  # 第二层未做，预留
        objects=["floor_2_crystal", "floor_2_marker"],
        area="苍穹回廊·第二层入口",
        zone="回廊门",
        coords=(0, 4),
        tags=["safe_zone", "transition", "floor_2"],
    ))

    # ── 营地物体 ──────────────────────────────────────────────────
    world.add_object(GameObject(
        id="coin_pouch",
        name="瘪空的币袋",
        description=(
            "你随身那只皮币袋，眼下瘪得能透光——一个铜板都没有。"
            "回廊的规矩：钱是记在你身家账上的（走身家，不在这只袋子里），袋子只是包装。"
            "等你哪天有了进项，数字会涨在账上，不在这块破皮子里。烧它砸它，账上一文不动。"
        ),
        kind="container",
        named_tags=["currency"],
        traits=["money"],
        takable=False,
        # 金币是抽象资产（gold 走 vitals），不绑实体。袋子是叙事道具，标 indestructible，
        # 免得一发炎刃斩把存款"烧没"——破坏它在机制上无意义（抽象资产保护）。
        indestructible=True,
    ))
    # 锈角酒馆：斗殴事件 + 老板（破局路一）
    world.add_object(GameObject(
        id="tavern_brawl",
        name="一触即发的争执",
        description=(
            "冒险者那队的领头是个独眼女人，叉着腰；镇卫这边一个满脸横肉的老兵按着剑柄。"
            "两边为一笔杀人兔赏金的归属吵到了顶点，中间隔着的只剩一张快被掀翻的长桌。"
            "你要是想插一脚，就得现在选边——之后可没人等你犹豫。"
        ),
        kind="event",
        named_tags=["brawl", "faction_choice"],
        traits=["one_shot"],
        takable=False,
        affordances={
            "back_adventurers": Affordance(
                verb="back_adventurers",
                desc="站到冒险者一边，帮独眼女人撑场",
                effect={
                    "flags": {"brawl_done": True, "sided_adventurers": True,
                              "tavern_ally": True},
                    "gain_gold": 5,
                    "clues": [
                        "你往独眼女人身侧一站，话没说完，那老兵一个箭步就是一拳——"
                        "正中你下巴，眼前一黑，等回过神已经趴在桌底数星星。架很快被劝开了。"
                        "独眼女人把你从桌底拎起来，咧嘴一笑，往你手里塞了几枚回廊币："
                        "「没用，但有种。这点算定金——以后锈角酒馆有你一杯。」"
                        "（+5 回廊币；冒险者那伙记下了你这份情）"
                    ],
                },
                consume_self=True,
            ),
            "back_guards": Affordance(
                verb="back_guards",
                desc="站到镇卫一边，帮老兵压场",
                effect={
                    "flags": {"brawl_done": True, "sided_guards": True,
                              "tavern_ally": True},
                    "gain_gold": 5,
                    "clues": [
                        "你挪到老兵身后虚张声势，结果第一个挨揍的还是你——"
                        "独眼女人随手一推，你就撞翻了三条板凳。等尘埃落定，老兵拍拍你肩膀，"
                        "力道大得差点把你拍散架：「新来的？有胆。」他丢给你几枚币，"
                        "「镇卫记人情。下回城门口报我名字，老高。」"
                        "（+5 回廊币；镇卫那边记下了你这份情）"
                    ],
                },
                consume_self=True,
            ),
        },
    ))
    world.add_object(GameObject(
        id="tavern_keeper",
        name="酒馆老板·跛脚塞恩",
        description=(
            "拖着一条瘸腿在吧台后擦杯子的老男人，据说年轻时也是攻略者，被某层的怪咬断了跟腱。"
            "他什么都见过，什么都不多嘴——除非你让他觉得你值得搭句话。"
        ),
        kind="npc",
        named_tags=["bartender"],
        traits=["veteran", "informant"],
        takable=False,
        affordances={
            "ask_advice": Affordance(
                verb="ask_advice",
                desc="问跛脚塞恩，一个穷光蛋新人能从哪儿弄把武器",
                effect={
                    "flags": {"got_tavern_tip": True},
                    "clues": [
                        "塞恩斜眼打量你空荡荡的腰带，嗤了一声：「拳头打杀人兔？回去等死吧。」"
                        "他压低声音：「实在没辙——城外那棵枯树，掰根硬枝也比空手强。"
                        "再不济，往西边树林里赌一把，老守林员的破屋里听说还留着把手斧。"
                        "当然，你要是嫌慢，今晚这场架，挑边站，挨顿打也能换几个子儿。」"
                    ],
                },
            ),
        },
    ))
    world.add_object(GameObject(
        id="field_notes",
        name="前人攻略残页",
        description=(
            "几张被雨水泡皱又晒干的羊皮纸，边角焦黑——像是从某个篝火堆里抢出来的。"
            "上面是潦草的炭笔字：第一层的怪、迷宫的陷阱、层守的出招规律，"
            "记到一半戛然而止。最后一行字被一道暗褐色的划痕盖住了。"
        ),
        kind="document",
        named_tags=["lore", "guide"],
        traits=["readable", "fragile"],
        takable=True,
        hidden_clue="残页要点：层守『裂蹄牛魔王』弱点在炎，蓄力重踏前会先低头——那是破绽窗口",
        hidden_flag="read_field_notes",
        affordances={
            "read": Affordance(
                verb="read",
                desc="借营火的光读这几页残卷",
                effect={
                    "flags": {"field_notes_read": True},
                    "clues": [
                        "残页要点：层守蓄力重踏前会先低头一瞬——那一刻它看不见脚下，"
                        "是炎属剑技切入的最佳窗口。写到这里，字迹被一道暗褐划痕截断了。"
                    ],
                },
            ),
            "tear": Affordance(
                verb="tear",
                desc="把残页撕掉（不可逆）",
                effect={"flags": {"field_notes_torn": True}},
                consume_self=True,
            ),
            "burn": Affordance(
                verb="burn",
                desc="就着营火烧掉残页",
                effect={"flags": {"field_notes_burned": True}},
                consume_self=True,
            ),
        },
    ))
    world.add_object(GameObject(
        id="oath_altar",
        name="试炼誓约碑",
        description=(
            "营地角落一方半人高的黑石碑，碑面被无数把剑尖刻得伤痕累累——"
            "每一道刻痕都是一位攻略者立下的「誓约」：自缚枷锁、加重试炼，"
            "以向回廊换取更丰厚的回响。碑下小字写着回廊的古老交易：「难者多得」。\n"
            "立约只对你的【下一场战斗】生效，胜则按难度放大经验与回响币（败则无咎，约自散）。\n"
            "可选誓约词条（可多选叠加）：\n"
            "· 狂暴——敌全员伤害 +2（难度 2）\n"
            "· 磐石——敌全员血量 ×1.5（难度 2）\n"
            "· 铁壁——敌全员 AC +3，更难命中（难度 2）\n"
            "· 疾风——敌全员速度 +6，更易抢先手（难度 1）"
        ),
        kind="scenery",
        named_tags=["contract", "altar"],
        traits=["challenge", "self_imposed"],
        takable=False,
        # 立约是带参数的选择，走 take_contract 工具（GM 据玩家所选调用），
        # 碑本身只作发现锚点 + 词条说明，不挂固定 affordance。
    ))
    world.add_object(GameObject(
        id="weapon_rack",
        name="登记武器架",
        description=(
            "靠墙立着一排上了锁链的制式铁剑和匕首，每把柄上拴着烙印登记牌。"
            "旁边木板钉着告示：「攻略组共用军备，凭登记烙印领取。未登记者擅动，按盗械论处。」"
            "你这个连铜板都没有、没人作保的新人，还轮不到在这上面登记——"
            "想拿这儿的剑，先得在镇上挣出个名头来。"
        ),
        kind="container",
        traits=["equipment", "locked"],
        takable=False,
        affordances={
            # 需"已登记"才能领——穷新人没这个 flag，等破局攒出立足之地(GM 裁定)再说。
            "take_sword": Affordance(
                verb="take_sword",
                desc="（需登记烙印）领一柄制式铁剑",
                requires_flag="attacker_registered",
                effect={"reveals_objects": ["rack_iron_sword"],
                        "clues": ["登记牌一扫，锁链应声而开。你取下一柄铁剑，重心刚好——总算像个攻略者了。"]},
            ),
            "take_dagger": Affordance(
                verb="take_dagger",
                desc="（需登记烙印）领一柄猎杀匕首",
                requires_flag="attacker_registered",
                effect={"reveals_objects": ["rack_dagger"],
                        "clues": ["匕首握在掌心，刃薄到能藏进腰带。"]},
            ),
        },
    ))

    # ── 武器架上的隐藏武器（通过 affordance reveal 后可变 takable）──
    world.add_object(GameObject(
        id="rack_iron_sword",
        name="制式铁剑",
        description="营地板架上的制式铁剑，重心刚好，挥起来顺手。刃口有几处小卷刃——是把见过风雨的旧剑。",
        kind="tool", hidden=True, takable=True,
        traits=["weapon", "slash"],
        equip_slot="weapon", damage_expr="1d6", damage_type="slash",
        scaling={"str": 1.0}, reach=1,
    ))
    world.add_object(GameObject(
        id="rack_dagger",
        name="猎杀匕首",
        description="柄缠细麻绳的短刃，刃薄到能藏在腰带里。营地的老手管它叫'狼牙签'——不是用来耍帅，是用来在疾风狼咬住你之前捅它喉咙。",
        kind="tool", hidden=True, takable=True,
        traits=["weapon", "pierce", "dex"],
        equip_slot="weapon", damage_expr="1d4", damage_type="pierce",
        scaling={"dex": 1.0}, reach=1,  # 匕首：纯敏，刺杀吃敏捷；近战触及
    ))

    # ── 营地商人 ──
    world.add_object(GameObject(
        id="camp_merchant",
        name="补给商·老马罗",
        description=(
            "一个五十出头的光头汉子，围着一条被各种液体染得看不出原色的围裙。"
            "他经营营地的补给摊已经不知道多少年了——「比你们所有人的回廊烙印加起来还老。」"
            "摊上摆着药水、磨刀石和几件从倒下的攻略者身上回收的装备。价格公道，童叟无欺——"
            "毕竟死人的装备是无限供应的。"
        ),
        kind="npc",
        named_tags=["merchant"],
        traits=["shopkeeper", "veteran"],
        takable=False,
        affordances={
            "buy_heal": Affordance(
                verb="buy_heal",
                desc="购买回复水晶（回 8 HP）— 50 金币",
                effect={"cost_gold": 50,
                        "clues": ["老马罗从摊下摸出一颗淡蓝色水晶，「用的时候捏碎——别咬，上个月有个笨蛋崩了门牙。」"]},
            ),
            "buy_sp": Affordance(
                verb="buy_sp",
                desc="购买战技灵药（回 5 SP）— 50 金币",
                effect={"cost_gold": 50,
                        "clues": ["他递过一支细颈瓶，里面液体是萤火虫的青色。「喝了能再放一剑技。别贪，一天最多两瓶。」"]},
            ),
            "buy_steel_blade": Affordance(
                verb="buy_steel_blade",
                desc="购买淬钢直剑（1d8 slash，力敏双修）— 200 金币",
                effect={"cost_gold": 200,
                        "clues": ["老马罗从摊下抽出一柄裹在油布里的直剑。刃面冷冽，比铁剑沉了一分，也狠了一分。"],
                        "reveals_objects": ["shop_steel_blade"]},
            ),
            "buy_leather_vest": Affordance(
                verb="buy_leather_vest",
                desc="购买皮背心（AC+2）— 100 金币",
                effect={"cost_gold": 100,
                        "clues": ["他拎起一件鞣制过的雾牛皮背心，拍了拍前胸，「比看起来结实。挡野猪那一下够用了。」"],
                        "reveals_objects": ["shop_leather_vest"]},
            ),
        },
    ))
    # 商店揭示的隐藏物品
    world.add_object(GameObject(
        id="shop_steel_blade",
        name="淬钢直剑",
        description="刃面冷冽的直剑，比制式铁剑沉一分。剑身上有锻打留下的水波纹——不是装饰，是叠层淬火的痕迹。",
        kind="tool", hidden=True, takable=True,
        traits=["weapon", "slash", "quality"],
        # §11 结构化装备字段（比起始铁剑 1d6 强一档）
        equip_slot="weapon",
        damage_expr="1d8",
        damage_type="slash",
        scaling={"str": 1.0, "dex": 1.0},  # 直剑：力敏双修
        reach=1,
    ))
    world.add_object(GameObject(
        id="shop_leather_vest",
        name="鞣制皮背心",
        description="雾牛皮缝成的护胸，鞣得柔软但韧劲十足。一股干草和硝烟的味道。肩带可以调——上一任主人大概比你壮一圈。",
        kind="item", hidden=True, takable=True,
        traits=["armor"],
        equip_slot="armor",
        defense=3,
    ))

    # ── 迷途的攻略者 ──
    world.add_object(GameObject(
        id="lost_scout",
        name="迷途的艾琳",
        description=(
            "一个看起来不到二十岁的少女攻略者，右眼下方有一道还很新的烙印——她进塔不到一周。"
            "此刻坐在营火旁，膝盖抵着下巴，眼圈发红。她的侦查小队三天前进了迷宫，"
            "只有她一个人逃了出来。她的护符——母亲给的进塔饯别礼——掉在草原了。"
        ),
        kind="npc",
        named_tags=["scout", "quest_giver"],
        traits=["young", "distressed"],
        takable=False,
        affordances={
            "ask_about_talisman": Affordance(
                verb="ask_about_talisman",
                desc="问她为什么难过",
                effect={
                    "flags": {"met_lost_scout": True},
                    "clues": [
                        "艾琳抬起头，用袖子擦了一下眼角。「我的护符——一颗雾语青石坠子——"
                        "掉在草原了。那是妈妈给我的……你能帮我找回来吗？它大概在草原北边的草丛里。」"
                        "她顿了顿，「找到了的话，我把我的匕首给你。它是敏系，比铁剑更适合对付疾风狼。」"
                    ],
                },
            ),
            "return_talisman": Affordance(
                verb="return_talisman",
                desc="把雾语护符还给艾琳",
                requires_item="erin_talisman",
                effect={
                    "flags": {"erin_talisman_returned": True},
                    "clues": [
                        "艾琳双手接过护符，贴在额头，半天没说话。"
                        "然后她解下腰间的匕首，递给你。「它叫'狼牙签'。拿着吧——你比我更需要它。」"
                    ],
                    "reveals_objects": ["erin_dagger_reward"],
                },
            ),
        },
    ))
    world.add_object(GameObject(
        id="erin_dagger_reward",
        name="艾琳的匕首",
        description="一柄纤细的猎刀，柄上缠着褪色的蓝丝线。刃短但极利——艾琳说它捅穿过三只疾风狼的喉咙。",
        kind="tool", hidden=True, takable=True,
        traits=["weapon", "pierce", "dex", "quest_reward"],
        equip_slot="weapon", damage_expr="1d4+1", damage_type="pierce",
        scaling={"dex": 1.0}, reach=1,  # 精良匕首：纯敏；近战触及
    ))

    world.add_object(GameObject(
        id="teleport_crystal",
        name="传送水晶",
        description=(
            "一根半人高的蓝色水晶柱，表面浮着像脉搏一样明灭的光纹。"
            "传说每根回廊水晶都是过去登顶失败者的烙印所化——"
            "他们没能登顶，但留下了让后来者少死一次的路标。"
        ),
        kind="scenery",
        traits=["save_point", "respawn"],
        takable=False,
        affordances={
            "attune": Affordance(
                verb="attune",
                desc="将手按上水晶，让回廊烙印与之共鸣",
                effect={
                    "flags": {"camp_attuned": True},
                    "clues": [
                        "水晶的冷意顺着手掌爬进烙印，那一瞬间你听见无数声音——"
                        "破碎的、含混的、从很远的地方漂来的低语。然后一切安静下来。"
                        "烙印泛起蓝光，与水晶同步明灭。营地成了你的复生点。"
                    ],
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="skill_trainer",
        name="剑技教官·薇拉",
        description=(
            "约莫二十出头的女剑士，栗色短发在脑后扎成一个不整齐的结。"
            "左手虎口有一道从拇指根拉到腕侧的旧疤——那是纵斩握姿的反面。"
            "她打量你的眼神介于教官和战友之间：不会手软，但也不会让你去送死。"
        ),
        kind="npc",
        named_tags=["trainer"],
        traits=["mentor", "swordswoman"],
        takable=False,
        affordances={
            # 学剑技：垂直方斩（被动精通和反应回避是出身自带，见 initial_state）
            "learn_vertical_arc": Affordance(
                verb="learn_vertical_arc",
                desc="请薇拉传授纵斩的发力轨迹",
                effect={
                    "learn_skills": ["vertical_arc"],   # 真正授予技能，进 state.skills
                    "flags": {"learned_vertical_arc": True},
                    "clues": [
                        "薇拉二话不说拔剑，在空中拉出一道银弧——"
                        "「纵斩不需要花样。脚蹬地，腰转，手腕锁死。"
                        "力从地面传到剑尖，一分也不少。」她收剑的动作比拔剑快了一倍。"
                        "你的肌肉记住了那道轨迹。剑技『垂直方斩』已掌握。"
                    ],
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="campfire",
        name="篝火",
        description=(
            "一堆用回廊浮石垒成的篝火，焰色偏蓝，烧的是草原上采来的雾草——"
            "闻起来像烧焦的薄荷。攻略组的人围坐一圈，有的在磨剑，有的只是对着火发呆。"
            "火光把每个人的影子都拉到帐篷上，长长短短，像另一个无声的聚会。"
        ),
        kind="scenery",
        traits=["rest", "light_source"],
        takable=False,
        affordances={
            "rest": Affordance(
                verb="rest",
                desc="在篝火旁坐下，歇息整备",
                effect={
                    "flags": {"rested": True},
                    "clues": [
                        "雾草在火里噼啪轻响，蓝焰舔着石沿，把暖意一寸一寸推进骨头。"
                        "呼吸慢下来，淤伤和紧绷都在消退——在这样的火边歇足一刻，"
                        "就是新的自己。HP 和 SP 完全回复了。"
                    ],
                },
            ),
        },
    ))

    # ── 破局路二：枯树 → 木棍（1d4）──────────────────────────────────
    world.add_object(GameObject(
        id="lone_tree",
        name="孤零的枯树",
        description=(
            "草原里一棵早就死透的枯树，灰白的树干裂着缝，断枝横七竖八地支棱着。"
            "有几根粗细正合手的枝桠，看着就能掰下来当根棍子使——"
            "对一个连把小刀都没有的人来说，这已经是天上掉下来的武器了。"
        ),
        kind="scenery",
        traits=["improvised_weapon_source"],
        takable=False,
        hp=4, max_hp=4, ac=3,    # 枯木易断：砸/踹几下也能弄断（deal_damage 亦可）
        on_destroyed=[{
            "reveals_objects": ["wooden_club"],
            "flags": {"got_first_weapon": True},
            "clues": ["枯木"
                      "应声而断，一根半臂长、握处正好的硬枝滚到脚边——你的第一件武器。"],
        }],
        affordances={
            "break_branch": Affordance(
                verb="break_branch",
                desc="掰下一根趁手的硬枝当棍子",
                effect={
                    "reveals_objects": ["wooden_club"],
                    "flags": {"got_first_weapon": True},
                    "clues": ["你架住一根粗枝，全身的重量压上去——咔啦一声脆响，"
                              "半臂长的硬木枝到了手里。掂了掂，能抡，能戳。聊胜于拳头。"],
                },
            ),
        },
    ))
    world.add_object(GameObject(
        id="wooden_club",
        name="枯木棍",
        description="从枯树上掰下的一截硬木枝，握处被你攥得发亮。没开刃，但抡圆了砸下去，比赤手强得多。1d4 钝击。",
        kind="tool", hidden=True, takable=True,
        traits=["weapon", "blunt", "improvised"],
        equip_slot="weapon", damage_expr="1d4", damage_type="blunt",
        scaling={"str": 1.0}, reach=1,
    ))

    # ── 草原物体 ──────────────────────────────────────────────────
    world.add_object(GameObject(
        id="field_chest",
        name="草丛宝箱",
        description=(
            "半埋在草丛里的小宝箱，铁皮包角已经生了薄锈，锁扣倒是亮晶晶的——"
            "显然最近有人开过又关上。可能是攻略组故意留在野外的补给箱，"
            "也可能是某个倒霉蛋来不及带回营地的遗物。"
        ),
        kind="container",
        traits=["loot"],
        takable=False,
        hp=4, max_hp=4, ac=5,
        affordances={
            "open": Affordance(
                verb="open",
                desc="掀开草丛宝箱的盖子",
                effect={
                    "flags": {"field_chest_opened": True},
                    "clues": [
                        "箱盖吱呀掀起，里面躺着几枚刻着回廊纹的金币和一瓶用粗陶罐封着的"
                        "回复药——标签上的字歪歪扭扭：『喝了继续冲』。"
                    ],
                },
                consume_self=True,
            ),
        },
    ))

    world.add_object(GameObject(
        id="mist_shrine",
        name="雾语祠",
        description=(
            "草原深处的小型石祠，比人略矮，屋顶长满青苔，门楣上刻着褪色的炎之刻印。"
            "神台上没有神像，只有一盏长明灯——据守营地的老兵说，"
            "向它祈祷能得一层炎护，打食人花的时候你会谢谢它的。"
        ),
        kind="scenery",
        named_tags=["shrine"],
        traits=["blessing"],
        takable=False,
    ))

    world.add_object(GameObject(
        id="tall_grass",
        name="高草丛",
        description=(
            "草叶高及腰际，秆子硬得像晒干的高粱。人在里面蹲下就只露出头顶，"
            "而风一吹整片草丛都在摇——绝佳的伏击掩体。不过草原上的怪也知道这件事。"
        ),
        kind="scenery",
        traits=["cover", "ambush"],
        takable=False,
        hp=2, max_hp=2, ac=3,
        damage_types_resist={"fire": 3.0},  # 一点就着
        on_destroyed=[{
            "reveals_objects": ["scout_token"],   # 烧穿草丛，露出底下藏的东西
            "flags": {"grass_burned": True},
            "clues": [
                        "干燥的草秆遇火即燃，橙红的火舌沿风向席卷整片草丛，黑烟冲天。"
                        "火光退去后，焦黑的草根间露出一枚被人匆忙埋下的金属牌——"
                        "某个没能走回营地的攻略者，最后留在了这里。"
                    ],
        }],
    ))
    world.add_object(GameObject(
        id="scout_token",
        name="烧焦的身份牌",
        description="一枚边缘被火燎黑的金属攻略者牌，正面刻着回廊攻略组的螺旋徽记和一个已看不清的名字。背面用小刀划了一道——大概是某次侥幸生还后给自己记的功。它的主人没能再划第二道。",
        kind="trace", hidden=True, takable=True,
        traits=["keepsake", "evidence"],
        named_tags=["fallen_scout"],
    ))

    # ── 平原支线物品 ──
    world.add_object(GameObject(
        id="erin_talisman",
        name="雾语青石坠子",
        description="一颗拇指大的青色石子，穿了皮绳。石面上刻着一道简易的螺旋——回廊烙印的民间摹本。握在手心微微发暖，像是被谁攥了很久。这是艾琳的护符。",
        kind="item", hidden=True, takable=True,
        traits=["quest_item"],
        named_tags=["quest_item", "evidence"],
    ))
    world.add_object(GameObject(
        id="mist_cave_entrance",
        name="石壁裂隙",
        description="草原西侧石壁上被藤蔓半掩的窄缝。若非走近细看，很容易当成阴影忽略。风从缝里灌出来时带着一股发光的菌丝味——这股味道在雾语草原别处没有。",
        kind="scenery",
        traits=["hidden", "entrance"],
        takable=False,
        affordances={
            "enter": Affordance(
                verb="enter",
                desc="侧身挤进裂隙",
                effect={"clues": ["你侧身挤过藤蔓，洞口初窄如咽喉，三步后豁然开朗——是一座发着青蓝磷光的天然洞窟。"],
                        "flags": {"mist_cave_found": True}},
            ),
        },
    ))

    # ── 破局路三：树林 → 守林员小屋 → 手斧（1d6）──────────────────────
    world.add_object(GameObject(
        id="dense_pines",
        name="密匝匝的松林",
        description=(
            "雾在松干之间凝成看得见的灰白，越往里越浓。没有路，每一棵树看着都一样，"
            "走上十几步回头就找不见来路了。深处那个方正轮廓还在——但要摸过去，"
            "得在迷雾、错综的树根和林子里游荡的东西之间赌一把运气。"
        ),
        kind="scenery",
        traits=["navigation_challenge", "risky"],
        takable=False,
        # 玩家说"我闯进去/往深处摸" → GM 让掷一把（感知/运气/敏捷，DC≈12）。
        # 过 → gm_set_flag("forest_path_found", True, unlock_exit="in")，"in" 通往小屋。
        # 败 → 迷路绕回、或惊动疾风狼（按情境裁定），可再试。
    ))
    world.add_object(GameObject(
        id="forester_hatchet",
        name="守林员手斧",
        description=(
            "斜插在劈柴墩上的一把短柄手斧，斧头蒙着灰却没怎么卷口——守林员保养得不错。"
            "握柄被磨出了手型，配重压手，劈下去是实打实的杀伤。1d6 斩击，对付杀人兔绰绰有余。"
        ),
        kind="tool", hidden=False, takable=True,
        traits=["weapon", "slash", "tool"],
        equip_slot="weapon", damage_expr="1d6", damage_type="slash",
        scaling={"str": 1.0}, reach=1,
    ))
    world.add_object(GameObject(
        id="chopping_block",
        name="劈柴墩",
        description="一截齐腰高的硬木桩，顶面被斧子啃出无数月牙形的豁口。守林员手斧就插在它上面。",
        kind="scenery",
        traits=["furniture"],
        takable=False,
    ))
    world.add_object(GameObject(
        id="dusty_shelf",
        name="积灰的工具墙",
        description=(
            "钉在原木墙上的工具架，挂钩多半空着——值钱的早被人顺走了。"
            "只剩一卷霉烂的麻绳、半罐凝固的松脂、一把缺了齿的锯。翻翻或许能凑出点有用的。"
        ),
        kind="container",
        traits=["scavenge"],
        takable=False,
        affordances={
            "search": Affordance(
                verb="search",
                desc="在工具墙和墙角翻找还能用的东西",
                effect={
                    "flags": {"searched_hut": True},
                    "clues": ["你扒拉开霉绳和锈锯，在墙缝里摸出三枚沾灰的回廊币——"
                              "守林员藏的应急钱，如今归你了。"],
                    "gain_gold": 3,
                },
            ),
        },
    ))

    # ── 迷宫物体 ──────────────────────────────────────────────────
    world.add_object(GameObject(
        id="rune_door",
        name="符文石门",
        description=(
            "迷宫最深处的门——不是木头，是一整面青石，表面密密麻麻刻着古老的炎之刻印，"
            "每个刻印都在微微发热。没有把手、没有锁孔，只有正中间一个空白符位，"
            "等着对应的印被激活。墙上的图解暗示了开法：纵斩蓄炎，以剑为钥。"
        ),
        kind="scenery",
        traits=["puzzle", "obstacle"],
        takable=False,
        affordances={
            # 解谜通关迷宫 → 解锁首领门
            "solve": Affordance(
                verb="solve",
                desc="按墙上刻印的提示，用炎属剑技激活符文门的密匙",
                requires_flag="read_wall_glyph",
                effect={
                    "flags": {"labyrinth_cleared": True},
                    "unlock_exit": "north",
                    "clues": [
                        "你将剑尖抵入空白符位，手腕一转——剑身上残留的炎属性"
                        "顺着刻印纹路蔓延开去，一条，两条，直到整面石门上每一条刻痕"
                        "都亮起暗红的光。石门无声滑开，首领殿的冷风迎面扑来，"
                        "带着湿土、旧血和某种巨大动物的气味。首领之门就在前方。"
                    ],
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="wall_glyph",
        name="墙上刻印",
        description=(
            "迷宫墙壁上连成一片的浮雕刻印，剥蚀严重但仍能辨识内容：三道火焰的图案，"
            "每个旁边配着一把剑的纵斩轨迹。火焰越画越大，剑越画越深，"
            "最后一幅图里剑尖点在了某个圆心——像一把钥匙插进锁眼。"
        ),
        kind="trace",
        traits=["clue", "puzzle_hint"],
        takable=False,
        hidden_clue="刻印含义：三道炎纹配纵斩轨迹——炎之刻印是激活符文门的键，剑尖即钥位，纵斩破封",
        hidden_flag="read_wall_glyph",
    ))

    world.add_object(GameObject(
        id="trap_floor",
        name="陷阱地砖",
        description=(
            "颜色比周围石砖略深，像被水浸过。边缘缝里的灰泥比别处新——有人补过。"
            "踩上去的瞬间地面会弹出两排尖刺，角度刚好覆盖整个通道宽度，无处可躲。"
            "要么拆了它，要么赌你的速度。"
        ),
        kind="scenery",
        traits=["trap", "hazard"],
        takable=False,
        hp=6, max_hp=6, ac=6,
        on_destroyed=[{
            "flags": {"trap_disarmed": True},
            "clues": [
                        "铁尖被你砸弯，石砖底下的机簧发出一声闷响后彻底哑了——"
                        "通道安全，不用再贴着墙走了。"
                    ],
        }],
    ))

    world.add_object(GameObject(
        id="treasure_chest",
        name="迷宫宝箱",
        description=(
            "一只有半人高的大宝箱，铁箍铜锁，箱盖上浮雕着纵斩的剑技图解——"
            "和薇拉教的是同一式，但图里剑的轨迹更老练，最后一笔劈开了某种兽形的轮廓。"
            "这箱子里封的不是财宝，是技艺。"
        ),
        kind="container",
        named_tags=["treasure"],
        traits=["loot", "skill_book"],
        takable=False,
        hp=6, max_hp=6, ac=6,
        affordances={
            "open": Affordance(
                verb="open",
                desc="开启迷宫深处的技能宝箱",
                effect={
                    "learn_skills": ["vertical_arc"],   # 真正授予技能，进 state.skills
                    "flags": {"got_skill_book": True, "learned_vertical_arc": True},
                    "clues": [
                        "锁扣弹开的瞬间，一卷泛着淡光的手卷浮了起来——它在眼前展开，"
                        "剑技口诀以刻印形式直接烙进你的意识。闭眼再睁开时，"
                        "『垂直方斩』的每一处发力细节都已刻在肌肉里。"
                        "卷轴化尘散去，功成身退。剑技『垂直方斩』已习得。"
                    ],
                },
                consume_self=True,
            ),
        },
    ))

    # ── 首领之间物体 ──────────────────────────────────────────────
    world.add_object(GameObject(
        id="warden_arena",
        name="首领战场",
        description=(
            "石殿中央一片被踏得比别处更光亮的区域，地面裂纹呈放射状——"
            "这里的每一条缝都是层守的蹄子踩出来的。空气在这里变得沉重，"
            "你听不见风声、听不见远处的雾，只能听见自己的心跳和殿深处"
            "某种巨大、缓慢的呼吸。踏入即战。"
        ),
        kind="scenery",
        traits=["arena", "trigger"],
        takable=False,
        affordances={
            # 踏入战场 → 首领战开打
            "challenge": Affordance(
                verb="challenge",
                desc="步入战场，正面挑战第一层层守",
                effect={
                    "flags": {"warden_fight_started": True},
                    "clues": [
                        "你的脚步踏入圆形战场的边缘，靴跟磕在石面上发出一声清脆的响。"
                        "殿深处的呼吸停了一拍。两根弯曲的巨角从暗中缓缓低下来，"
                        "一双赤红的眼睛在角根处亮起——裂蹄牛魔王踏前一步，挡在你与去路之间。"
                        "它身后的阴影里，一声低沉的骨角呜鸣响起，殿中温度骤降：角鸣巫祝"
                        "缩在牛魔王背后，不打算靠近，只管从远处往你身上浇寒雾。"
                        "想让它闭嘴，你的剑得先够得着它。首领战开始。"
                    ],
                    # §14 战术首领战：牛魔王前排近战(reach1)，巫祝后排远程(reach99)。
                    # 近战 build 够不到后排巫祝→得用远程(辉石杖)或走位绕；模板自带 rank/reach。
                    "start_combat": {
                        "canon": ["warden_gorehoof", "horn_shaman"],
                        "tactical": True, "rank_depth": 2, "player_rank": 0,
                    },
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="corridor_gate",
        name="回廊门",
        description=(
            "一扇比符文门更大的石门，门框上的浮雕不再是炎纹，"
            "而是一道螺旋上升的阶梯——通往第二层。「回廊只能向上」，"
            "击败层守后，这扇门会自动激活，刻痕逐一亮起，通向上一界域的路会打开。"
        ),
        kind="scenery",
        named_tags=["progression"],
        traits=["floor_exit"],
        takable=False,
        # 击败首领后由 GM 裁定（update_quest + gm_set_flag warden_defeated）
        # 解锁 north 出口，通往第二层（暂未实现，留作 floor_2 钩子）。
    ))

    # ── 雾隐洞窟物体 ──
    world.add_object(GameObject(
        id="cave_chest",
        name="旧补给箱",
        description="一口被潮气啃得边角发黑的木箱，锁扣早已锈烂。盖上用炭笔潦草地写着「给后来的倒霉蛋——别碰洞底那东西」。",
        kind="container",
        traits=["treasure"],
        takable=False,
        reveals_objects=["cave_glow_staff", "cave_heal_crystal"],
        affordances={
            "open": Affordance(
                verb="open",
                desc="撬开锈蚀的箱盖",
                effect={"reveals_objects": ["cave_glow_staff", "cave_heal_crystal"],
                        "clues": ["箱盖嘎吱掀开，潮气裹着霉味扑面。里面躺着一根石质短杖和一颗淡蓝色水晶——前人留给后来者的保险。"]},
            ),
        },
    ))
    world.add_object(GameObject(
        id="cave_glow_staff",
        name="辉石杖",
        description="一根由发光洞壁凿下的石杖，杖头嵌着一颗不灭的青色辉石。握在手里能感到轻微的魔力脉动——它不是武器，是法器。智为主、力为辅。",
        kind="tool", hidden=True, takable=True,
        traits=["weapon", "arcane", "quality", "ranged"],
        equip_slot="weapon", damage_expr="1d6", damage_type="arcane",
        scaling={"int": 1.0, "str": 0.5},  # 辉石杖：智为主、力为辅（混属性带权重）
        reach=99,   # §14：法器远程，能点后排——战术战斗里近战 build 的破局答案
    ))
    world.add_object(GameObject(
        id="cave_heal_crystal",
        name="回复水晶",
        description="一颗淡蓝色水晶，表面浮着脉搏般的光纹。捏碎后回廊之力会涌入体内，加速伤口愈合。",
        kind="consumable", hidden=True, takable=True,
        traits=["consumable", "heal"],
        use_effect={"heal": 12},  # 消耗品：回 12 hp
    ))
    world.add_object(GameObject(
        id="cave_crystal",
        name="洞壁晶簇",
        description="洞壁上一簇自发光的青蓝色晶簇，光芒随呼吸般明灭。靠近时能感到微弱的暖意——这是回廊的天然魔力矿脉。",
        kind="scenery",
        traits=["magic_source"],
        takable=False,
        affordances={
            "attune": Affordance(
                verb="attune",
                desc="伸手触摸晶簇，感应魔力",
                effect={"clues": ["指尖触到晶簇的瞬间，一股暖流顺手臂窜上烙印。"
                                    "你感到体内的回廊之力涨了一截——魔力池+5 stamina。"],
                        "flags": {"cave_attuned": True}},
            ),
        },
    ))

    # ── 第二层入口物体 ──
    world.add_object(GameObject(
        id="floor_2_crystal",
        name="第二层·传送水晶",
        description="一根全新的蓝色水晶柱，表面还没有任何划痕。回廊在你击败层守后生成了它——这是新的存档点，也是第一层的句号。",
        kind="scenery",
        traits=["save_point", "new_floor"],
        takable=False,
        affordances={
            "attune": Affordance(
                verb="attune",
                desc="将手按上水晶，激活第二层烙印",
                effect={"flags": {"floor_2_attuned": True},
                        "clues": ["水晶在你掌心下亮起——这一次没有低语，只有一种沉默的确认。"
                                    "回廊承认了你的第一层攻略。烙印上多了一道细不可见的刻痕。"],
                        "unlock_exit": "up"},
            ),
        },
    ))
    world.add_object(GameObject(
        id="floor_2_marker",
        name="螺旋阶梯铭牌",
        description="立在阶梯入口旁的石刻铭牌，上面刻着：「苍穹回廊·第二层·炎砾荒原」。下面用小字刻着一行前人留的警示：'带水。真的，带水。'",
        kind="scenery",
        traits=["lore"],
        takable=False,
    ))

    # ── 初始状态 ──────────────────────────────────────────────────
    world.initial_state = GameState(
        position="camp",
        # 冷开局：身无长物。没有武器（赤手 1d1）、没有护甲、没有回复、没有钱。
        # 第一件事是【破局】——靠脑子和胆子挣出第一把武器、第一枚铜板、第一个人脉。
        inventory=[],
        flags={},
        alertness=0,
        clues=[],
        turn=0,
        profile=ActorProfile(
            name="你",
            role="流落的新烙印者",
            background=(
                "三天前被回廊烙印硬生生卷上这座浮空塔的倒霉蛋。没有剑、没有钱、"
                "不认识任何人——只有一身淤青和一个还没死的事实。城里没人会白帮你。"
            ),
        ),
        vitals=VitalStats(
            hp=6,
            max_hp=6,
            gold=0,
            reputation=0,
            ac=10,            # 无甲，赤身基线
            speed=10,
            stamina=4,        # SP 也低——还没本钱谈剑技
            max_stamina=4,
            level=1,
            exp=0,
            attributes={"str": 3, "dex": 4, "con": 3, "int": 2},  # 能挥拳，只是没武器没体格
        ),
        # 一无所长：没有出身技能。剑技要靠破局后习得（教官/宝箱/剧情）。
        skills=[],
        conditions=[],
        # 认识的人 0：镇上没有一个人欠你人情。关系靠破局后一点点挣。
        relationships={},
        world_time=WorldTime(
            calendar="回廊历 第1层",
            day=1,
            phase="noon",
            minute=0,
            weather="clear",
        ),
        quest_log=[
            QuestEntry(
                id="break_the_deadlock",
                title="破局",
                stage="penniless",
                summary=(
                    "六点血、一双空拳、兜里一枚铜板都没有，连城外那只杀人兔都弄不死你"
                    "——但你也弄不死它。在这座没人会白帮你的小镇里，第一件事是给自己"
                    "挣出一条活路：一把像样的武器、第一笔钱、或者一个肯帮你的人。"
                ),
                deadline="",
                # 阶段机（GM 用 update_quest 推进）：
                #   penniless → armed（搞到第一把武器：木棍/手斧/或别的）
                #   → first_blood（凭它弄死城外的杀人兔）→ standing（在镇上有了立足之地）
                # 三条明路（非唯一）：①酒馆斗殴搏个道义补偿 ②攻击树得木棍
                #   ③闯树林进废弃守林员小屋拿手斧。也可即兴，GM 用 gm_set_flag 裁定。
                known_facts=[
                    "你 hp 上限只有 6，赤手空拳只有 1d1，几乎打不动任何东西",
                    "城外的杀人兔有 8 点血、会 1d4 撕咬，硬刚必死",
                    "镇上没人会无偿帮一个没钱没名的新人",
                ],
                unresolved=[
                    "去哪儿弄到第一把武器",
                    "酒馆里那群人在吵什么",
                    "城外的树林深处有什么",
                ],
            ),
            QuestEntry(
                id="floor_1_conquest",
                title="攻略第一层",
                stage="not_yet",
                summary="传说攻破雾语迷宫、击败层守裂蹄牛魔王，就能开启通往第二层的回廊门。但那是活下来、变强之后才敢想的事。",
                deadline="",
                # 阶段机（GM 用 update_quest 推进 stage）：
                #   entered_floor_1 → cleared_labyrinth（解开符文门）
                #   → warden_defeated（击败层守）→ floor_2_unlocked（回廊门开）
                # 成长循环：打怪/通关给 grant_xp("sword_mastery"/"vertical_arc", n)，
                #   跨 rank_thresholds 自动升等级。营地 skill_trainer / 迷宫宝箱可学剑技。
                known_facts=[
                    "苍穹回廊逐层攻略，死亡即真死",
                    "第一层首领是裂蹄牛魔王，弱点在炎",
                    "营地是安全区，可整备与学剑技",
                ],
                unresolved=[
                    "如何攻破雾语迷宫的符文门",
                    "层守的攻击规律",
                    "登顶后的「一愿」是否真实",
                ],
            ),
            QuestEntry(
                id="lost_talisman",
                title="迷途护符",
                stage="available",
                summary="艾琳的雾语青石护符掉在草原了。找到它，她会把自己的猎杀匕首送给你。",
                deadline="",
                known_facts=[
                    "艾琳是刚进塔不到一周的新手攻略者",
                    "护符是母亲给的进塔饯别礼，对她意义重大",
                    "护符大概掉在草原北边的草丛里",
                    "回报是她的猎杀匕首——纯敏捷，对付疾风狼有奇效",
                ],
                unresolved=[
                    "护符的具体位置",
                ],
            ),
            QuestEntry(
                id="explore_mist_cave",
                title="雾隐洞窟",
                stage="available",
                summary="草原西侧石壁上有一道被藤蔓掩住的裂隙。里面可能藏着前人留下的好东西——但也可能有危险。",
                deadline="",
                known_facts=[
                    "裂隙在草原西侧石壁上，被藤蔓半掩",
                    "风从缝里灌出来时带着发光的菌丝味",
                    "补给箱上写着'别碰洞底那东西'的警告",
                ],
                unresolved=[
                    "洞里有什么",
                    "洞底'那东西'是什么",
                ],
            ),
        ],
    )
