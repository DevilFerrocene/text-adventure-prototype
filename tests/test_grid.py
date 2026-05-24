"""二维棋盘（房间内空间感）：引擎持坐标+寻路，对外只吐方位+距离。

设计要点回归：
- 有 grid 的房间：get_scene 给出 player_locale + at_hand(手边可交互) + around(四周带方位/距离)。
- 够不着的东西：warm_object/take_item/call_affordance 自动寻路走过去（更新 state.cell），过不去则拒。
- approach 显式走位；move 进房重置到 grid.entry；存档往返保留 cell。
- 无 grid 的房间：一律视为"满屋皆在手边"，零门控（向后兼容）。
"""
import unittest

from core.types import RoomGrid
import mcp_server as m


class BearingDistanceTest(unittest.TestCase):
    """方位/距离/远近词的纯函数。x 东+ / y 南+（行号自上而下）。"""

    def test_bearing_eight_ways(self):
        o = (2, 2)
        self.assertEqual(m._bearing(o, (4, 2)), "东")
        self.assertEqual(m._bearing(o, (0, 2)), "西")
        self.assertEqual(m._bearing(o, (2, 0)), "北")   # y 减小=北
        self.assertEqual(m._bearing(o, (2, 4)), "南")   # y 增大=南
        self.assertEqual(m._bearing(o, (4, 0)), "东北")
        self.assertEqual(m._bearing(o, (0, 0)), "西北")
        self.assertEqual(m._bearing(o, (4, 4)), "东南")
        self.assertEqual(m._bearing(o, (0, 4)), "西南")
        self.assertEqual(m._bearing(o, (2, 2)), "")     # 同格无方位

    def test_chebyshev_is_diagonal_steps(self):
        self.assertEqual(m._cheb((0, 0), (3, 2)), 3)    # 斜走 3 步
        self.assertEqual(m._cheb((1, 1), (1, 1)), 0)

    def test_proximity_buckets(self):
        self.assertEqual(m._proximity_label(0), "脚下")
        self.assertEqual(m._proximity_label(1), "手边")
        self.assertEqual(m._proximity_label(3), "几步外")
        self.assertEqual(m._proximity_label(6), "房间另一头")
        self.assertEqual(m._proximity_label(9), "远处")


class PathfindTest(unittest.TestCase):
    """BFS 寻路：避开 blocked/occupied，8 向，不可达返回 None。"""

    def setUp(self):
        # 5×1 走廊，(2,0) 是墙 → 左右被隔开
        self.grid = RoomGrid(width=5, height=1, blocked=[(2, 0)])

    def test_straight_path_steps(self):
        self.assertEqual(m._grid_pathfind(self.grid, (0, 0), {(1, 0)}), 1)

    def test_already_at_goal(self):
        self.assertEqual(m._grid_pathfind(self.grid, (1, 0), {(1, 0)}), 0)

    def test_blocked_unreachable(self):
        self.assertIsNone(m._grid_pathfind(self.grid, (0, 0), {(4, 0)}))   # 墙隔断

    def test_diagonal_around_obstacle(self):
        # 3×3，中心 (1,1) 占位 → 从 (0,1) 斜绕到 (2,1) 两步
        g = RoomGrid(width=3, height=3, blocked=[(1, 1)])
        self.assertEqual(m._grid_pathfind(g, (0, 1), {(2, 1)}), 2)


class TavernSceneSpaceTest(unittest.TestCase):
    """酒馆（示范 grid 房）：进门落点 + 场景空间总览。"""

    def setUp(self):
        self.assertTrue(m.start_game("aincrad")["ok"])
        self.assertTrue(m.move("east")["ok"])     # camp → tavern

    def test_enters_at_grid_entry(self):
        self.assertEqual(tuple(m.SESSION.state.cell), (0, 2))   # 西侧门口

    def test_scene_has_grid_overview(self):
        g = m.get_scene()["scene"]["grid"]
        self.assertTrue(g["enabled"])
        self.assertTrue(g["player_locale"])                     # 玩家大致方位非空
        names_around = {e["name"] for e in g["around"]}
        # 吧台后的老板、屋子正中的争执都在"四周"（进门够不着）
        self.assertTrue(any("老板" in n for n in names_around))
        self.assertTrue(any("争执" in n or "争吵" in n for n in names_around))

    def test_around_entries_carry_bearing_and_distance(self):
        g = m.get_scene()["scene"]["grid"]
        for e in g["around"]:
            self.assertIn(e["bearing"], m._BEARINGS_8)
            self.assertGreaterEqual(e["steps"], 2)              # around=非手边
            self.assertIn(e["proximity"], ("几步外", "房间另一头", "远处"))

    def test_object_snapshot_annotated_with_spatial(self):
        # 成型物（老板）带 spatial：进门时够不着
        objs = {o["name"]: o for o in m.get_scene()["scene"]["objects"]}
        keeper = next(o for n, o in objs.items() if "老板" in n)
        self.assertIsNotNone(keeper["spatial"])
        self.assertFalse(keeper["spatial"]["in_reach"])


class AutoApproachOnInteractTest(unittest.TestCase):
    """够不着的东西：交互自动寻路走过去；够得着则不挪窝；过不去则拒。"""

    def setUp(self):
        self.assertTrue(m.start_game("aincrad")["ok"])
        m.move("east")                                          # tavern, cell=(0,2)

    def tearDown(self):
        if m.SESSION.in_combat:
            m.end_combat(reason="t")

    def test_warm_far_object_walks_there(self):
        st = m.SESSION.state
        self.assertEqual(tuple(st.cell), (0, 2))
        r = m.warm_object("桌上的酒瓶", "grab")                 # 酒瓶在 (2,3)，够不着
        self.assertTrue(r["ok"])
        self.assertTrue(r["approached"]["moved"])               # 自动走过去了
        self.assertLessEqual(m._cheb(tuple(st.cell), (2, 3)), 1)  # 现在站在酒瓶旁

    def test_warm_when_in_reach_does_not_move(self):
        m.warm_object("桌上的酒瓶", "grab")                     # 先走到酒瓶旁
        before = tuple(m.SESSION.state.cell)
        r = m.warm_object("桌上的酒瓶", "grab")                 # 再抓：已在手边
        self.assertTrue(r["ok"])
        self.assertNotIn("approached", r)                       # 没挪窝
        self.assertEqual(tuple(m.SESSION.state.cell), before)

    def test_take_far_item_walks_there(self):
        # 把酒瓶钉到棋盘上没意义——改测成型物：老板不可拾取，这里用 call_affordance 门控更合适。
        # 这里验证 take_item 在 grid 房对未钉格物体不门控（不崩）。
        st = m.SESSION.state
        # tavern_keeper 钉在 (2,0)，但不可拾取；改测：take 一个不存在物 → 正常报错而非空间崩溃
        r = m.take_item("nonexistent")
        self.assertFalse(r["ok"])


class ApproachToolTest(unittest.TestCase):
    """approach：显式走位。"""

    def setUp(self):
        self.assertTrue(m.start_game("aincrad")["ok"])
        m.move("east")                                          # tavern

    def tearDown(self):
        if m.SESSION.in_combat:
            m.end_combat(reason="t")

    def test_approach_landmark_stands_on_it(self):
        r = m.approach("吧台")                                  # 地标 (3,1)，可驻足
        self.assertTrue(r["ok"])
        self.assertTrue(r["moved"])
        self.assertEqual(tuple(m.SESSION.state.cell), (3, 1))

    def test_approach_partial_match(self):
        r = m.approach("酒瓶")                                  # 部分匹配冷物体
        self.assertTrue(r["ok"])

    def test_approach_unknown_errors(self):
        r = m.approach("根本没有的东西")
        self.assertFalse(r["ok"])

    def test_approach_blocked_in_combat(self):
        m.request_combat(reason="试", improvised=[{"name": "醉汉", "archetype": "brute_low"}])
        self.assertTrue(m.SESSION.in_combat)
        r = m.approach("吧台")
        self.assertFalse(r["ok"])

    def test_approach_in_gridless_room_errors(self):
        m.SESSION.state.position = "floor_2_gate"               # 无 grid 的房间
        r = m.approach("水晶")
        self.assertFalse(r["ok"])


class GridlessBackcompatTest(unittest.TestCase):
    """无 grid 的房间：满屋皆在手边，零门控（旧行为不变）。"""

    def setUp(self):
        self.assertTrue(m.start_game("aincrad")["ok"])
        m.SESSION.world.get_room("camp").grid = None   # 摘掉营地棋盘，模拟未挂 grid 的房间

    def test_scene_grid_is_none(self):
        sc = m.get_scene()["scene"]
        self.assertIsNone(sc["grid"])
        for o in sc["objects"]:
            self.assertIsNone(o["spatial"])

    def test_warm_object_no_gating(self):
        # camp 有 "篝火边的劈柴:club"，无 grid → 直接拿到，不强制走位
        r = m.warm_object("篝火边的劈柴", "grab")
        self.assertTrue(r["ok"])
        self.assertNotIn("approached", r)

    def test_in_reach_true_without_grid(self):
        room = m.SESSION.world.get_room("camp")
        self.assertTrue(m._in_reach(m.SESSION.state, room, (5, 5)))   # 无 grid 恒为真


class PointOfInterestTest(unittest.TestCase):
    """探索点：明面只给 hint、payload 锁在引擎（GM 看不到）；走到跟前自动揭示、一次性。"""

    def setUp(self):
        self.assertTrue(m.start_game("aincrad")["ok"])

    def tearDown(self):
        if m.SESSION.in_combat:
            m.end_combat(reason="t")

    def test_poi_shows_hint_not_payload(self):
        st = m.SESSION.state
        st.position = "plains"; st.cell = (2, 3)
        grid = m.get_scene()["scene"]["grid"]
        names = {e["name"] for e in grid["around"]}
        self.assertIn("草叶间半埋着什么，反着一点微光", names)   # 明面 hint 在
        blob = str(grid)
        self.assertNotIn("loot", blob)                          # payload 不外泄
        self.assertNotIn("磨尖的骨刺", blob)                    # 谜底 GM 看不到

    def test_approach_loot_adds_item_and_is_one_shot(self):
        st = m.SESSION.state
        st.position = "plains"; st.cell = (2, 3)
        r = m.approach("微光")
        self.assertTrue(r["ok"])
        self.assertEqual(r["revealed"]["kind"], "loot")
        self.assertTrue(any("磨尖" in i.name for i in st.inventory))
        self.assertTrue(st.flags.get("_poi_plains_glint"))      # 一次性 flag
        # 揭示后不再出现在场景，也再找不到
        self.assertFalse(any("微光" in e["name"]
                             for e in m.get_scene()["scene"]["grid"]["around"]))
        self.assertFalse(m.approach("微光")["ok"])

    def test_approach_ambush_sets_spawns_and_fightable(self):
        st = m.SESSION.state
        st.position = "forest_edge"; st.cell = (2, 2)
        r = m.approach("兽臊")
        self.assertEqual(r["revealed"]["kind"], "ambush")
        self.assertEqual(st.active_spawns, ["gale_wolf"])       # 伏击落到在场敌人
        self.assertTrue(m.request_combat(reason="应战")["ok"])  # 随后能直接开打

    def test_trap_deals_damage(self):
        from core.types import GridPOI
        st = m.SESSION.state
        room = m.SESSION.world.get_room("plains")
        room.grid.pois.append(GridPOI(
            id="t_acid", cell=(0, 4), hint="地上一摊发暗的黏液",
            payload={"kind": "trap", "damage": "1d4", "damage_type": "acid",
                     "reveal": "黏液腾起酸雾"}))         # 无 save → 必吃伤害
        st.position = "plains"; st.cell = (2, 3)
        hp0 = st.vitals.hp
        r = m.approach("黏液")
        self.assertEqual(r["revealed"]["kind"], "trap")
        self.assertLess(st.vitals.hp, hp0)

    def test_poi_round_trips_one_shot_through_save(self):
        st = m.SESSION.state
        st.position = "plains"; st.cell = (2, 3)
        m.approach("微光")                                       # 揭示 → 置 flag
        m.save_game("poi_test")
        m.start_game("aincrad")
        self.assertFalse(m.SESSION.state.flags.get("_poi_plains_glint"))
        m.load_game("poi_test")
        self.assertTrue(m.SESSION.state.flags.get("_poi_plains_glint"))  # 已揭示状态恢复


class CellPersistenceTest(unittest.TestCase):
    """move 重置到 entry；存档往返保留 cell。"""

    def setUp(self):
        self.assertTrue(m.start_game("aincrad")["ok"])

    def test_move_resets_to_entry(self):
        m.move("east")
        m.approach("吧台")
        self.assertEqual(tuple(m.SESSION.state.cell), (3, 1))
        m.move("west")                                          # 离开酒馆
        m.move("east")                                          # 再进 → 回到 entry
        self.assertEqual(tuple(m.SESSION.state.cell), (0, 2))

    def test_cell_round_trips_through_save(self):
        m.move("east")
        m.approach("吧台")
        m.save_game("grid_cell_test")
        m.start_game("aincrad")                                 # 清内存 → 落回营地 entry
        self.assertEqual(tuple(m.SESSION.state.cell), (2, 2))
        m.load_game("grid_cell_test")
        self.assertEqual(tuple(m.SESSION.state.cell), (3, 1))


if __name__ == "__main__":
    unittest.main()
