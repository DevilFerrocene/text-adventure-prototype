"""自动存档 + 启动自恢复：根治"玩到一半进程重启、内存 SESSION 丢失"。"""
import json
import unittest

import mcp_server
from mcp_server import SAVE_DIR, AUTOSAVE_SLOT


def _autosave_path():
    return SAVE_DIR / f"{AUTOSAVE_SLOT}.json"


def _clear_autosave():
    p = _autosave_path()
    if p.exists():
        p.unlink()


def _simulate_process_restart():
    """模拟进程重启：清空内存 SESSION，再触发自恢复（如真实启动那样）。"""
    mcp_server.SESSION = mcp_server.Session()  # 空白单例，等价于新进程
    return mcp_server._maybe_restore_autosave()


class AutosaveWriteTest(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        _clear_autosave()

    def test_start_game_writes_autosave(self):
        self.assertTrue(_autosave_path().exists())
        data = json.loads(_autosave_path().read_text(encoding="utf-8"))
        self.assertEqual(data["world"], "aincrad")
        self.assertEqual(data["position"], "camp")

    def test_move_updates_autosave(self):
        mcp_server.move("north")  # camp → plains
        data = json.loads(_autosave_path().read_text(encoding="utf-8"))
        self.assertEqual(data["position"], "plains")

    def test_autosave_captures_skills_and_flags(self):
        # 开局自带技能 + 学新技能 + 置 flag 都该落盘
        mcp_server.SESSION.state.position = "labyrinth"
        mcp_server.call_affordance("treasure_chest", "open")  # learn vertical_arc + flag
        data = json.loads(_autosave_path().read_text(encoding="utf-8"))
        skill_ids = {s["id"] for s in data["skills"]}
        self.assertIn("vertical_arc", skill_ids)   # 宝箱习得的剑技已落盘
        self.assertTrue(data["flags"].get("got_skill_book"))


class RestoreTest(unittest.TestCase):
    def setUp(self):
        _clear_autosave()

    def tearDown(self):
        _clear_autosave()

    def test_restore_after_simulated_restart(self):
        # 玩到一半
        mcp_server.start_game("aincrad")
        mcp_server.move("north")            # plains
        mcp_server.SESSION.state.vitals.hp = 13
        mcp_server._autosave()  # 直接改 vitals 不经工具，手动落盘一次
        # 进程重启
        restored = _simulate_process_restart()
        self.assertTrue(restored)
        self.assertTrue(mcp_server.SESSION.started)
        # 位置/世界/hp 都还在
        self.assertEqual(mcp_server.SESSION.world_name, "aincrad")
        self.assertEqual(mcp_server.SESSION.state.position, "plains")
        self.assertEqual(mcp_server.SESSION.state.vitals.hp, 13)

    def test_restored_skills_still_work(self):
        mcp_server.start_game("aincrad")
        mcp_server.learn_skill("sword_mastery")  # 习得一技 → 触发 autosave
        mcp_server.learn_skill("crisis_evasion")
        _simulate_process_restart()
        ids = {s.id for s in mcp_server.SESSION.state.skills}
        self.assertIn("sword_mastery", ids)
        self.assertIn("crisis_evasion", ids)

    def test_require_started_recovers_via_autosave(self):
        # 模拟玩家玩到一半，进程重启，然后 GM 直接调一个需要 started 的工具
        mcp_server.start_game("aincrad")
        mcp_server.move("north")
        mcp_server.SESSION = mcp_server.Session()  # 内存丢失，但不主动恢复
        # get_scene 内部 _require_started 应自动从 autosave 恢复，而不是报错
        r = mcp_server.get_scene()
        self.assertTrue(r["ok"])
        self.assertEqual(mcp_server.SESSION.state.position, "plains")

    def test_no_autosave_gives_clear_guidance(self):
        _clear_autosave()
        mcp_server.SESSION = mcp_server.Session()  # 全空，无档可恢复
        r = mcp_server.get_scene()
        self.assertFalse(r["ok"])
        self.assertIn("load_game", r["error"])  # 指引去恢复/新开
        self.assertIn("start_game", r["error"])

    def test_new_game_overwrites_old_autosave(self):
        # 玩到草原 → 重新开局 → autosave 应是新局(camp)而非旧进度(plains)
        mcp_server.start_game("aincrad")
        mcp_server.move("north")  # plains
        data = json.loads(_autosave_path().read_text(encoding="utf-8"))
        self.assertEqual(data["position"], "plains")
        mcp_server.start_game("aincrad")  # 重开新局
        data2 = json.loads(_autosave_path().read_text(encoding="utf-8"))
        self.assertEqual(data2["world"], "aincrad")
        self.assertEqual(data2["position"], "camp")
        # 重启后恢复到新局起点
        _simulate_process_restart()
        self.assertEqual(mcp_server.SESSION.world_name, "aincrad")
        self.assertEqual(mcp_server.SESSION.state.position, "camp")


class ResetGameTest(unittest.TestCase):
    """reset_game：清自动存档 + 开新局，手动存档保留。"""

    def tearDown(self):
        _clear_autosave()
        for slot in ("reset_keep",):
            p = SAVE_DIR / f"{slot}.json"
            if p.exists():
                p.unlink()

    def test_reset_starts_fresh_same_world(self):
        mcp_server.start_game("aincrad")
        mcp_server.move("north")
        mcp_server.SESSION.state.vitals.hp = 3
        r = mcp_server.reset_game()
        self.assertTrue(r["ok"])
        self.assertTrue(r["reset"])
        self.assertEqual(mcp_server.SESSION.world_name, "aincrad")  # 沿用当前世界
        self.assertEqual(mcp_server.SESSION.state.position, "camp")  # 回到起点
        self.assertEqual(mcp_server.SESSION.state.vitals.hp, 6)      # 冷开局满血=6

    def test_reset_keeps_manual_saves(self):
        mcp_server.start_game("aincrad")
        mcp_server.save_game("reset_keep")
        mcp_server.reset_game()
        # 手动存档仍可读回
        loaded = mcp_server.load_game("reset_keep")
        self.assertTrue(loaded["ok"])

    def test_reset_clears_autosave_no_stale_restore(self):
        mcp_server.start_game("aincrad")
        mcp_server.move("north")  # plains
        mcp_server.reset_game()
        # reset 后 autosave 是新局(camp)，模拟重启不会回到 plains
        _simulate_process_restart()
        self.assertEqual(mcp_server.SESSION.state.position, "camp")

    def test_reset_to_specified_world(self):
        mcp_server.start_game("aincrad")
        r = mcp_server.reset_game("aincrad")   # 显式指定世界的路径仍生效
        self.assertTrue(r["ok"])
        self.assertEqual(mcp_server.SESSION.world_name, "aincrad")

    def test_reset_invalid_world_rejected(self):
        mcp_server.start_game("aincrad")
        r = mcp_server.reset_game("nonexistent")
        self.assertFalse(r["ok"])


class CombatPersistenceTest(unittest.TestCase):
    """进行中的战斗（encounter）也要进自动存档——否则中途重载会丢战斗、血量还会"穿越"回开打前。"""

    def setUp(self):
        _clear_autosave()
        mcp_server.start_game("aincrad")
        st = mcp_server.SESSION.state
        st.vitals.hp = st.vitals.max_hp = 20   # 撑住别被一击秒，专测持久化

    def tearDown(self):
        _clear_autosave()

    def test_start_combat_writes_encounter_to_autosave(self):
        mcp_server.start_combat(canon=["killer_rabbit"])
        data = json.loads(_autosave_path().read_text(encoding="utf-8"))
        self.assertIsNotNone(data.get("encounter"))
        self.assertIn("player", data["encounter"]["combatants"])

    def test_restart_mid_combat_resumes_encounter(self):
        mcp_server.start_combat(canon=["killer_rabbit"])
        enc = mcp_server.SESSION.encounter
        enc.combatants["player"].hp = 7            # 战斗中受了伤
        enc.round = 3
        rid = next(cid for cid in enc.combatants if cid != "player")
        enc.combatants[rid].hp = 2
        mcp_server._autosave()                     # 落盘（模拟战斗行动后）
        self.assertTrue(_simulate_process_restart())
        renc = mcp_server.SESSION.encounter
        self.assertIsNotNone(renc, "重启后应仍在战斗中")
        self.assertTrue(mcp_server.SESSION.in_combat)
        self.assertEqual(renc.combatants["player"].hp, 7)   # 伤势保留，没"穿越"回 20
        self.assertEqual(renc.combatants[rid].hp, 2)        # 敌人血量也保留
        self.assertEqual(renc.round, 3)

    def test_grid_combat_preserves_combatant_cells(self):
        # 棋盘战斗：敌人就位 enemy_field 后开战，combatant.cell 须随存档往返
        # （草原是刷怪场，打在场的怪走 request_combat，不能 start_combat 点名）
        st = mcp_server.SESSION.state
        st.position = "plains"
        st.cell = (2, 3)
        st.active_spawns = ["killer_rabbit"]
        st.enemy_field = [{"uid": "killer_rabbit", "enemy_id": "killer_rabbit",
                           "cell": [4, 3], "sight": 2, "aggro": 1, "state": "hostile"}]
        r = mcp_server.request_combat("被发现")
        self.assertTrue(r["ok"])
        cells_before = {cid: c.cell for cid, c in mcp_server.SESSION.encounter.combatants.items()}
        mcp_server._autosave()
        self.assertTrue(_simulate_process_restart())
        cells_after = {cid: c.cell for cid, c in mcp_server.SESSION.encounter.combatants.items()}
        self.assertEqual(cells_after, cells_before)        # 走位坐标无损

    def test_no_encounter_field_when_not_in_combat(self):
        data = json.loads(_autosave_path().read_text(encoding="utf-8"))
        self.assertIsNone(data.get("encounter"))           # 没开战 → encounter 为空


if __name__ == "__main__":
    unittest.main()
