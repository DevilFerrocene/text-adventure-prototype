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
        self.assertIn("vertical_arc", skill_ids)
        self.assertIn("sword_mastery", skill_ids)  # 出身自带
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
        mcp_server.move("north")  # 触发一次 autosave，把出身技能写进去
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
        # 玩 aincrad 到一半 → 新开 yanan → autosave 应是 yanan 而非旧 aincrad
        mcp_server.start_game("aincrad")
        mcp_server.move("north")
        mcp_server.start_game("yanan")
        data = json.loads(_autosave_path().read_text(encoding="utf-8"))
        self.assertEqual(data["world"], "yanan")
        self.assertEqual(data["position"], "apartment")
        # 重启后恢复到 yanan
        _simulate_process_restart()
        self.assertEqual(mcp_server.SESSION.world_name, "yanan")


if __name__ == "__main__":
    unittest.main()
