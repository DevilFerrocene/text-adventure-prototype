"""亚楠下层区 — 孟达希尔王都，雨夜委托。

世界观：艾克薇尔大河世界，孟达希尔王国，维多利亚蒸汽朋克 + 中世纪奇幻。
场景：王都亚楠下层区，王国历302年，雨季深夜。
开局：主角接了一份神秘委托，五万金币定金，任务是让某位领主"意外"死亡。

四个房间：
  破旧公寓 → 雨夜巷子 → 低矮酒馆（Anchor: 铁匠铺/情报) → 码头仓库
核心流程：
  读信→发现委托人线索→出门→在巷子拾遗落物→酒馆打听情报→码头确认目标
"""

from core.types import (
    Room, GameObject, Affordance, GameState, WorldCanon, InventoryItem,
    ActorProfile, VitalStats, WorldTime, QuestEntry, EnemyTemplate,
    Skill, ActiveSkill, ReactiveSkill, Step, Modifier,
)
from runtime.game_world import GameWorld


YANAN_CANON = WorldCanon(
    setting_blurb="艾克薇尔大河世界，孟达希尔王国，维多利亚蒸汽朋克+中世纪奇幻。煤气灯、蒸汽管道、魔法共存。无现代电子设备。",
    forbidden=["电子设备", "手机", "现代枪械（火药武器存在但管制）", "现代俚语", "汽车"],
    aesthetic_tags=["蒸汽朋克", "煤气灯", "雨夜", "煤灰", "铁锈", "阴谋", "悬疑"],
    name_style="西式中世纪人名，可带斯拉夫/拉丁词根，孟达希尔王国风格",
)

ENEMIES = {
    "dock_thug": EnemyTemplate(
        id="dock_thug", name="码头打手",
        archetype="brute_low", hp=8, max_hp=8, ac=10, speed=8,
        damage_expr="1d6", damage_type="blunt",
        behavior_profile="aggressive", skills=[],
        loot=[], flavor="穿着油布雨衣，腰间别着一根包铁短棍。",
    ),
    # 主线后半段守卫：领主护卫（中级，把守船坞入口）
    "lord_guard": EnemyTemplate(
        id="lord_guard", name="领主护卫",
        archetype="brute_mid", hp=14, max_hp=14, ac=12, speed=8,
        damage_expr="1d6+2", damage_type="slash",
        behavior_profile="aggressive", skills=[],
        loot=["guard_token"],
        flavor="贝尔维斯雇的私兵，褪色的灰斗篷上别着船锚徽章。短刀出鞘前会在手中转半圈——一种老兵的坏习惯。",
    ),
    # 目标本人参战时的战斗形态（正面解法用）。注意：lord_belveth 同时是船坞里的
    # NPC 物体（可被潜行绞杀/嫁祸），这个模板仅用于"正面战斗"分支 start_combat。
    "belveth_combatant": EnemyTemplate(
        id="belveth_combatant", name="贝尔维斯领主",
        archetype="boss", hp=20, max_hp=20, ac=13, speed=10,
        damage_expr="1d8+2", damage_type="pierce",
        behavior_profile="cautious", skills=[],
        loot=["belveth_signet"],
        flavor="鬓角花白仍不掩警觉，紫缎马甲下藏着一柄细刺剑。他习惯了被人畏惧，还不习惯被人猎杀。",
    ),
}


# ── 技能表（§6 Phase 3-5）──────────────────────────────────────────
# 三种参与方式各一个示例：passive(常驻) / active(主动) / reactive(触发)。
SKILLS = {
    # Phase 3：被动常驻——潜行/感知相关掷骰 +2
    "stealth_training": Skill(
        id="stealth_training", name="潜行训练",
        desc="街头摸爬滚打练出的身法，潜行与察觉相关检定更稳。",
        passive_modifiers=[
            Modifier(
                id="passive", source_kind="skill", source_id="stealth_training",
                target="roll", selector={"reason_includes": ["潜行", "察觉", "感知", "躲藏"]},
                op="add", value=2, reason="潜行训练", visible="full",
            ),
        ],
        obtained_from="background:underdweller",
    ),

    # Phase 4：主动——潜行术。扣 stamina，挂 hidden buff 让下次感知掷骰 +5
    "stealth_art": Skill(
        id="stealth_art", name="潜行术",
        desc="屏息凝神隐入暗处，下一次潜行检定大幅提升。",
        active=ActiveSkill(
            cost={"stamina": 2},
            cooldown=3,
            recipe=[
                Step(verb="apply_buff", args={
                    "name": "隐入暗处", "desc": "气息收敛，下次潜行检定 +5",
                    "polarity": "buff", "target": "roll", "op": "add", "value": 5,
                    "duration": 2, "timing": "on_check",
                    "reason": "潜行术", "visible": "full",
                    "selector": {"reason_includes": ["潜行", "躲藏"]},
                }),
                Step(verb="narrative_tag", args={"tag": "隐匿中"}),
            ],
        ),
        obtained_from="npc:fence",
    ),

    # Phase 5：反应——街头直觉。被偷袭前（before_roll，理由含"偷袭/突袭"）自动加感知
    "street_instinct": Skill(
        id="street_instinct", name="街头直觉",
        desc="对危险有近乎野兽的预感，遭突袭时反应快人一步。",
        reactive=ReactiveSkill(
            trigger="before_roll",
            condition={"reason_includes": ["偷袭", "突袭", "伏击"]},
            recipe=[
                Step(verb="emit_modifier", args={
                    "target": "roll", "op": "add", "value": 3,
                    "reason": "街头直觉", "visible": "full",
                    "selector": {"reason_includes": ["偷袭", "突袭", "伏击"]},
                }),
            ],
        ),
        obtained_from="background:underdweller",
    ),
}


def register(world: GameWorld):
    world.set_world_canon(YANAN_CANON)
    world.register_enemies(ENEMIES)
    world.register_skills(SKILLS)

    # ── 房间 ─────────────────────────────────────────────────────

    world.add_room(Room(
        id="apartment",
        name="破旧公寓·三楼",
        base_description=(
            "亚楠下层区的雨总是带着甜腥味——炼金废气、地沟油、铁锈，还有烂掉的梦想。"
            "狭小的房间里，窗户永远合不严，雨水顺着木框慢慢渗进来。"
            "桌上摆着一个发霉的皮袋子，旁边压着一封猩红封蜡的信。"
        ),
        exits={"south": "alley"},
        objects=["sealed_letter", "coin_bag", "cracked_window", "worn_table", "rumpled_bed"],
        area="亚楠下层区",
        zone="破旧公寓",
        coords=(0, 0),
        tags=["indoor", "safe_room", "lower_district", "rain_leak"],
    ))

    world.add_room(Room(
        id="alley",
        name="下层区巷子",
        base_description=(
            "雨水顺着石板路汇成细流，带走煤灰和不知名的污渍。"
            "两侧楼墙压得很近，只剩一线天光。蒸汽管道在头顶嗤嗤作响，偶尔喷出一团白雾。"
            "巷子南端有一盏摇曳的煤气灯，灯下隐约是酒馆的招牌。"
        ),
        exits={"north": "apartment", "south": "tavern"},
        objects=["wet_cobblestone", "steam_pipe", "muddy_glove", "graffiti_wall", "dung_heap"],
        area="亚楠下层区",
        zone="雨夜巷道",
        coords=(0, -1),
        tags=["outdoor", "alley", "lower_district", "heavy_rain", "steam_pipe"],
    ))

    world.add_room(Room(
        id="tavern",
        name="锈钩酒馆",
        base_description=(
            "低矮的拱顶，烟熏得发黑的横梁，常驻的酸臭啤酒气味。"
            "客人不多，各自缩在角落，没人想让人看清脸。"
            "吧台后面的老板是个矮人，胡子遮住了大半张脸，擦杯子的动作机械得像发条玩具。"
            "墙角贴着一张手写的告示牌，字迹潦草。"
        ),
        exits={"north": "alley", "east": "warehouse"},
        locked_exits={"east": "dock_key"},
        objects=["dwarf_bartender", "notice_board", "corner_drunk", "sticky_counter", "empty_mug"],
        area="亚楠下层区",
        zone="锈钩酒馆",
        coords=(0, -2),
        tags=["indoor", "tavern", "contact_point", "lower_district"],
    ))

    world.add_room(Room(
        id="warehouse",
        name="码头仓库·7号",
        base_description=(
            "盐腥味和腐木的气息扑面而来。高大的货架投下深沉的阴影，"
            "只有远处码头的灯火从木板缝里透进几丝光。"
            "地上有新鲜的脚印，通向仓库深处一个被粗麻布盖着的大箱子。"
        ),
        exits={"west": "tavern", "east": "dock_7_yard"},
        objects=["large_crate", "footprints", "dock_manifest", "rusty_hook", "lantern_post"],
        area="亚楠码头",
        zone="7号仓库",
        coords=(1, -2),
        tags=["indoor", "warehouse", "dockside", "contraband_site", "river_adjacent"],
        enemies=["dock_thug"],
    ))

    # ── 主线后半段：码头7号外围 → 领主船坞 ────────────────────────
    # 暗杀目标贝尔维斯领主藏在私人船坞。三种解法（正面战斗/潜行绞杀/嫁祸谋略）
    # 的机制钩子见下方物体与 affordance。

    world.add_room(Room(
        id="dock_7_yard",
        name="7号仓库外围·守卫驻点",
        base_description=(
            "雨水转过仓库墙角，汇入一条排水沟。前方是领主私人船坞的入口——"
            "两盏煤气灯把守岗哨照得惨白，光线在湿漉漉的货箱上拖出长影。"
            "空气里混着焦油、铁锈和河水腥气。"
        ),
        exits={"west": "warehouse", "east": "lord_boathouse"},
        # east 默认锁住——必须先处理守卫（战斗/潜行/嫁祸任一）才放行
        locked_exits={"east": "guard_post_cleared"},
        objects=["guard_post", "stacked_crates", "mooring_rope", "gas_lamp_yard"],
        area="亚楠码头",
        zone="7号外围",
        coords=(2, -2),
        tags=["outdoor", "dockside", "guarded", "river_adjacent", "approach"],
        enemies=["lord_guard"],
    ))

    world.add_room(Room(
        id="lord_boathouse",
        name="领主私人船坞",
        base_description=(
            "低矮的木构船坞里，一艘铜壳蒸汽快艇静静浮在水面，锅炉余温在湿气中凝成薄雾。"
            "贝尔维斯领主背对着入口，正弯腰清点一只打开的货箱。他的影子在油灯下拉得很长。"
            "这里就是终点。"
        ),
        exits={"west": "dock_7_yard"},
        objects=["lord_belveth", "steam_launch", "smuggled_arms_crate", "boathouse_lantern", "oil_drums"],
        area="亚楠码头",
        zone="领主船坞",
        coords=(3, -2),
        tags=["indoor", "dockside", "river_adjacent", "target_location", "climax"],
    ))

    # ── 公寓物体 ──────────────────────────────────────────────────

    world.add_object(GameObject(
        id="sealed_letter",
        name="猩红封蜡的信",
        description=(
            "封蜡上压着一个你认不出的家族纹章——一条咬住自己尾巴的蛇。"
            "信封沉甸甸的，里面不只是纸。"
        ),
        kind="document",
        named_tags=["quest_item", "evidence"],
        modifiers=["fragile"],
        traits=["quest", "sealed", "contains_key"],
        takable=True,
        hidden_clue="委托人徽记：衔尾蛇纹章",
        hidden_flag="read_letter",
        reveals_objects=["dock_key"],
        affordances={
            "read": Affordance(
                verb="read",
                desc="拆开信，阅读委托内容",
                effect={
                    "flags": {"letter_opened": True},
                    "clues": ["信件内容：目标是贝尔维斯领主，期限三天，尾款五万，联络点码头7号"],
                    "reveals_objects": ["dock_key"],
                },
            ),
            "tear": Affordance(
                verb="tear",
                desc="把信撕毁（不可逆，可能产生碎片）",
                effect={"flags": {"letter_torn": True}},
                consume_self=True,
            ),
            "burn": Affordance(
                verb="burn",
                desc="烧毁信件（需要火源）",
                effect={"flags": {"letter_burned": True}},
                consume_self=True,
            ),
        },
    ))

    world.add_object(GameObject(
        id="dock_key",
        name="信中的钥匙",
        description="从信封里滑出来的一把小铁钥匙，上面刻着'7'。码头仓库的号码。",
        kind="key",
        named_tags=["quest_item", "dock_access"],
        modifiers=["small", "concealable", "noisy"],
        traits=["warehouse_7", "proof"],
        takable=True,
        hidden=True,
        affordances={
            "show": Affordance(
                verb="show",
                desc="把钥匙展示给矮人老板看，他会指路",
                effect={
                    "unlock_exit": "east",
                    "flags": {"bartender_unlocked_way": True},
                    "clues": ["矮人老板认识这把钥匙——他是联络人之一"],
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="coin_bag",
        name="发霉的皮袋子",
        description=(
            "五万金币的定金。你数过三遍了，每一枚都印着女王的侧脸。"
            "钱早已是你的资产（记在身家里，不在这只袋子里）——袋子只是它来时的包装。"
        ),
        kind="container",
        named_tags=["payment"],
        modifiers=["heavy", "noisy"],
        traits=["money", "quest_reward"],
        takable=False,
        # 报酬是抽象资产（gold 走 vitals），不绑实体。袋子是叙事道具，不该被一发
        # 火球把存款烧没——标 indestructible，破坏它在机制上无意义。见会话记录。
        indestructible=True,
    ))

    world.add_object(GameObject(
        id="cracked_window",
        name="合不严的窗户",
        description=(
            "窗框已经变形，不管怎么用力都留着一条缝。"
            "雨水顺着缝隙慢慢渗进来，在窗台上积了一小滩。"
            "从这里能看到下层区连绵的屋顶，还有远处上层区灯火的轮廓——那是另一个世界。"
        ),
        kind="scenery",
        traits=["vantage_point", "rain"],
        takable=False,
        hidden_clue="上层区方向有一栋塔楼，三楼亮着灯",
        hidden_flag="noticed_tower_light",
    ))

    world.add_object(GameObject(
        id="worn_table",
        name="破旧的桌子",
        description="桌面布满刀痕，不知道是前任房客留下的还是更早之前的。有几道划痕像是某种符文。",
        kind="container",
        traits=["surface", "scratched"],
        takable=False,
    ))

    world.add_object(GameObject(
        id="rumpled_bed",
        name="皱巴巴的床铺",
        description="窄床，薄被，枕头里可能填的是稻草。睡过一夜后背已经在抗议了。",
        kind="container",
        traits=["hiding_place"],
        takable=False,
    ))

    # ── 巷子物体 ──────────────────────────────────────────────────

    world.add_object(GameObject(
        id="wet_cobblestone",
        name="石板路",
        description="被雨水冲得发亮的石板，缝隙里长着暗绿色的苔藓。走路要小心，很滑。",
        kind="scenery",
        traits=["slippery", "rain"],
        takable=False,
    ))

    world.add_object(GameObject(
        id="steam_pipe",
        name="蒸汽管道",
        description=(
            "直径半米的铸铁管道从墙体穿过，表面因为温差结着水珠。"
            "阀门处有一圈新的焊接痕迹，不知道是修补了什么。"
        ),
        kind="tool",
        traits=["steam", "hazard", "valve"],
        takable=False,
    ))

    world.add_object(GameObject(
        id="muddy_glove",
        name="泥污的手套",
        description="一只男式皮手套，左手，泡在路边的积水里。掌心有一个被磨穿的洞，中指位置有血迹。",
        kind="clue",
        named_tags=["evidence"],
        modifiers=["small", "concealable", "wet"],
        traits=["blood", "personal_effect"],
        takable=True,
        hidden_clue="遗失的手套：左手，掌心穿洞，中指血迹",
        hidden_flag="found_glove_clue",
        affordances={
            "show": Affordance(
                verb="show",
                desc="把手套放到角落醉汉面前，看他反应",
                effect={
                    "flags": {"drunk_identified": True},
                    "clues": ["醉汉猛地抬头——这是他的手套，他是贝尔维斯领主的侦察员"],
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="graffiti_wall",
        name="涂鸦墙",
        description=(
            "墙上满是各色涂鸦，叠了一层又一层。"
            "最新的一条用红漆写着：『领主的血会喂肥大河女神』，字迹还没干透，被雨水晕开了边缘。"
        ),
        kind="trace",
        named_tags=["evidence"],
        traits=["fresh_paint", "political"],
        takable=False,
        hidden_clue="新涂鸦：『领主的血会喂肥大河女神』",
        hidden_flag="read_graffiti",
    ))

    # ── 可破坏物示例（§9 E3：万物皆可破坏 + on_destroyed）──────────
    # 牛粪堆——fragile（hp=1），鞭炮一炸/棍子一捅就散，里面藏着前任侦察员
    # 慌乱中塞进去的信物。展示"破坏揭示"链路：deal_damage → on_destroyed →
    # reveals_objects + flags + clues。
    world.add_object(GameObject(
        id="dung_heap",
        name="牛粪堆",
        description=(
            "巷角一堆发酵到冒泡的牛粪，雨水把臭味泡得愈发上头。"
            "苍蝇绕着它打转，没人愿意靠近——正因如此，它是藏东西的好地方。"
        ),
        kind="scenery",
        traits=["filthy", "fragile", "hiding_place"],
        takable=False,
        hp=1, max_hp=1, ac=3,                       # 一碰就散
        damage_types_resist={},                      # 无抗性，全类型 1.0
        on_destroyed=[
            {
                "reveals_objects": ["rusted_token"],
                "flags": {"dung_heap_destroyed": True},
                "clues": ["炸开的牛粪里滚出一枚锈蚀信物——有人匆忙间把它埋了进去"],
            },
        ],
    ))

    world.add_object(GameObject(
        id="rusted_token",
        name="锈蚀的信物",
        description="一枚黄铜小牌，表面锈得发绿，依稀能辨出衔尾蛇的轮廓——和委托人的徽记同源。",
        kind="clue",
        named_tags=["evidence"],
        modifiers=["small", "concealable"],
        traits=["ouroboros", "personal_effect"],
        takable=True,
        hidden=True,                                 # 默认隐藏，被 on_destroyed 揭示
    ))

    # ── 酒馆物体 ──────────────────────────────────────────────────

    world.add_object(GameObject(
        id="dwarf_bartender",
        name="矮人老板",
        description=(
            "三十岁还是三百岁，从外表看不出来。"
            "他的动作很慢，但眼睛很快——每个进门的人他都扫一遍，分类，定价，归档。"
        ),
        kind="npc",
        traits=["contact", "bartender"],
        takable=False,
        hidden_clue="老板认识衔尾蛇纹章，听到问题后停顿了整整三秒",
        hidden_flag="bartender_knows",
    ))

    world.add_object(GameObject(
        id="notice_board",
        name="告示牌",
        description=(
            "三张手写告示：招募搬运工（已满），寻人启示（字迹模糊），"
            "还有一张只写着坐标——'码头7号，午夜后'——没有落款。"
        ),
        kind="document",
        named_tags=["evidence"],
        traits=["public_notice", "coordinates"],
        takable=False,
        hidden_clue="码头7号·午夜后——有人在等",
        hidden_flag="read_notice",
    ))

    world.add_object(GameObject(
        id="corner_drunk",
        name="角落的醉汉",
        description=(
            "缩在角落里，帽沿压得很低，喝的不是酒馆的便宜麦酒，是他自带的皮扁壶。"
            "你注意到他的靴子上有新鲜的泥，和巷子里不一样的颜色——码头的泥，咸腥的。"
        ),
        kind="npc",
        traits=["drunk", "scout", "suspicious"],
        takable=False,
        hidden_clue="醉汉靴子上的码头泥——他从7号仓库那边来",
        hidden_flag="spotted_drunk_boots",
    ))

    world.add_object(GameObject(
        id="sticky_counter",
        name="黏腻的吧台",
        description="麦酒渍、蜡烛油和不明物质的混合物，已经风干成了一层棕色的膜。",
        kind="scenery",
        traits=["tavern_surface"],
        takable=False,
    ))

    world.add_object(GameObject(
        id="empty_mug",
        name="空啤酒杯",
        description="厚壁玻璃杯，还带着泡沫的痕迹。",
        kind="tool",
        traits=["improvised_container"],
        takable=False,
    ))

    # ── 仓库物体 ──────────────────────────────────────────────────

    world.add_object(GameObject(
        id="large_crate",
        name="粗麻布覆盖的大箱子",
        description=(
            "木箱很新，钉子还没生锈。掀开一角的麻布——里面是枪械零件，"
            "精密得超出这个地区能生产的水平。外销管制品，或者……走私货。"
        ),
        kind="container",
        named_tags=["quest_item", "evidence", "contraband"],
        modifiers=["heavy"],
        traits=["contraband", "covered"],
        takable=False,
        hidden_clue="箱中走私枪械：精度超出孟达希尔民间水平，可能是东示巴军工件",
        hidden_flag="found_smuggled_weapons",
    ))

    world.add_object(GameObject(
        id="footprints",
        name="新鲜的脚印",
        description=(
            "两双，尺码不同。一双深，一双浅，深的那双步伐均匀，浅的那双在某处停下来打了个转——"
            "像是环顾四周确认没人跟踪。两双都通向那个大箱子。"
        ),
        kind="trace",
        named_tags=["evidence"],
        traits=["fresh", "two_people", "dock_mud"],
        takable=False,
        hidden_clue="两组脚印：一深一浅，均止于大箱子",
        hidden_flag="analyzed_footprints",
    ))

    world.add_object(GameObject(
        id="dock_manifest",
        name="货运清单",
        description=(
            "夹在货架缝里，被雨水打湿过又晾干了，字迹还认得出。"
            "收货方一栏写着：'贝尔维斯领地事务处'。发货日期是三天前。"
        ),
        kind="document",
        named_tags=["quest_item", "evidence"],
        modifiers=["fragile"],
        traits=["manifest", "evidence"],
        takable=True,
        hidden_clue="货运清单收货方：贝尔维斯领地事务处，三天前到货",
        hidden_flag="read_manifest",
        affordances={
            "show": Affordance(
                verb="show",
                desc="把货运清单推过吧台，让矮人老板看",
                effect={
                    "flags": {"bartender_talked": True},
                    "clues": ["老板低声说：贝尔维斯的人从三天前就开始往仓库运东西，不止武器"],
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="rusty_hook",
        name="铁钩",
        description="装卸货物用的大铁钩，挂在墙上，够重，够长。",
        kind="tool",
        modifiers=["heavy", "noisy"],
        traits=["heavy", "hook"],
        takable=True,
    ))

    world.add_object(GameObject(
        id="lantern_post",
        name="码头灯柱",
        description=(
            "仓库后门通向码头，灯柱上的油灯还亮着，橘黄的光在水面上拉出一条长长的倒影。"
            "河对岸，上层区的灯火一片连绵——那边的领主大人，现在是否也在某扇窗后面看着同一条河？"
        ),
        kind="scenery",
        traits=["light_source", "river_view"],
        takable=False,
    ))

    # ── 7号外围物体（守卫驻点 + 三解法入口）────────────────────────
    # east 出口锁 guard_post_cleared。三种解法各自把它置 true：
    #   正面战斗 → guard_post 的 provoke affordance 开战，GM 在敌人全灭后置 flag
    #   潜行绞杀 → guard_post 的 sneak affordance（潜行检定，GM 裁定后置 flag）
    #   嫁祸谋略 → smuggled_arms_crate 的 plant_evidence，引守卫内讧撤离
    world.add_object(GameObject(
        id="guard_post",
        name="守卫驻点",
        description="一扇锈迹斑斑的铁栅栏横在通往船坞的入口前。两名护卫在煤气灯下来回踱步，斗篷下摆扫着积水。岗哨旁支着个炭火盆，铁网上的鱼骨还没啃干净——你来得正是时候。",
        kind="scenery",
        traits=["obstacle", "guarded"],
        takable=False,
        affordances={
            # 解法A：正面挑衅 → 开战。胜负由战斗系统裁定；GM 在敌人全灭后
            # 调 update_quest/set flag guard_post_cleared 放行（见 SKILL 指引）。
            "provoke": Affordance(
                verb="provoke",
                desc="正面现身，以刀剑而非谎言面对守卫",
                effect={
                    "flags": {"chose_combat": True},
                    "clues": ["你踏出阴影，守卫猛地转头——炭火盆的火光在你脸上跳了一下，接下来只有刀刃的应答"],
                    "start_combat": {"canon": ["lord_guard"]},
                },
            ),
            # 解法B：潜行绕过。requires_flag 由 GM 在潜行检定成功后置；这里
            # 的 affordance 只负责"检定通过后落 flag + 解锁"。GM 先 roll_check，
            # 成功才允许调用本 verb（SKILL 指引说明）。
            "sneak_past": Affordance(
                verb="sneak_past",
                desc="借货箱阴影潜行绕过守卫（需先通过潜行检定）",
                requires_flag="stealth_check_passed",
                effect={
                    "flags": {"guard_post_cleared": True, "chose_stealth": True},
                    "unlock_exit": "east",
                    "clues": ["你贴着货箱边缘一寸寸挪过岗哨，守卫的靴跟在你鼻尖三尺外转了一圈——然后走开了。雨水声盖住了一切"],
                },
            ),
            # 解法B'：引开守卫。先制造一个干扰源（推倒货箱 crates_toppled，
            # 或别处声响），再用此 verb 把守卫调离岗哨。requires_flag 确保
            # "先有动静才引得走"，逻辑自洽；属于潜行系（不暴露身份）。
            "distract": Affordance(
                verb="distract",
                desc="趁货场骚动把守卫引离岗哨（需先制造声响，如推倒货箱）",
                requires_flag="crates_toppled",
                effect={
                    "flags": {"guard_post_cleared": True, "chose_stealth": True},
                    "unlock_exit": "east",
                    "clues": ["两名守卫循着倒塌声冲向货场深处。你从他们让出的空当里闪过铁栅栏——通道空了"],
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="stacked_crates",
        name="堆叠的货箱",
        description="五六个齐人高的货箱堆在货场上，粗麻布罩角渗出雨水。箱体之间的窄缝刚好容一人贴身穿行——但也可能一个不小心就碰倒整组。",
        kind="scenery",
        traits=["cover", "fragile"],
        modifiers=["heavy"],
        takable=False,
        hp=8, max_hp=8, ac=4,
        on_destroyed=[{
            "flags": {"crates_toppled": True},
            "clues": ["货箱轰然倒塌，木板砸在石地上炸开一声闷响。你听见岗哨方向传来急促的脚步——有人过来查看了"],
        }],
    ))

    world.add_object(GameObject(
        id="mooring_rope",
        name="系船缆绳",
        description="一根手腕粗的麻缆从船坞铁桩上绕过，末端牢牢系在快艇艏柱。缆绳在潮水中绷得吱嘎作响，像是在等一把刀。",
        kind="tool",
        traits=["rope", "sabotage_hook"],
        takable=False,
        hp=3, max_hp=3, ac=6,
        damage_types_resist={"slash": 2.0},  # 斩击易断
        on_destroyed=[{
            "flags": {"launch_adrift": True},
            "clues": ["缆绳在刀刃下绽开最后一缕麻丝，蒸汽快艇无声地滑离码头，被潮水缓缓拖入暗夜——领主就算活过今晚，也走不掉了"],
        }],
    ))

    world.add_object(GameObject(
        id="gas_lamp_yard",
        name="货场煤气灯",
        description="一根铸铁灯柱上挂着双头煤气灯，嘶嘶吐着惨白火焰，把周围十步照得无处可藏。灯罩上积了一层煤灰，光线已经发黄。",
        kind="scenery",
        traits=["light_source"],
        takable=False,
        affordances={
            "extinguish": Affordance(
                verb="extinguish",
                desc="拧灭煤气灯，让整个货场沉入黑暗（获得潜行加成）",
                effect={
                    "flags": {"yard_dark": True},
                    "clues": ["煤气灯发出最后一丝嘶鸣后熄灭，货场像落进墨汁。你听着守卫在暗处咒骂，嘴角动了一下——现在猎人是你了"],
                },
            ),
        },
    ))

    # ── 领主船坞物体（最终对决 + 三种收尾）──────────────────────────
    world.add_object(GameObject(
        id="lord_belveth",
        name="贝尔维斯领主",
        description="贝尔维斯，领地的拥有者、走私的操盘手、暗杀名单上的名字。他正弯着腰用一根铁撬检查货箱，浑然不知今夜的雨水比往常更腥——他呼吸着自己的最后几分钟。",
        kind="npc",
        named_tags=["assassination_target"],
        traits=["target", "noble"],
        takable=False,
        hp=20, max_hp=20, ac=13,
        affordances={
            # 解法B 收尾：潜行绞杀（要求已潜行进入且目标未察觉）
            "assassinate": Affordance(
                verb="assassinate",
                desc="从背后无声了结目标（需潜行接近）",
                requires_flag="chose_stealth",
                effect={
                    "flags": {"target_eliminated": True, "silent_kill": True},
                    "clues": ["铁撬从领主手中滑落，敲在木板上的声响被你的刀锋盖过。他只来得及发出一声湿漉漉的气音，然后一切重归雨声。快艇锅炉仍在低鸣，仿佛什么都没发生"],
                },
                consume_self=True,  # 目标倒下，从场景移除
            ),
            # 解法A 收尾：正面对决，开战（目标作为 boss combatant）
            "confront": Affordance(
                verb="confront",
                desc="走出暗处，报上名字，让他知道是谁来收了这条命",
                effect={
                    "flags": {"chose_combat": True},
                    "start_combat": {"canon": ["belveth_combatant"]},
                },
            ),
        },
    ))

    world.add_object(GameObject(
        id="smuggled_arms_crate",
        name="走私军火木箱",
        description=(
            "木箱上的东示巴徽记还没刮干净，里面的精密枪械零件包裹在浸油的麻布里。"
            "这批货够贝尔维斯掉十次脑袋——或者，够你编一个足够杀死他的故事。"
        ),
        kind="container",
        named_tags=["evidence", "contraband"],
        traits=["frame_hook"],
        takable=False,
        affordances={
            # 解法C：嫁祸谋略。摆出证据触发内讧，不亲自动手。
            # requires_item：需要前面拿到的 dock_manifest 货运清单作伪造材料。
            "plant_evidence": Affordance(
                verb="plant_evidence",
                desc="用货运清单伪造收货人变更记录，栽赃领主私吞军火，让'盟友'替他动手",
                requires_item="dock_manifest",
                effect={
                    "flags": {
                        "guard_post_cleared": True,   # 守卫被调去内讧，通道空了
                        "target_eliminated": True,
                        "framed": True,
                        "chose_frame": True,
                    },
                    "unlock_exit": "east",
                    "clues": ["伪造的清单被「不经意」塞进了守卫的巡逻记录里。日出之前，贝尔维斯的人就会互相拔刀——而你已经在下层区的暗巷里数着尾款了"],
                },
                consume_item=True,
            ),
        },
    ))

    world.add_object(GameObject(
        id="steam_launch",
        name="蒸汽快艇",
        description="一艘铜壳蒸汽快艇，吃水线上的铆钉亮得能照出人影。锅炉还在低声振动，冷凝管滴着热水——领主备好了退路，却没算到退路也可以被人先一步切掉。",
        kind="scenery",
        traits=["vehicle", "escape_route"],
        takable=False,
        hp=15, max_hp=15, ac=8,
        on_destroyed=[{
            "flags": {"launch_destroyed": True},
            "clues": ["蒸汽快艇的锅炉最先炸开，铜壳像纸一样撕裂，橙红的火光在水面上炸成一片沸腾的倒影。船坞的木梁在呻吟，领主再没地方可逃了"],
        }],
    ))

    world.add_object(GameObject(
        id="oil_drums",
        name="油桶",
        description="三只铁皮油桶堆在船坞角落，桶壁鼓胀变形，底缝渗出的黑油已经在积水面上铺了一层虹光。哪怕一颗火星也能把这片虹光变成地狱。",
        kind="scenery",
        traits=["hazard", "fragile", "explosive"],
        takable=False,
        hp=2, max_hp=2, ac=4,
        damage_types_resist={"fire": 3.0},  # 遇火剧烈
        on_destroyed=[{
            "flags": {"boathouse_ablaze": True},
            "clues": ["油桶炸开的瞬间，滚烫的油火像活的一样爬过木梁、窗帘、货箱——船坞在三息内变成了炉膛。火舌舔穿屋顶，码头在暴雨中都看得见这道冲天的橙红"],
        }],
    ))

    world.add_object(GameObject(
        id="boathouse_lantern",
        name="船坞油灯",
        description="固定在船坞木柱上的一盏老式油灯，灯座已经锈蚀，一颗螺丝松脱了。灯焰无精打采地晃着，完全不知道自己离三桶漏油只有五步之遥。",
        kind="scenery",
        traits=["light_source", "ignition_hook"],
        takable=False,
    ))

    # affordances 已内联到各 GameObject 定义中

    # ── 初始状态 ──────────────────────────────────────────────────

    world.initial_state = GameState(
        position="apartment",
        inventory=[InventoryItem(
            id="sealed_letter",
            name="猩红封蜡的信",
            desc="封蜡上压着衔尾蛇纹章，信封沉甸甸的，里面不只是纸。",
            tags=["任务"],
            kind="document",
            named_tags=["quest_item", "evidence"],
            modifiers=["fragile"],
        )],
        flags={},
        alertness=0,
        clues=[],
        turn=0,
        profile=ActorProfile(
            name="你",
            role="受雇的暗杀者",
            background="在亚楠下层区接下雨夜委托的外来者",
        ),
        vitals=VitalStats(
            hp=10,
            max_hp=10,
            gold=50000,
            reputation=0,
        ),
        conditions=["rain-soaked"],
        relationships={
            "dwarf_bartender": "unknown_contact",
            "corner_drunk": "unknown",
            "client_snake": "hired_you",
            "lord_belvis": "target",
        },
        world_time=WorldTime(
            calendar="王国历302年 雨季",
            day=17,
            phase="deep_night",
            minute=0,
            weather="heavy_rain",
        ),
        quest_log=[
            QuestEntry(
                id="assassination_contract",
                title="雨夜委托",
                stage="received_contract",
                summary="一封猩红封蜡的信把你卷入贝尔维斯领主的暗杀委托。",
                deadline="三天内",
                # 阶段机（GM 用 update_quest 推进 stage）：
                #   received_contract → reached_dock_7（进 warehouse）
                #   → target_identified（进 lord_boathouse，见到领主）
                #   → target_eliminated（任一解法得手）
                # 收尾解法 flag（互斥，决定结局演绎）：
                #   killed_in_combat（正面战斗，chose_combat 且战斗胜）
                #   silent_kill（潜行绞杀，chose_stealth + assassinate）
                #   framed（嫁祸谋略，chose_frame + plant_evidence）
                # 环境'意外'可叠加：launch_destroyed / boathouse_ablaze / launch_adrift
                known_facts=[
                    "定金五万金币已送达破旧公寓",
                    "委托信封上有衔尾蛇纹章",
                    "联络点指向码头7号",
                ],
                unresolved=[
                    "委托人真实身份",
                    "贝尔维斯领主为何被盯上",
                    "如何接近并了结目标（战斗/潜行/嫁祸）",
                ],
            )
        ],
    )
