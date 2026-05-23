"""苍穹回廊：世界观锚句 + 数值规则书。"""
from core.types import WorldCanon, RuleBook


SPIRE_CANON = WorldCanon(
    setting_blurb=(
        "苍穹回廊：悬浮于云海之上的层状巨塔，逐层攻略向上。剑与少量魔法共存，"
        "日式异世界冒险风。死亡即真死（回廊烙印），只能上行。属性相克：炎/霜/雷/影。"
    ),
    forbidden=["现代科技", "枪械", "现代俚语", "汽车", "电子设备", "回到地面/逃离塔"],
    aesthetic_tags=["日式异世界", "浮空塔", "剑技", "热血战斗", "迷宫探索", "升级变强"],
    name_style="日式幻想风人名地名，可带欧式奇幻词根（界域、回廊、烙印、刻印）",
)


RULEBOOK = RuleBook(
    attributes={"str": "力量", "dex": "敏捷", "con": "体质", "int": "智力"},
    roles={"accuracy": "dex", "hp_growth": "con", "stamina_pool": "int"},
    equip_slots={"weapon": "主手", "armor": "护甲", "accessory": "饰品", "boots": "鞋"},
    level_curve="quadratic",
    unarmed_damage="1d1",   # 冷开局：赤手空拳，一拳只有 1d1——逼玩家破局找武器
)
