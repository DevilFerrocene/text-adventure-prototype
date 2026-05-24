"""世界编辑器后端端点：列世界 / 导出 / 实时校验 / 保存 / 删除 / 防覆盖内置。

编辑器是 WebUI 的写入口，这些端点是它与引擎之间的契约。钉死：内置世界只读可导出、
JSON 世界可存可删、保存即热刷新进 WORLDS、校验真能逮到悬空引用、世界名做了防穿越。
"""
import unittest

from fastapi.testclient import TestClient

import mcp_server
import standalone.web as web


class EditorApiTest(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(web.app)
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        # 清掉测试残留世界 + 可能写出的内置覆盖层，恢复纯内置注册
        for p in mcp_server.WORLDS_DIR.glob("ed_test*.json"):
            p.unlink()
        (mcp_server.WORLDS_DIR / "aincrad.json").unlink(missing_ok=True)
        mcp_server.load_json_worlds()

    def _aincrad_export(self):
        return self.c.get("/editor/world/aincrad").json()["world"]

    def test_list_worlds_marks_builtin(self):
        worlds = self.c.get("/editor/worlds").json()["worlds"]
        ain = next(w for w in worlds if w["name"] == "aincrad")
        self.assertTrue(ain["builtin"])
        self.assertFalse(ain["editable"])

    def test_export_builtin_is_full_world(self):
        r = self.c.get("/editor/world/aincrad").json()
        self.assertTrue(r["ok"])
        self.assertFalse(r["editable"])
        self.assertEqual(len(r["world"]["rooms"]), 9)
        self.assertIn("initial_state", r["world"])

    def test_get_unknown_world_404(self):
        self.assertEqual(self.c.get("/editor/world/nope").status_code, 404)

    def test_validate_catches_dangling_exit(self):
        bad = {"name": "x",
               "rooms": {"r0": {"name": "房", "base_description": "d",
                                "exits": {"north": "ghost"}}},
               "initial_state": {"position": "r0"}}
        out = self.c.post("/editor/validate", json=bad).json()
        self.assertTrue(out["ok"])
        self.assertTrue(any("ghost" in p for p in out["problems"]))

    def test_validate_clean_world_empty_problems(self):
        out = self.c.post("/editor/validate", json=self._aincrad_export()).json()
        self.assertEqual(out["problems"], [])

    def test_save_registers_and_refreshes(self):
        data = self._aincrad_export()
        sv = self.c.post("/editor/world/ed_test1", json=data).json()
        self.assertTrue(sv["ok"])
        self.assertEqual(sv["problems"], [])
        self.assertIn("ed_test1", mcp_server.WORLDS)
        listed = self.c.get("/editor/worlds").json()["worlds"]
        self.assertTrue(any(w["name"] == "ed_test1" and w["editable"] for w in listed))

    def test_save_over_builtin_creates_override(self):
        # 不再保护内置：同名保存写一份 JSON 覆盖层，aincrad 变为可编辑的 JsonWorld
        out = self.c.post("/editor/world/aincrad", json=self._aincrad_export()).json()
        self.assertTrue(out["ok"])
        self.assertEqual(out["problems"], [])
        self.assertTrue(hasattr(mcp_server.WORLDS["aincrad"], "data"))
        self.assertTrue((mcp_server.WORLDS_DIR / "aincrad.json").exists())

    def test_delete_override_restores_builtin(self):
        self.c.post("/editor/world/aincrad", json=self._aincrad_export())
        self.assertTrue(hasattr(mcp_server.WORLDS["aincrad"], "data"))  # 覆盖层
        self.c.delete("/editor/world/aincrad")
        # 删掉覆盖层 → 还原内置 Python 模块（不再有 .data）
        self.assertFalse(hasattr(mcp_server.WORLDS["aincrad"], "data"))

    def test_rejects_path_traversal_name(self):
        out = self.c.post("/editor/world/..%2Fevil", json={"name": "x"})
        # 路径里的非法名要么 404 路由不匹配，要么被名字校验拒
        self.assertIn(out.status_code, (404, 400, 200))
        if out.status_code == 200:
            self.assertFalse(out.json()["ok"])

    def test_delete_removes_world(self):
        self.c.post("/editor/world/ed_test2", json=self._aincrad_export())
        self.assertIn("ed_test2", mcp_server.WORLDS)
        out = self.c.delete("/editor/world/ed_test2").json()
        self.assertTrue(out["ok"])
        self.assertNotIn("ed_test2", mcp_server.WORLDS)

    def test_save_invalid_structure_rejected(self):
        # rooms 不是 dict → 构建失败，应被挡下而非落盘
        out = self.c.post("/editor/world/ed_test3", json={"rooms": "notadict"}).json()
        self.assertFalse(out["ok"])
        self.assertNotIn("ed_test3", mcp_server.WORLDS)


if __name__ == "__main__":
    unittest.main()
