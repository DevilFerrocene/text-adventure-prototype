"""冷物体（环境陈设）：场景廉价铺密度 + warm_object 按类别确定性解冻。"""
import unittest

import mcp_server


class AmbientSceneTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        self.assertTrue(mcp_server.move("east")["ok"])   # 营地 → 酒馆（有 ambient）

    def test_scene_lists_ambient_with_kind_and_label(self):
        sc = mcp_server.get_scene()["scene"]
        self.assertIn("ambient", sc)
        names = [a["name"] for a in sc["ambient"]]
        self.assertTrue(any("酒瓶" in n for n in names))
        self.assertTrue(all("kind" in a and "label" in a for a in sc["ambient"]))


class WarmObjectTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.move("east")                          # 酒馆

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="t")

    def _find(self, frag):
        return next((i for i in mcp_server.SESSION.state.inventory if frag in i.name), None)

    def test_grab_bottle_yields_1d3_slash_weapon(self):
        r = mcp_server.warm_object("桌上的酒瓶", "grab")
        self.assertTrue(r["ok"])
        it = self._find("酒瓶")
        self.assertIsNotNone(it)
        self.assertEqual((it.equip_slot, it.damage_expr, it.damage_type),
                         ("weapon", "1d3", "slash"))
        self.assertTrue(mcp_server.equip(it.id)["ok"])   # 真能装备开打

    def test_grab_partial_match(self):
        r = mcp_server.warm_object("酒瓶", "grab")        # 部分匹配
        self.assertTrue(r["ok"])

    def test_grab_furniture_rejected(self):
        r = mcp_server.warm_object("长条木桌", "grab")
        self.assertFalse(r["ok"])                        # 太大，搬不动

    def test_grab_unknown_errors(self):
        self.assertFalse(mcp_server.warm_object("根本不存在的东西", "grab")["ok"])

    def test_smash_furniture_yields_club(self):
        # 砸家具 → 掉一截木料(1d4 钝棒)入背包（家具抓不起，砸开才有用）
        r = mcp_server.warm_object("长条木桌", "smash")
        self.assertTrue(r["ok"])
        self.assertEqual(r["smashed"], "长条木桌")
        club = next((i for i in mcp_server.SESSION.state.inventory if "木料" in i.name), None)
        self.assertIsNotNone(club)
        self.assertEqual((club.equip_slot, club.damage_expr, club.damage_type),
                         ("weapon", "1d4", "blunt"))

    def test_smash_bottle_no_debris(self):
        # 瓶子 grab 已更优，砸只作叙事破坏、不掉碎块
        before = len(mcp_server.SESSION.state.inventory)
        r = mcp_server.warm_object("墙角的空酒坛", "smash")
        self.assertTrue(r["ok"])
        self.assertEqual(len(mcp_server.SESSION.state.inventory), before)   # 无新物

    def test_club_yields_1d4_blunt(self):
        mcp_server.SESSION.state.position = "plains"      # 草原："尖锐的断枝:club"
        r = mcp_server.warm_object("尖锐的断枝", "grab")
        self.assertTrue(r["ok"])
        it = self._find("断枝")
        self.assertEqual((it.damage_expr, it.damage_type), ("1d4", "blunt"))


if __name__ == "__main__":
    unittest.main()
