"""苍穹回廊：怪物表。"""
from core.types import EnemyTemplate


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
        spawn_weight=4.0,   # 草原"教学怪"：刷怪占大头，让新手大概率先遇到它而非更硬的狼/猪
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
