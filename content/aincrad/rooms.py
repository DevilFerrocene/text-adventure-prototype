"""苍穹回廊：房间。"""
from core.types import Room, RoomGrid, GridPOI


def add_all(world):
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
        objects=["weapon_rack", "registry_officer", "rack_iron_sword", "rack_dagger",
                 "teleport_crystal", "skill_trainer", "campfire",
                 "camp_merchant", "lost_scout", "coin_pouch", "field_notes",
                 "oath_altar"],
        area="苍穹回廊·第一层",
        zone="雾语草原·营地",
        coords=(0, 0),
        tags=["safe_zone", "no_combat", "respawn_point", "floor_1"],
        ambient=["磨剑石:misc", "成堆的补给木箱:furniture", "篝火边的劈柴:club",
                 "拴马桩旁的石块:rock"],
        # 6×6 营寨：篝火居中(进门落点)，武器架/铁剑/短剑在北、薇拉与登记官分两侧、
        # 老马罗补给摊在东、传送水晶/誓约祭坛在西、北门通草原、东门进酒馆。
        grid=RoomGrid(
            width=6, height=6, entry=(2, 2),
            objects={
                "weapon_rack": (0, 0), "rack_iron_sword": (1, 0), "rack_dagger": (3, 0),
                "skill_trainer": (0, 1), "campfire": (2, 1), "registry_officer": (4, 1),
                "teleport_crystal": (0, 3), "camp_merchant": (4, 3),
                "oath_altar": (0, 4), "lost_scout": (3, 4),
                "coin_pouch": (0, 5), "field_notes": (2, 5),
            },
            ambient={
                "磨剑石": (4, 0), "篝火边的劈柴": (1, 2),
                "成堆的补给木箱": (2, 3), "拴马桩旁的石块": (4, 5),
            },
            exits={"north": (2, 0), "east": (5, 2)},
        ),
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
        ambient=["桌上的酒瓶:bottle", "长条木桌:furniture", "翻倒的木凳:furniture",
                 "壁炉边的拨火棍:club", "吊着的油灯:misc", "墙角的空酒坛:bottle"],
        # 二维棋盘（示范房）：5×5。x 东+/y 南+（行号自上而下，顶=北=后墙）。布局：
        #   y\x  0      1       2       3        4
        #   0    .      壁炉    油灯    老板     .
        #   1    .      拨火棍  .       吧台      .
        #   2    门口   .       争吵    .        .
        #   3    .      .       酒瓶    .        .
        #   4    .      木凳    木桌    .        空酒坛
        # 进门(西墙门口)→ 吧台/老板在东北、争吵在正中、壁炉在西北——拿东西/搭话都要走过去。
        grid=RoomGrid(
            width=5, height=5,
            entry=(0, 2),                     # 从营地推门进来，站在西侧门口
            objects={
                "tavern_keeper": (3, 0),      # 吧台后的老板（东北）
                "tavern_brawl": (2, 2),       # 屋子正中那场一触即发的争吵
            },
            ambient={
                "吊着的油灯": (2, 0),         # 后墙正中吊着
                "壁炉边的拨火棍": (1, 1),     # 西北壁炉旁
                "桌上的酒瓶": (2, 3),
                "长条木桌": (2, 4),
                "翻倒的木凳": (1, 4),
                "墙角的空酒坛": (4, 4),       # 东南墙角
            },
            exits={"west": (0, 2)},           # 通营地的门在西墙
            landmarks={"吧台": (3, 1), "壁炉": (1, 0)},
        ),
    ))

    world.add_room(Room(
        id="plains",
        name="雾语草原",
        base_description=(
            "出了镇门就是草原：草高及腰，雾低过膝，十步之外的景物开始在乳白里融化。"
            "风吹草动时你以为是眼花，但那些晃动里偶尔有几处逆着风向——这片草原从不缺东西盯着落单的人。"
            "西边草色压暗，连成一道黑黢黢的树林轮廓；北面雾最浓处立着几根青石柱，是迷宫的入口。"
            "至于此刻草里藏着什么、有没有东西正朝你来——得你自己看清。"
        ),
        exits={"south": "camp", "north": "labyrinth", "west": "forest_edge"},
        objects=["field_chest", "mist_shrine", "tall_grass",
                 "erin_talisman", "mist_cave_entrance"],
        area="苍穹回廊·第一层",
        zone="雾语草原",
        coords=(0, 1),
        tags=["field", "spawn_ground", "floor_1", "misty"],
        enemies=["killer_rabbit", "frenzy_boar", "gale_wolf", "mistbloom"],
        ambient=["没膝的草浪:foliage", "零星的碎石:rock", "风干的兽骨:misc",
                 "半埋的朽木桩:furniture", "尖锐的断枝:club"],
        # 6×6 草原：开阔野地，神龛在北、洞窟裂隙在东南、三向出口（南营地/北迷宫/西树林）。
        grid=RoomGrid(
            width=6, height=6, entry=(2, 3),
            objects={
                "mist_shrine": (2, 0), "erin_talisman": (4, 0),
                "tall_grass": (3, 3), "field_chest": (2, 4),
                "mist_cave_entrance": (5, 4),
            },
            ambient={
                "没膝的草浪": (1, 1), "风干的兽骨": (3, 1), "半埋的朽木桩": (4, 2),
                "尖锐的断枝": (1, 3), "零星的碎石": (4, 4),
            },
            exits={"north": (0, 0), "west": (0, 2), "south": (2, 5)},
            pois=[
                GridPOI(id="plains_glint", cell=(4, 5),
                        hint="草叶间半埋着什么，反着一点微光",
                        payload={"kind": "loot",
                                 "items": [{"name": "磨尖的骨刺", "category": "tool",
                                            "equip_slot": "weapon", "damage_expr": "1d3",
                                            "damage_type": "pierce"}],
                                 "reveal": "拨开草——半截磨尖的兽骨，不知谁削的，够当把锥子使。"}),
            ],
        ),
    ))

    # ── 林边 / 树林（破局路三：闯林进守林员小屋取手斧）──────────────
    world.add_room(Room(
        id="forest_edge",
        name="雾语树林",
        base_description=(
            "草原西侧的树林，松木黑而密，针叶在脚下铺了厚厚一层，踩上去几乎没声。"
            "粗壮的树干随处可及，低处不少枯枝半垂着，风过时簌簌作响。"
            "雾在这里更重，能见度不足五步；林子里没有路，方向感很快被树干和雾吃掉，"
            "老话说进雾语林靠的不是地图，是运气。隐约地，深处有个方方正正的轮廓，像座被遗忘的小木屋。"
        ),
        exits={"east": "plains", "in": "forester_hut"},
        # 闯进深处的小屋需要一点运气——GM 让玩家掷一把（迷路/野兽/雾），
        # 过了再 gm_set_flag("forest_path_found", True, unlock_exit="in")。
        locked_exits={"in": "forest_path_found"},
        objects=["forest_trees", "dense_pines"],
        area="苍穹回廊·第一层",
        zone="雾语树林",
        coords=(-1, 1),
        tags=["forest", "risky", "floor_1", "misty", "spawn_ground"],
        enemies=["gale_wolf"],
        ambient=["半垂的枯枝:club", "厚厚的针叶层:foliage", "倒伏的朽木:furniture",
                 "松动的石块:rock", "缠人的藤蔓:foliage", "尖头的断木刺:blade"],
        # 5×5 密林：巨树在深处、密松在西、小屋入口(in)在东北深处、东口回草原。
        grid=RoomGrid(
            width=5, height=5, entry=(2, 2),
            objects={"dense_pines": (0, 2), "forest_trees": (2, 4)},
            ambient={
                "倒伏的朽木": (0, 0), "厚厚的针叶层": (2, 0),
                "松动的石块": (1, 1), "半垂的枯枝": (3, 1),
                "缠人的藤蔓": (1, 3), "尖头的断木刺": (3, 3),
            },
            exits={"in": (4, 0), "east": (4, 2)},
            pois=[
                GridPOI(id="forest_lurk", cell=(3, 2),
                        hint="前面有什么屏着气，土腥里掺了股兽臊，安静得不像风",
                        payload={"kind": "ambush", "enemies": ["gale_wolf"],
                                 "reveal": "树影炸开——一头疾风狼从伏窝里窜出，咬着寒气扑向你！"}),
            ],
        ),
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
        ambient=["积灰的旧工具:misc", "墙上的锈钉:blade", "劈好的柴火:club",
                 "塌了的吊床:foliage", "桌上的空酒瓶:bottle"],
        # 4×4 小屋：工具墙在西北、手斧插在劈柴墩旁、门(out)在西南角。
        grid=RoomGrid(
            width=4, height=4, entry=(1, 3),
            objects={"dusty_shelf": (0, 0), "chopping_block": (0, 2), "forester_hatchet": (1, 2)},
            ambient={
                "墙上的锈钉": (1, 0), "桌上的空酒瓶": (3, 0),
                "积灰的旧工具": (0, 1), "劈好的柴火": (3, 1), "塌了的吊床": (3, 2),
            },
            exits={"out": (0, 3)},
        ),
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
        tags=["dungeon", "trap", "floor_1", "labyrinth", "spawn_ground"],
        enemies=["gale_wolf", "shadow_lurker"],
        ambient=["碎裂的石砖:rock", "崩落的廊柱残段:club", "墙缝里的骨殖:misc",
                 "锈蚀的断剑:blade"],
        # 5×5 迷宫：四根廊柱(blocked)切出回路，符文门在北壁、宝箱在西南、南口回草原、北门叩首领。
        grid=RoomGrid(
            width=5, height=5, entry=(2, 3),
            blocked=[(1, 1), (3, 1), (1, 3), (3, 3)],
            objects={
                "rune_door": (2, 0), "trap_floor": (2, 2),
                "treasure_chest": (0, 4), "wall_glyph": (1, 4),
            },
            ambient={
                "碎裂的石砖": (1, 0), "墙缝里的骨殖": (3, 0),
                "崩落的廊柱残段": (0, 2), "锈蚀的断剑": (4, 2),
            },
            exits={"north": (0, 0), "south": (2, 4)},
            pois=[
                GridPOI(id="laby_tripwire", cell=(3, 2),
                        hint="半空里一根绷直的细线，齐踝高，几乎看不见",
                        payload={"kind": "trap", "save_attr": "dex", "dc": 12,
                                 "damage": "1d6", "damage_type": "pierce",
                                 "reveal": "你的小腿挂上那根细线——咔哒，墙缝激出一蓬淬黑的飞针！"}),
            ],
        ),
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
        ambient=["地上的碎石粉:rock", "崩落的石殿残块:rock", "前人遗落的断矛:blade"],
        # 5×5 圆殿：竞技场居中、回廊门在其北、南门回迷宫、北门(胜后解锁)上第二层。
        grid=RoomGrid(
            width=5, height=5, entry=(2, 3),
            objects={"corridor_gate": (2, 1), "warden_arena": (2, 2)},
            ambient={
                "崩落的石殿残块": (1, 1), "地上的碎石粉": (0, 2),
                "前人遗落的断矛": (4, 2),
            },
            exits={"north": (2, 0), "south": (2, 4)},
        ),
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
        ambient=["发光的菌簇:foliage", "散落的白骨:misc", "松动的钟乳石:rock",
                 "锋利的石笋碎片:blade"],
        zone="雾隐洞窟",
        coords=(1, 1),   # 草原东侧隐藏裂隙（与林边 -1,1 区分，避免地图叠格）
        tags=["hidden", "treasure", "floor_1"],
        # 4×4 洞窟：水晶/补给箱在西、石笋与白骨在东、裂隙出口(out)在西南。
        grid=RoomGrid(
            width=4, height=4, entry=(1, 3),
            objects={"cave_crystal": (1, 1), "cave_chest": (0, 2)},
            ambient={
                "发光的菌簇": (0, 0), "松动的钟乳石": (2, 0),
                "锋利的石笋碎片": (3, 1), "散落的白骨": (3, 2),
            },
            exits={"out": (0, 3)},
        ),
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
