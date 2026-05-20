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
    # 第一层首领：雾语草原的霸主
    "warden_gorehoof": EnemyTemplate(
        id="warden_gorehoof", name="层守·裂蹄牛魔王",
        archetype="boss", hp=24, max_hp=24, ac=12, speed=9,
        damage_expr="2d6", damage_type="blunt",
        behavior_profile="aggressive", skills=[],
        damage_types_resist={"fire": 1.5, "frost": 0.5},  # 弱炎、抗霜
        loot=["warden_horn", "floor_2_key"],
        flavor=(
            "肩高两米的牛头巨兽，断角上缠着历代挑战者留下的碎布。蹄子每踏一步，"
            "石殿地砖就多一道白茬裂痕。最可畏的是它的沉默——不像杂兵那样嘶吼，"
            "只是缓慢地、笃定地朝你走来。弱点在炎属剑技。"
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
}


def register(world: GameWorld):
    world.set_world_canon(SPIRE_CANON)
    world.register_enemies(ENEMIES)
    world.register_skills(SKILLS)

    # ── 第一层「雾语草原」房间链 ──────────────────────────────────
    # camp(安全区) → plains(刷怪) → labyrinth(迷宫) → warden_gate(首领)
    world.add_room(Room(
        id="camp",
        name="回廊脚下·营地",
        base_description=(
            "回廊塔底层的天然空洞，被前人凿宽撑高，成了攻略组的营寨。"
            "中央篝火终年不熄——没人说得清是谁在添柴，它只是烧着，蓝焰无声舔舐雾草。"
            "几顶褪色的帐篷和补给摊围成半圆，攻略者三三两两：磨剑的、打盹的、"
            "死盯着刻印石板念念有词的。传送水晶立在营地正中，脉冲般明灭，像在呼吸。"
            "抬头能望见第一层草原的雾气从上方裂口缓缓渗下，像天空在漏光。"
            "这里是回廊的第一条不成文规则——「营地是安全的」。"
        ),
        exits={"north": "plains"},
        objects=["weapon_rack", "teleport_crystal", "skill_trainer", "campfire"],
        area="苍穹回廊·第一层",
        zone="雾语草原·营地",
        coords=(0, 0),
        tags=["safe_zone", "no_combat", "respawn_point", "floor_1"],
    ))

    world.add_room(Room(
        id="plains",
        name="雾语草原",
        base_description=(
            "草高及腰，雾低过膝。整片界域像泡在一杯稀薄的乳白里，十步之外的景物开始融化。"
            "风吹草动时你以为是自己眼花，但那些晃动里总有几处是逆着风向的——那是怪。"
            "草原上散落着石祠、宝箱和齐腰草丛，攻略者在这里刷怪、攒金币、磨炼剑技。"
            "北面雾气最浓处隐约立着几根青石柱，那是迷宫入口的轮廓。"
            "空气里有青草、湿土和一种微弱的甜花香——那是雾语食人花的饵。"
        ),
        exits={"south": "camp", "north": "labyrinth"},
        objects=["field_chest", "mist_shrine", "tall_grass"],
        area="苍穹回廊·第一层",
        zone="雾语草原",
        coords=(0, 1),
        tags=["field", "spawn_ground", "floor_1", "misty"],
        enemies=["frenzy_boar", "gale_wolf", "mistbloom"],
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
        enemies=["gale_wolf"],
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
        exits={"south": "labyrinth"},
        # 击败首领后解锁的回廊门（上行）
        locked_exits={"north": "warden_defeated"},
        objects=["corridor_gate", "warden_arena"],
        area="苍穹回廊·第一层",
        zone="首领之间",
        coords=(0, 3),
        tags=["boss_room", "floor_1", "climax"],
        enemies=["warden_gorehoof"],
    ))

    # ── 营地物体 ──────────────────────────────────────────────────
    world.add_object(GameObject(
        id="weapon_rack",
        name="武器架",
        description=(
            "营地的公用武器架，摆着几柄制式铁剑和一面打凹了的圆盾。"
            "架脚被雾水泡过又晒干，木头翘了一层皮。"
            "愿意要的话，拿一把就是——「反正死在外面的人也用不着了。」"
        ),
        kind="container",
        traits=["equipment"],
        takable=False,
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
            "flags": {"grass_burned": True},
            "clues": [
                        "干燥的草秆遇火即燃，橙红的火舌沿风向席卷整片草丛，黑烟冲天。"
                        "你听见附近传来慌乱的怪叫声——火光不只烧掉了藏身处，"
                        "也烧掉了所有人的伪装。"
                    ],
        }],
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
                        "殿深处的呼吸停了一拍。然后两根弯曲的巨角从暗中缓缓低下来，"
                        "一双赤红的眼睛在角根处亮起——裂蹄牛魔王已经醒了。"
                        "它用沉默回答了你的挑战。首领战开始。"
                    ],
                    "start_combat": {"canon": ["warden_gorehoof"]},
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

    # ── 初始状态 ──────────────────────────────────────────────────
    world.initial_state = GameState(
        position="camp",
        inventory=[InventoryItem(
            id="iron_sword",
            name="新手铁剑",
            desc=(
                "营地配发的制式铁剑，剑锷上刻着回廊攻略组的徽记——一道向上的螺旋。"
                "刃口已有几处细小卷刃，但重心刚好，挥起来顺手。"
                "这是你在回廊里的第一把剑，也许也是最后一把。"
            ),
            tags=["武器", "damage", "dmg:1d6"],
            kind="tool",
            named_tags=["weapon"],
            modifiers=[],
        )],
        flags={},
        alertness=0,
        clues=[],
        turn=0,
        profile=ActorProfile(
            name="你",
            role="回廊攻略者",
            background="被回廊烙印卷入苍穹回廊的剑士，目标是逐层登顶。",
        ),
        vitals=VitalStats(
            hp=20,
            max_hp=20,
            gold=500,
            reputation=0,
            ac=11,
            speed=11,
            stamina=10,       # SP
            max_stamina=10,
        ),
        # 出身自带技能（start:swordsman）：单手剑精通(被动) + 危机回避(反应)。
        # start_game 会深拷贝，玩家成长状态独立于模板。
        skills=[SKILLS["sword_mastery"], SKILLS["crisis_evasion"]],
        conditions=[],
        relationships={
            "skill_trainer": "mentor",
            "warden_gorehoof": "floor_1_boss",
        },
        world_time=WorldTime(
            calendar="回廊历 第1层",
            day=1,
            phase="noon",
            minute=0,
            weather="clear",
        ),
        quest_log=[
            QuestEntry(
                id="floor_1_conquest",
                title="攻略第一层",
                stage="entered_floor_1",
                summary="抵达苍穹回廊第一层「雾语草原」，目标是击败层守、开启通往第二层的回廊门。",
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
            )
        ],
    )
