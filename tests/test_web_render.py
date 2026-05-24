"""Web 富 UI：从工具结果抽结构面板 + 散文模式提示词。"""
import json
import unittest

import mcp_server
from standalone.web import _render_events, hud_payload, panels_payload
from standalone.prompt import load_system_prompt


class RenderEventsTest(unittest.TestCase):
    def test_scene_extracted_excludes_locked_exits(self):
        result = {"scene": {
            "objects": [{"name": "武器架"}, {"name": "篝火"}],
            "exits": {"north": {"target": "plains", "locked": False},
                      "in": {"target": "hut", "locked": True}}}}
        d = dict(_render_events("get_scene", result))
        self.assertEqual(d["scene"]["objects"], ["武器架", "篝火"])
        self.assertEqual(d["scene"]["exits"], ["north"])   # 锁住的 in 排除

    def test_dice_extracted(self):
        d = dict(_render_events("explain_last_roll",
                                {"line_format": "📊 测试 d20=19 +4 = 23", "outcome": "success"}))
        self.assertIn("dice", d)
        self.assertEqual(d["dice"]["outcome"], "success")
        self.assertIn("d20=19", d["dice"]["line"])

    def test_combat_extracted(self):
        result = {"encounter": {
            "active": True, "round": 2, "active_combatant": "player",
            "combatants": [
                {"id": "player", "name": "你", "hp": 6, "max_hp": 6,
                 "side": "player", "is_dead": False},
                {"id": "enemy_killer_rabbit", "name": "杀人兔", "hp": 3, "max_hp": 8,
                 "side": "enemy", "is_dead": False}]}}
        d = dict(_render_events("declare_intent", result))
        self.assertEqual(d["combat"]["round"], 2)
        self.assertEqual(d["combat"]["active"], "player")
        self.assertEqual(len(d["combat"]["combatants"]), 2)

    def test_inactive_encounter_no_combat_card(self):
        d = dict(_render_events("get_state", {"encounter": {"active": False}}))
        self.assertNotIn("combat", d)

    def test_non_dict_result_safe(self):
        self.assertEqual(_render_events("x", "not a dict"), [])
        self.assertEqual(_render_events("x", None), [])

    def test_plain_result_yields_nothing(self):
        self.assertEqual(_render_events("learn_skill", {"ok": True, "learned": {}}), [])

    def test_combat_log_shows_roll_and_damage(self):
        result = {"events": [
            {"kind": "attack", "actor": "player", "target": "enemy_x",
             "detail": {"line": "📊 你 攻击 杀人兔 d20=15 +4 = 19 vs DC10 → success",
                        "target_name": "杀人兔"}},
            {"kind": "hit", "actor": "player", "target": "enemy_x",
             "detail": {"damage": 3, "damage_raw": 3, "resist": 1.0,
                        "target_hp": "5/8", "target_name": "杀人兔"}},
            {"kind": "kill", "target": "enemy_x", "detail": {"target_name": "杀人兔"}},
        ]}
        d = dict(_render_events("declare_intent", result))
        lines = d["combat_log"]["lines"]
        self.assertTrue(any("d20=15" in l for l in lines))           # 明骰掷骰可见
        self.assertTrue(any("伤害" in l and "杀人兔" in l for l in lines))  # 伤害+目标名
        self.assertTrue(any("倒下" in l for l in lines))

    def test_combat_log_shows_resist_process(self):
        result = {"events": [
            {"kind": "hit", "actor": "p", "target": "e",
             "detail": {"damage": 6, "damage_raw": 4, "resist": 1.5,
                        "target_hp": "4/10", "target_name": "怪"}}]}
        lines = dict(_render_events("declare_intent", result))["combat_log"]["lines"]
        self.assertTrue(any("4×1.5=6" in l for l in lines))          # 抗性结算过程显出

    def test_combat_log_only_for_declare_intent(self):
        # end_combat 等也带 events，但不该把整段日志再刷一遍
        result = {"events": [{"kind": "kill", "target": "e", "detail": {"target_name": "怪"}}]}
        self.assertNotIn("combat_log", dict(_render_events("end_combat", result)))


class EnemiesCardTest(unittest.TestCase):
    """F2：刷出/在场的敌人（未开战）渲染成"敌在场"卡。"""

    def test_enemy_profiles_become_enemies_card(self):
        mcp_server.start_game("aincrad")          # encounter=None
        result = {"enemy_profiles": [
            {"name": "杀人兔", "hp": 8, "max_hp": 8, "damage_expr": "1d4"}]}
        out = dict(_render_events("move", result))
        self.assertIn("enemies", out)
        self.assertEqual(out["enemies"]["list"][0]["name"], "杀人兔")

    def test_no_enemies_card_during_combat(self):
        # 开战后由 combat 面板接管，不再出"敌在场"卡（避免重复）
        mcp_server.start_game("aincrad")
        mcp_server.start_combat(canon=["killer_rabbit"])
        result = {"enemy_profiles": [{"name": "杀人兔", "hp": 8, "max_hp": 8}]}
        out = dict(_render_events("get_scene", result))
        self.assertNotIn("enemies", out)
        mcp_server.end_combat(reason="test")


class HudCombatHpTest(unittest.TestCase):
    """F4：战斗中 HUD 血量跟 Combatant 走，不显示过期的 vitals。"""

    def test_hud_uses_combatant_hp_in_combat(self):
        mcp_server.start_game("aincrad")
        mcp_server.SESSION.state.vitals.hp = 6        # vitals 满
        mcp_server.start_combat(canon=["killer_rabbit"])
        mcp_server.SESSION.encounter.combatants["player"].hp = 3  # 战斗中掉到 3
        hud = hud_payload()
        self.assertEqual(hud["vitals"]["hp"], 3)      # HUD 跟战斗走，不是过期的 6
        self.assertTrue(hud["in_combat"])
        mcp_server.end_combat(reason="test")

    def test_hud_uses_vitals_outside_combat(self):
        mcp_server.start_game("aincrad")
        mcp_server.SESSION.state.vitals.hp = 5
        hud = hud_payload()
        self.assertEqual(hud["vitals"]["hp"], 5)
        self.assertFalse(hud["in_combat"])


class PanelsPayloadTest(unittest.TestCase):
    """侧栏面板数据：背包/技能/任务/地图。"""

    def setUp(self):
        mcp_server.start_game("aincrad")

    def test_all_sections_present(self):
        p = panels_payload()
        self.assertTrue(p["started"])
        for k in ("inventory", "skills", "quests", "map"):
            self.assertIn(k, p)
        self.assertIsInstance(p["inventory"], list)   # 冷开局空背包
        self.assertGreaterEqual(len(p["quests"]), 1)  # 开场任务「破局」在

    def test_map_current_room_and_floor_scope(self):
        p = panels_payload()
        rooms = p["map"]["rooms"]
        cur = [r for r in rooms if r["current"]]
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0]["id"], "camp")          # 开局在营地
        ids = {r["id"] for r in rooms}
        self.assertIn("plains", ids)
        self.assertIn("warden_gate", ids)
        self.assertNotIn("floor_2_gate", ids)           # 第二层(不同 area)不入第一层图
        # 坐标无冲突——地图不叠格（mist_cave 已挪开）
        coords = [(r["x"], r["y"]) for r in rooms]
        self.assertEqual(len(coords), len(set(coords)))

    def test_inventory_and_skill_surface_after_acquire(self):
        mcp_server.add_improvised([{"id": "imp_stick", "name": "木棍",
                                    "category": "tool", "equip_slot": "weapon",
                                    "damage_expr": "1d4"}])
        mcp_server.learn_skill("keen_senses")
        p = panels_payload()
        inv_names = [i["name"] for i in p["inventory"]]
        self.assertIn("木棍", inv_names)
        stick = next(i for i in p["inventory"] if i["name"] == "木棍")
        self.assertTrue(any("武器" in c for c in stick["capabilities"]))
        skill_ids = [s["id"] for s in p["skills"]]
        self.assertIn("keen_senses", skill_ids)


class SessionPersistenceTest(unittest.TestCase):
    """会话持久化：对话存/取、叙事流抽取、命名快照列表。"""

    def setUp(self):
        import standalone.web as web
        self.web = web
        mcp_server.start_game("aincrad")
        web._agent = None                      # 强制重建一个干净 agent
        a = web._get_agent()
        a.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "（行动）我往北走"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c", "type": "function",
                             "function": {"name": "move", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c", "content": "{}"},
            {"role": "assistant", "content": "你走进草原，雾气漫过脚踝。"},
        ]
        self._slots = []

    def tearDown(self):
        for slot in self._slots:
            for p in (mcp_server.SAVE_DIR / f"{slot}.json", self.web._session_path(slot)):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    def test_transcript_extracts_player_and_gm_only(self):
        # 只抽 玩家输入(去模式前缀) + GM 散文；跳过工具调用/工具结果
        tr = self.web._transcript(self.web._get_agent().messages)
        self.assertEqual(tr, [{"role": "player", "text": "我往北走"},
                              {"role": "gm", "text": "你走进草原，雾气漫过脚踝。"}])

    def test_save_load_conversation_roundtrip(self):
        slot = "sess_ut_roundtrip"; self._slots.append(slot)
        self.web._save_conversation(slot, "测试")
        self.web._get_agent().messages = [{"role": "system", "content": "x"}]   # 抹掉内存
        self.assertTrue(self.web._load_conversation(slot))
        self.assertEqual(self.web._get_agent().messages[-1]["content"], "你走进草原，雾气漫过脚踝。")

    def test_named_save_appears_in_list(self):
        slot = "sess_ut_listed"; self._slots.append(slot)
        mcp_server.save_game(slot)
        self.web._save_conversation(slot, "列表测试")
        data = json.loads(self.web.session_list().body)
        entry = next((s for s in data["sessions"] if s["id"] == slot), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["title"], "列表测试")


class PromptModeTest(unittest.TestCase):
    def test_rich_ui_uses_prose_block(self):
        # 富 UI：前台格式整章换成散文版（面板交界面渲染），且无自相矛盾的"覆盖否定"
        p = load_system_prompt(rich_ui=True)
        self.assertIn("只写叙事散文", p)
        self.assertIn("界面自动渲染", p)
        self.assertIn("绝不列表", p)             # F1：明令禁止罗列物件/出口清单
        self.assertNotIn("一律作废", p)          # 不再"全量塞 + 末尾否定"
        self.assertNotIn("富 UI 覆盖", p)

    def test_default_uses_paste_block(self):
        # 纯文本前端：保留粘贴版（GM 自己贴 HUD/骰子/场景），不混进散文版
        p = load_system_prompt(rich_ui=False)
        self.assertIn("直接原样贴出来", p)        # 粘贴版独有
        self.assertNotIn("界面自动渲染", p)        # 散文版不该出现
        self.assertNotIn("一律作废", p)

    def test_no_raw_markers_or_frontmatter_leak(self):
        # 二选一的切分标记 + skill frontmatter 都不该漏进最终提示词
        for rich in (True, False):
            p = load_system_prompt(rich_ui=rich)
            self.assertNotIn("FRONTEND:PASTE", p)   # HTML 切分标记被剥
            self.assertNotIn("name: play", p)        # 宿主用的 frontmatter 被剥
            self.assertNotIn("----- SKILL", p)       # 文档套文档的拼接缝已去

    def test_rich_ui_has_no_residual_paste_commands(self):
        # 散文版下，正文里不该再残留"叫 GM 贴面板"的指令（曾散落在战斗/战术段，和散文版矛盾）
        p = load_system_prompt(rich_ui=True)
        for leak in ("直接贴给玩家", "贴出最新 `combat_hud`", "贴 HUD"):
            self.assertNotIn(leak, p)


if __name__ == "__main__":
    unittest.main()
