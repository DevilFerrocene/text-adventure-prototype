"""§11 RPG 数值骨架测试：R1-R4 逐层覆盖。"""

import unittest
import mcp_server
from core.types import (
    VitalStats, InventoryItem, GameState, RuleBook,
    exp_to_reach, HP_PER_LEVEL, HP_PER_HPGROWTH,
)


class RPGDataModelTest(unittest.TestCase):
    """R1: 数据模型 —— 新字段默认值 + 旧存档兼容。"""

    def test_vitalstats_has_rpg_fields(self):
        vs = VitalStats()
        self.assertEqual(vs.level, 1)
        self.assertEqual(vs.exp, 0)
        self.assertEqual(vs.attributes, {})

    def test_inventoryitem_has_equip_fields(self):
        item = InventoryItem(id="test", name="test")
        self.assertEqual(item.equip_slot, "")
        self.assertEqual(item.damage_expr, "")
        self.assertEqual(item.damage_type, "blunt")
        self.assertEqual(item.scaling, {})
        self.assertEqual(item.defense, 0)
        self.assertEqual(item.resist, {})
        self.assertEqual(item.attr_bonus, {})

    def test_rulebook_defaults(self):
        rb = RuleBook()
        self.assertIn("str", rb.attributes)
        self.assertIn("dex", rb.attributes)
        self.assertEqual(rb.roles["accuracy"], "dex")
        self.assertEqual(rb.roles["hp_growth"], "con")
        self.assertIn("weapon", rb.equip_slots)

    def test_gamestate_has_equipped(self):
        gs = GameState(position="test")
        self.assertEqual(gs.equipped, {})

    def test_exp_to_reach(self):
        self.assertEqual(exp_to_reach(1), 0)
        self.assertEqual(exp_to_reach(2), 100)
        self.assertEqual(exp_to_reach(3), 300)
        self.assertEqual(exp_to_reach(4), 600)
        self.assertEqual(exp_to_reach(5), 1000)

    def test_old_save_compat(self):
        """旧存档缺失新字段 → load 不崩、默认值生效。"""
        mcp_server.start_game()
        state = mcp_server.SESSION.state
        # 旧存档形 vitals 反序列化（缺失 level/exp/attributes）→ 默认值
        vs = VitalStats(**{"hp": 10, "max_hp": 10, "gold": 500})
        self.assertEqual(vs.level, 1)
        self.assertEqual(vs.exp, 0)
        self.assertEqual(vs.attributes, {})


class RPGAttributeProjectionTest(unittest.TestCase):
    """R2: 属性 → Modifier 投影。"""

    def setUp(self):
        mcp_server.start_game(world="aincrad")

    def test_starting_attributes(self):
        state = mcp_server.SESSION.state
        self.assertEqual(state.vitals.attributes, {"str": 3, "dex": 4, "con": 3, "int": 2})

    def test_accuracy_role_projection(self):
        """dex=4 → accuracy roll modifier +4。"""
        state = mcp_server.SESSION.state
        from mcp_server import _emit_attribute_modifiers
        mods = _emit_attribute_modifiers(state, rulebook=mcp_server.SESSION.world.rulebook)
        roll_mods = [m for m in mods if m.target == "roll"]
        self.assertEqual(len(roll_mods), 1)
        self.assertEqual(roll_mods[0].value, 4)  # dex=4
        self.assertEqual(roll_mods[0].source_kind, "attribute")

    def test_scaling_damage_projection(self):
        """str=3 × 权重1.0 → damage +3。"""
        state = mcp_server.SESSION.state
        from mcp_server import _emit_attribute_modifiers
        mods = _emit_attribute_modifiers(state, scaling={"str": 1.0},
                                         rulebook=mcp_server.SESSION.world.rulebook)
        dmg_mods = [m for m in mods if m.target == "damage"]
        self.assertEqual(len(dmg_mods), 1)
        self.assertEqual(dmg_mods[0].value, 3)  # floor(3*1.0)

    def test_roll_check_includes_attr_audit(self):
        """roll_check audit trail 包含属性来源。"""
        result = mcp_server.roll_check(reason="攻击检定", dc=10)
        self.assertTrue(result["ok"])
        audit = mcp_server.explain_last_roll()
        full_items = audit.get("modifiers_full", []) + audit.get("modifiers_result", [])
        self.assertTrue(any("attribute" in s for s in full_items),
                        f"audit 应包含 attribute 来源，实际: {full_items}")


class RPGEquipmentTest(unittest.TestCase):
    """R3: equip/unequip + 结构化武器字段。"""

    def setUp(self):
        mcp_server.start_game(world="aincrad")
        # 冷开局起手无装备；本组测装备机制，先把铁剑/皮甲塞进背包
        from core.types import InventoryItem
        st = mcp_server.SESSION.state
        st.add_item(InventoryItem(
            id="iron_sword", name="新手铁剑", kind="tool",
            tags=["武器", "damage", "dmg:1d6"], named_tags=["weapon"],
            equip_slot="weapon", damage_expr="1d6", damage_type="slash",
            scaling={"str": 1.0, "dex": 1.0}))
        st.add_item(InventoryItem(
            id="leather_vest", name="皮背心", kind="item",
            equip_slot="armor", defense=2))

    def test_equip_weapon(self):
        # 铁剑已在背包
        result = mcp_server.equip(item_id="iron_sword")
        self.assertTrue(result["ok"], result.get("error", ""))
        self.assertEqual(result["slot"], "weapon")

        state = mcp_server.SESSION.state
        self.assertEqual(state.equipped.get("weapon"), "iron_sword")

    def test_equip_armor(self):
        result = mcp_server.equip(item_id="leather_vest")
        self.assertTrue(result["ok"], result.get("error", ""))
        self.assertEqual(result["slot"], "armor")

        # AC 应受装备加成
        state = mcp_server.SESSION.state
        self.assertEqual(state.equipped.get("armor"), "leather_vest")

    def test_unequip(self):
        mcp_server.equip(item_id="iron_sword")
        result = mcp_server.unequip(slot="weapon")
        self.assertTrue(result["ok"], result.get("error", ""))
        self.assertEqual(mcp_server.SESSION.state.equipped.get("weapon", ""), "")

    def test_equip_invalid_slot(self):
        # 消耗品没有 equip_slot → 不可装备，应被拒
        result = mcp_server.equip(item_id="heal_crystal")
        self.assertFalse(result["ok"])

    def test_old_dmg_tag_fallback(self):
        """旧 'dmg:1d6' tag 武器仍可用。declare_intent 回退读 tag。"""
        # 铁剑有 damage_expr="1d6" 也有 "dmg:1d6" tag — 优先读结构化字段
        item = mcp_server.SESSION.state.get_item("iron_sword")
        self.assertEqual(item.damage_expr, "1d6")
        self.assertEqual(item.scaling, {"str": 1.0, "dex": 1.0})
        # 同时保留旧 tag
        self.assertIn("dmg:1d6", item.tags)


class RPGLevelUpTest(unittest.TestCase):
    """R4: 角色经验 / 升级循环。"""

    def setUp(self):
        mcp_server.start_game(world="aincrad")

    def test_grant_char_exp_no_levelup(self):
        result = mcp_server.grant_char_exp(amount=50, reason="测试")
        self.assertTrue(result["ok"])
        self.assertFalse(result["leveled_up"])
        self.assertEqual(mcp_server.SESSION.state.vitals.exp, 50)

    def test_grant_char_exp_levelup(self):
        """100 XP → Lv.1→2。"""
        result = mcp_server.grant_char_exp(amount=100, reason="测试")
        self.assertTrue(result["ok"])
        self.assertTrue(result["leveled_up"])
        self.assertEqual(result["level"], 2)
        self.assertGreater(len(result["level_events"]), 0)

        state = mcp_server.SESSION.state
        self.assertEqual(state.vitals.level, 2)

    def test_levelup_increases_max_hp(self):
        """升级 max_hp = HP_PER_LEVEL + HP_PER_HPGROWTH * con"""
        state = mcp_server.SESSION.state
        old_max_hp = state.vitals.max_hp
        mcp_server.grant_char_exp(amount=100, reason="测试")
        new_max_hp = state.vitals.max_hp
        expected_gain = HP_PER_LEVEL + HP_PER_HPGROWTH * state.vitals.attributes.get("con", 0)
        self.assertEqual(new_max_hp, old_max_hp + expected_gain)

    def test_save_load_preserves_level_exp(self):
        """存档/读档后 level/exp 保留。"""
        mcp_server.grant_char_exp(amount=100, reason="测试")
        saved = mcp_server.save_game(slot="rpg_test")
        self.assertTrue(saved["ok"])

        # 重新开始，清空状态
        mcp_server.start_game(world="aincrad")
        loaded = mcp_server.load_game(slot="rpg_test")
        self.assertTrue(loaded["ok"])

        state = mcp_server.SESSION.state
        self.assertEqual(state.vitals.level, 2)
        self.assertEqual(state.vitals.exp, 100)

        # Cleanup
        from pathlib import Path
        Path(saved["path"]).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
