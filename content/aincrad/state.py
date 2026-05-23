"""苍穹回廊：玩家初始状态（冷开局·赤贫）。"""
from core.types import (
    GameState, InventoryItem, ActorProfile, VitalStats, WorldTime, QuestEntry,
)


def build_initial_state():
    # ── 初始状态 ──────────────────────────────────────────────────
    return GameState(
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
                    "六点血、一双空拳、兜里一枚铜板都没有，谁都不欠你人情。"
                    "先想办法在这座小镇活下去。"
                ),
                deadline="",
                # 出路埋在世界里，让玩家自己摸——别在任务/叙事里替他点破（见 SKILL 冷开局铁律）。
                known_facts=[
                    "你 hp 上限只有 6、赤手空拳只有 1d1",
                    "这座小镇没人会无偿帮一个没名没钱的新人",
                ],
                unresolved=[],
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
