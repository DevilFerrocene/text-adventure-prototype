"""验收修复回归测试：捡到的装备可装备 / 消耗品可用 / 技能可查。"""
import unittest
from unittest.mock import patch

import mcp_server
from core.types import InventoryItem, GameObject


def _take(oid):
    """把场景物拿进背包（模拟 take_item 的核心：from_object 迁移）。"""
    obj = mcp_server.SESSION.world.get_object(oid)
    mcp_server.SESSION.state.inventory.append(InventoryItem.from_object(obj))
    return obj


class EquipFromSceneTest(unittest.TestCase):
    """问题3：场景里捡到的武器/护甲必须能装备（equip 数据要过 from_object 迁移）。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_from_object_carries_equip_fields(self):
        obj = mcp_server.SESSION.world.get_object("shop_steel_blade")
        inv = InventoryItem.from_object(obj)
        self.assertEqual(inv.equip_slot, "weapon")
        self.assertEqual(inv.damage_expr, "1d8")
        self.assertEqual(inv.scaling, {"str": 1.0, "dex": 1.0})

    def test_scene_weapon_can_be_equipped(self):
        _take("shop_steel_blade")
        r = mcp_server.equip("shop_steel_blade")
        self.assertTrue(r["ok"])
        self.assertEqual(r["slot"], "weapon")
        self.assertEqual(mcp_server.SESSION.state.equipped["weapon"], "shop_steel_blade")

    def test_scene_armor_can_be_equipped(self):
        _take("shop_leather_vest")
        r = mcp_server.equip("shop_leather_vest")
        self.assertTrue(r["ok"])
        self.assertEqual(r["slot"], "armor")

    def test_dagger_scales_dex_staff_mixes(self):
        # 匕首纯敏、辉石杖力+智混属性——结构化字段正确
        dagger = InventoryItem.from_object(mcp_server.SESSION.world.get_object("rack_dagger"))
        self.assertEqual(dagger.scaling, {"dex": 1.0})
        staff = InventoryItem.from_object(mcp_server.SESSION.world.get_object("cave_glow_staff"))
        self.assertEqual(staff.scaling, {"int": 1.0, "str": 0.5})

    def test_equipped_weapon_auto_used_in_attack(self):
        # 装备辉石杖后，declare_intent 不传 weapon= 也该用它（arcane 而非默认 blunt）
        _take("cave_glow_staff")
        mcp_server.equip("cave_glow_staff")
        mcp_server.SESSION.state.position = "warden_gate"
        mcp_server.call_affordance("warden_arena", "challenge")
        boss = mcp_server.SESSION.encounter.combatants["enemy_warden_gorehoof"]
        boss.hp = boss.max_hp = 300
        with patch("mcp_server.random.randint", return_value=15):
            r = mcp_server.declare_intent(actor="player", intent="attack",
                                          target="enemy_warden_gorehoof")
        hit = next((e for e in r["events"] if e["kind"] == "hit"), None)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["detail"]["damage_type"], "arcane")
        mcp_server.end_combat(reason="test")


class UseItemTest(unittest.TestCase):
    """问题2：消耗品可用，应用 use_effect 并消耗。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        # 冷开局起手无回复品、血上限 6；本组测消耗品机制，抬高上限 + 给一颗水晶
        st = mcp_server.SESSION.state
        st.vitals.max_hp = 20
        st.add_item(InventoryItem(
            id="heal_crystal", name="回复水晶", kind="consumable",
            use_effect={"heal": 12}))

    def test_heal_potion_restores_hp_and_consumes(self):
        st = mcp_server.SESSION.state
        st.vitals.hp = 8
        r = mcp_server.use_item("heal_crystal")
        self.assertTrue(r["ok"])
        self.assertEqual(r["effect"]["healed"], 12)
        self.assertEqual(st.vitals.hp, 20)
        self.assertFalse(st.has_item("heal_crystal"))  # 一次性消耗

    def test_heal_clamps_to_max(self):
        st = mcp_server.SESSION.state
        st.vitals.hp = 18  # 离满血只差 2
        r = mcp_server.use_item("heal_crystal")
        self.assertEqual(st.vitals.hp, 20)            # 钳到上限
        self.assertEqual(r["effect"]["healed"], 2)

    def test_scene_consumable_usable_after_pickup(self):
        # 洞穴回复水晶捡起后可用
        _take("cave_heal_crystal")
        mcp_server.SESSION.state.vitals.hp = 5
        r = mcp_server.use_item("cave_heal_crystal")
        self.assertTrue(r["ok"])
        self.assertGreater(mcp_server.SESSION.state.vitals.hp, 5)

    def test_non_consumable_rejected(self):
        _take("shop_steel_blade")  # 武器不是消耗品
        r = mcp_server.use_item("shop_steel_blade")
        self.assertFalse(r["ok"])
        self.assertIn("不是可使用", r["error"])

    def test_use_missing_item_rejected(self):
        r = mcp_server.use_item("no_such_item")
        self.assertFalse(r["ok"])


class InspectSkillTest(unittest.TestCase):
    """问题1：inspect_skill 返回技能完整效果，GM 不必翻源码。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_passive_skill_effect_visible(self):
        # 冷开局未自带 sword_mastery，但 inspect_skill 仍能查到它的定义
        mcp_server.learn_skill("sword_mastery")
        r = mcp_server.inspect_skill("sword_mastery")
        self.assertTrue(r["ok"])
        self.assertTrue(r["learned"])  # 习得后
        self.assertEqual(len(r["passive_modifiers"]), 1)
        pm = r["passive_modifiers"][0]
        self.assertEqual(pm["value"], 2)
        self.assertEqual(pm["target"], "roll")

    def test_active_skill_recipe_visible(self):
        r = mcp_server.inspect_skill("vertical_arc")  # 未掌握也能查模板
        self.assertTrue(r["ok"])
        self.assertFalse(r["learned"])
        self.assertEqual(r["active"]["cost"], {"stamina": 3})
        self.assertEqual(r["active"]["cooldown"], 2)
        self.assertTrue(len(r["active"]["recipe"]) >= 1)

    def test_reactive_skill_trigger_visible(self):
        r = mcp_server.inspect_skill("crisis_evasion")
        self.assertTrue(r["ok"])
        self.assertEqual(r["reactive"]["trigger"], "on_take_damage")

    def test_unknown_skill_rejected(self):
        r = mcp_server.inspect_skill("no_such_skill")
        self.assertFalse(r["ok"])


class CombatXpTest(unittest.TestCase):
    """战斗经验：canon + 即兴敌人都给经验；declare_intent 击杀顶层可见。"""

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_combatant_carries_archetype(self):
        # canon 与即兴敌人都该带 archetype（经验结算靠它）
        mcp_server.start_game("aincrad")
        mcp_server.SESSION.state.position = "plains"
        mcp_server.SESSION.state.active_spawns = ["frenzy_boar"]   # 打在场刷到的（过刷怪场防搓怪门）
        mcp_server.start_combat(canon=["frenzy_boar"])
        c = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        self.assertEqual(c.archetype, "brute_low")
        mcp_server.end_combat(reason="t")
        mcp_server.start_combat(improvised=[{"name": "迷雾怪", "archetype": "scout", "count": 1}])
        enemy = next(c for c in mcp_server.SESSION.encounter.combatants.values()
                     if c.side == "enemy")
        self.assertEqual(enemy.archetype, "scout")

    def test_canon_kill_grants_char_xp(self):
        mcp_server.start_game("aincrad")
        mcp_server.SESSION.state.position = "plains"
        mcp_server.SESSION.state.active_spawns = ["frenzy_boar"]   # 打在场刷到的（过刷怪场防搓怪门）
        mcp_server.start_combat(canon=["frenzy_boar"])
        mcp_server.deal_damage(target="enemy_frenzy_boar", amount=999)
        r = mcp_server.end_combat(reason="胜利")
        self.assertEqual(r["char_xp_gained"], 30)  # brute_low

    def test_improvised_kill_grants_char_xp(self):
        # 之前的 bug：即兴敌人永远 0 经验
        mcp_server.start_game("aincrad")
        mcp_server.SESSION.state.position = "plains"
        mcp_server.start_combat(improvised=[{"name": "迷雾怪", "archetype": "scout", "count": 1}])
        for c in mcp_server.SESSION.encounter.combatants.values():
            if c.side == "enemy":
                mcp_server.deal_damage(target=c.id, amount=999)
        r = mcp_server.end_combat(reason="胜利")
        self.assertEqual(r["char_xp_gained"], 40)  # scout

    def test_declare_intent_kill_surfaces_xp_at_top_level(self):
        # declare_intent 击杀最后一敌自动结束，char_xp 应在顶层（不必挖 end_combat_result）
        mcp_server.start_game("aincrad")
        mcp_server.SESSION.state.position = "plains"
        mcp_server.SESSION.state.active_spawns = ["frenzy_boar"]   # 打在场刷到的（过刷怪场防搓怪门）
        mcp_server.start_combat(canon=["frenzy_boar"])
        mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"].hp = 2
        with patch("mcp_server.random.randint", return_value=18):
            r = mcp_server.declare_intent(actor="player", intent="attack",
                                          target="enemy_frenzy_boar")
        self.assertIsNone(r["next_actor"])         # 战斗已结束
        self.assertEqual(r["char_xp_gained"], 30)  # 顶层可见

    def test_flee_grants_no_xp(self):
        # 没杀敌就结束 → 0 经验是对的
        mcp_server.start_game("aincrad")
        mcp_server.SESSION.state.position = "plains"
        mcp_server.SESSION.state.active_spawns = ["frenzy_boar"]   # 打在场刷到的（过刷怪场防搓怪门）
        mcp_server.start_combat(canon=["frenzy_boar"])
        r = mcp_server.end_combat(reason="逃跑")
        self.assertEqual(r["char_xp_gained"], 0)


if __name__ == "__main__":
    unittest.main()
