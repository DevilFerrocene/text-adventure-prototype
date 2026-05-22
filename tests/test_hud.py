import unittest

import mcp_server


class HudFieldTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def test_start_game_returns_hud(self):
        r = mcp_server.start_game()
        self.assertIn("hud", r)
        # 关键数值在场（aincrad 起始）
        self.assertIn("20/20", r["hud"])      # hp
        self.assertIn("500", r["hud"])        # gold
        self.assertIn("营地", r["hud"])        # 位置

    def test_get_scene_returns_hud(self):
        r = mcp_server.get_scene()
        self.assertIn("hud", r)
        self.assertIn("📍", r["hud"])

    def test_get_state_returns_hud(self):
        r = mcp_server.get_state()
        self.assertIn("hud", r)

    def test_phase_and_weather_localized(self):
        # noon/clear → 中文，原始英文 key 不外泄
        hud = mcp_server.get_state()["hud"]
        self.assertIn("正午", hud)
        self.assertIn("晴", hud)
        self.assertNotIn("noon", hud)
        self.assertNotIn("clear", hud)

    def test_hud_updates_after_move(self):
        before = mcp_server.get_state()["hud"]
        mcp_server.move("north")   # 营地 → 雾语草原
        after = mcp_server.get_state()["hud"]
        self.assertNotEqual(before, after)   # 位置 + 时钟都变了
        self.assertIn("雾语草原", after)

    def test_hud_reflects_quest_stage(self):
        hud = mcp_server.get_state()["hud"]
        self.assertIn("entered_floor_1", hud)

    def test_hud_shows_active_buffs(self):
        mcp_server.add_improvised_buff(
            name="雾寒侵体", desc="", polarity="debuff",
            target="roll", op="add", value=-2, duration=3, timing="on_check",
        )
        hud = mcp_server.get_state()["hud"]
        self.assertIn("雾寒侵体", hud)

    def test_clock_advances_with_turns(self):
        # 00:00 → inspect 推进 5 分钟 → 00:05
        self.assertIn("00:00", mcp_server.get_state()["hud"])
        mcp_server.inspect_object("teleport_crystal")
        self.assertIn("00:05", mcp_server.get_state()["hud"])

    def test_stamina_shown_when_present(self):
        # aincrad 默认有 SP（max_stamina=10）→ ⚡ 显示
        self.assertIn("⚡ 10/10", mcp_server.get_state()["hud"])
        # 归零后不再显示
        mcp_server.SESSION.state.vitals.max_stamina = 0
        mcp_server.SESSION.state.vitals.stamina = 0
        self.assertNotIn("⚡", mcp_server.get_state()["hud"])


class CombatHudTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        self.assertTrue(mcp_server.start_combat(canon=["frenzy_boar"])["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_encounter_has_combat_hud(self):
        enc = mcp_server.get_state()["encounter"]
        self.assertIn("combat_hud", enc)
        hud = enc["combat_hud"]
        self.assertIn("第 1 回合", hud)
        self.assertIn("你", hud)              # 玩家
        self.assertIn("狂奔野猪", hud)        # 敌人
        self.assertIn("20/20", hud)           # 玩家血条
        self.assertIn("9/9", hud)             # 敌人血条

    def test_active_marker_on_current_actor(self):
        hud = mcp_server.get_state()["encounter"]["combat_hud"]
        # 玩家先手，行动标记 ▶ 在玩家行
        player_line = next(l for l in hud.splitlines() if "你" in l)
        self.assertIn("▶", player_line)

    def test_dead_combatant_shown_fallen(self):
        # 把敌人打死，HUD 显示"已倒下"
        mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"].hp = 0
        mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"].is_dead = True
        hud = mcp_server.get_state()["encounter"]["combat_hud"]
        self.assertIn("已倒下", hud)


if __name__ == "__main__":
    unittest.main()
