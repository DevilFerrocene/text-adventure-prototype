import unittest

import mcp_server


class HudFieldTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def test_start_game_returns_hud(self):
        r = mcp_server.start_game()
        self.assertIn("hud", r)
        # 关键数值在场
        self.assertIn("10/10", r["hud"])      # hp
        self.assertIn("50000", r["hud"])       # gold
        self.assertIn("破旧公寓", r["hud"])    # 位置

    def test_get_scene_returns_hud(self):
        r = mcp_server.get_scene()
        self.assertIn("hud", r)
        self.assertIn("📍", r["hud"])

    def test_get_state_returns_hud(self):
        r = mcp_server.get_state()
        self.assertIn("hud", r)

    def test_phase_and_weather_localized(self):
        # deep_night/heavy_rain → 中文
        hud = mcp_server.get_state()["hud"]
        self.assertIn("深夜", hud)
        self.assertIn("暴雨", hud)
        self.assertNotIn("deep_night", hud)
        self.assertNotIn("heavy_rain", hud)

    def test_hud_updates_after_move(self):
        before = mcp_server.get_state()["hud"]
        mcp_server.move("south")
        after = mcp_server.get_state()["hud"]
        self.assertNotEqual(before, after)   # 位置 + 时钟都变了
        self.assertIn("下层区巷子", after)

    def test_hud_reflects_quest_stage(self):
        hud = mcp_server.get_state()["hud"]
        self.assertIn("received_contract", hud)

    def test_hud_shows_active_buffs(self):
        mcp_server.add_improvised_buff(
            name="雨夜湿冷", desc="", polarity="debuff",
            target="roll", op="add", value=-2, duration=3, timing="on_check",
        )
        hud = mcp_server.get_state()["hud"]
        self.assertIn("雨夜湿冷", hud)

    def test_clock_advances_with_turns(self):
        # 00:00 → inspect 推进 5 分钟 → 00:05
        self.assertIn("00:00", mcp_server.get_state()["hud"])
        mcp_server.inspect_object("cracked_window")
        self.assertIn("00:05", mcp_server.get_state()["hud"])

    def test_stamina_shown_only_when_present(self):
        # 默认 max_stamina=0，不显示耐力
        self.assertNotIn("⚡", mcp_server.get_state()["hud"])
        mcp_server.SESSION.state.vitals.max_stamina = 5
        mcp_server.SESSION.state.vitals.stamina = 3
        self.assertIn("⚡ 3/5", mcp_server.get_state()["hud"])


class CombatHudTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        self.assertTrue(mcp_server.start_combat(canon=["dock_thug"])["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_encounter_has_combat_hud(self):
        enc = mcp_server.get_state()["encounter"]
        self.assertIn("combat_hud", enc)
        hud = enc["combat_hud"]
        self.assertIn("第 1 回合", hud)
        self.assertIn("你", hud)              # 玩家
        self.assertIn("码头打手", hud)        # 敌人
        self.assertIn("10/10", hud)           # 玩家血条
        self.assertIn("8/8", hud)             # 敌人血条

    def test_active_marker_on_current_actor(self):
        hud = mcp_server.get_state()["encounter"]["combat_hud"]
        # 玩家先手，行动标记 ▶ 在玩家行
        player_line = next(l for l in hud.splitlines() if "你" in l)
        self.assertIn("▶", player_line)

    def test_dead_combatant_shown_fallen(self):
        # 把敌人打死，HUD 显示"已倒下"
        mcp_server.SESSION.encounter.combatants["enemy_dock_thug"].hp = 0
        mcp_server.SESSION.encounter.combatants["enemy_dock_thug"].is_dead = True
        hud = mcp_server.get_state()["encounter"]["combat_hud"]
        self.assertIn("已倒下", hud)


if __name__ == "__main__":
    unittest.main()
