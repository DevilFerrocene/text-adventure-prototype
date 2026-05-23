"""刷怪（动态遭遇）：刷怪场进门随机刷，不再静态摆全量敌人池；Boss 房仍固定。"""
import unittest
from unittest.mock import patch

import mcp_server


class RollSpawnsTest(unittest.TestCase):
    """_roll_spawns 本身：刷怪场才刷，按概率刷 0/1/2 只。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        self.plains = mcp_server.SESSION.world.get_room("plains")      # spawn_ground
        self.camp = mcp_server.SESSION.world.get_room("camp")          # 安全区
        self.boss = mcp_server.SESSION.world.get_room("warden_gate")   # 固定遭遇

    def test_non_spawn_ground_never_rolls(self):
        self.assertEqual(mcp_server._roll_spawns(self.camp), [])       # 安全营地
        self.assertEqual(mcp_server._roll_spawns(self.boss), [])       # Boss 房不随机刷

    def test_quiet_when_chance_misses(self):
        with patch("mcp_server.random.random", return_value=0.99):     # ≥ SPAWN_CHANCE
            self.assertEqual(mcp_server._roll_spawns(self.plains), [])

    def test_spawns_single_from_pool(self):
        # 第一掷 0.0 < SPAWN_CHANCE → 刷；第二掷 0.5 ≥ PAIR_CHANCE → 单只
        with patch("mcp_server.random.random", side_effect=[0.0, 0.5]), \
             patch("mcp_server.random.choices", return_value=["killer_rabbit"]):
            got = mcp_server._roll_spawns(self.plains)
        self.assertEqual(got, ["killer_rabbit"])
        self.assertTrue(set(got) <= set(self.plains.enemies))          # 只从池里抽

    def test_spawns_pair_when_pair_roll_hits(self):
        with patch("mcp_server.random.random", side_effect=[0.0, 0.0]), \
             patch("mcp_server.random.choices", return_value=["gale_wolf"]):
            got = mcp_server._roll_spawns(self.plains)
        self.assertEqual(len(got), 2)

    def test_spawn_uses_weights_favoring_tutorial_mob(self):
        # 加权抽取：杀人兔(教学怪 spawn_weight=4)在草原池里权重应最大
        captured = {}
        def fake_choices(pool, weights=None, k=1):
            captured["pool"], captured["weights"] = pool, weights
            return [pool[0]]
        with patch("mcp_server.random.random", side_effect=[0.0, 0.5]), \
             patch("mcp_server.random.choices", side_effect=fake_choices):
            mcp_server._roll_spawns(self.plains)
        pool, weights = captured["pool"], captured["weights"]
        ri = pool.index("killer_rabbit")
        self.assertGreater(weights[ri], 1.0)                     # 比默认权重大
        self.assertEqual(weights[ri], max(weights))              # 是池里最大的


class SceneReflectsSpawnsTest(unittest.TestCase):
    """get_scene 只显示【此刻在场】的敌人，不再显示整池。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.SESSION.state.position = "plains"

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_scene_hides_spawn_ground_tag(self):
        # GM 不该知道"这是刷怪区"——机制内部标签从场景快照里滤掉
        sc = mcp_server.get_scene()["scene"]
        self.assertNotIn("spawn_ground", sc["tags"])
        # 但叙事性标签仍在（场景还是雾语草原）
        self.assertIn("field", sc["tags"])
        # 引擎自己照常认得它是刷怪场（标签还在房间对象上，只是不外显）
        self.assertTrue(mcp_server._is_spawn_ground(mcp_server.SESSION.world.get_room("plains")))

    def test_no_spawns_means_no_enemy_profiles(self):
        mcp_server.SESSION.state.active_spawns = []
        sc = mcp_server.get_scene()
        self.assertNotIn("enemy_profiles", sc)
        self.assertFalse(sc.get("can_initiate_combat"))

    def test_only_spawned_enemies_show(self):
        # 池里有 4 种，但此刻只刷到 1 只 → 场景只显示这 1 只
        mcp_server.SESSION.state.active_spawns = ["killer_rabbit"]
        sc = mcp_server.get_scene()
        self.assertTrue(sc.get("can_initiate_combat"))
        ids = [p["id"] for p in sc["enemy_profiles"]]
        self.assertEqual(ids, ["killer_rabbit"])
        self.assertLess(len(ids), len(mcp_server.SESSION.world.get_room("plains").enemies))


class RequestCombatUsesSpawnsTest(unittest.TestCase):
    """request_combat 不带 canon 时，只打【在场刷到的】，不再一锅端整池。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.SESSION.state.position = "plains"

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_no_enemies_present_errors(self):
        mcp_server.SESSION.state.active_spawns = []
        r = mcp_server.request_combat(reason="试着开打")
        self.assertFalse(r["ok"])

    def test_fights_only_spawned_subset(self):
        mcp_server.SESSION.state.active_spawns = ["killer_rabbit"]
        r = mcp_server.request_combat(reason="扑上去")
        self.assertTrue(r["ok"])
        enemies = [c for c in mcp_server.SESSION.encounter.combatants.values()
                   if c.side == "enemy"]
        self.assertEqual(len(enemies), 1)             # 只打刷到的那一只，不是整池 4 只

    def test_end_combat_clears_spawns(self):
        mcp_server.SESSION.state.active_spawns = ["killer_rabbit"]
        mcp_server.request_combat(reason="开打")
        mcp_server.end_combat(reason="解决了")
        self.assertEqual(mcp_server.SESSION.state.active_spawns, [])


class MoveRerollsTest(unittest.TestCase):
    """move 进入刷怪场重刷；进入安全/非刷怪房清空。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_move_into_spawn_ground_rolls(self):
        with patch("mcp_server._roll_spawns", return_value=["killer_rabbit"]):
            r = mcp_server.move("north")              # camp → plains
        self.assertEqual(mcp_server.SESSION.state.active_spawns, ["killer_rabbit"])
        self.assertEqual(r.get("spawned"), ["killer_rabbit"])

    def test_move_spawn_carries_enemy_profiles(self):
        # F2：move 撞上遭遇时一并带 enemy_profiles，供前端渲染"敌在场"卡
        with patch("mcp_server._roll_spawns", return_value=["killer_rabbit"]):
            r = mcp_server.move("north")
        profs = r.get("enemy_profiles")
        self.assertTrue(profs and profs[0]["name"] == "杀人兔")

    def test_move_back_to_safe_clears(self):
        with patch("mcp_server._roll_spawns", return_value=["killer_rabbit"]):
            mcp_server.move("north")                  # 进草原刷到怪
        # 回营地（安全区，非刷怪场）→ 在场敌人清空
        r = mcp_server.move("south")                  # plains → camp
        self.assertEqual(mcp_server.SESSION.state.active_spawns, [])
        self.assertNotIn("spawned", r)


class BossRoomStaysFixedTest(unittest.TestCase):
    """Boss 房（无 spawn_ground 标签）仍固定摆放；打清后才隐去。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])
        mcp_server.SESSION.state.position = "warden_gate"

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_boss_present_without_spawn_roll(self):
        # active_spawns 为空，但 Boss 房静态敌人照常在场
        mcp_server.SESSION.state.active_spawns = []
        sc = mcp_server.get_scene()
        self.assertTrue(sc.get("can_initiate_combat"))
        ids = {p["id"] for p in sc["enemy_profiles"]}
        self.assertEqual(ids, set(mcp_server.SESSION.world.get_room("warden_gate").enemies))

    def test_boss_hidden_after_cleared(self):
        # 胜利后打清 → 不再阴魂不散
        mcp_server.SESSION.state.flags["_cleared_warden_gate"] = True
        sc = mcp_server.get_scene()
        self.assertNotIn("enemy_profiles", sc)


class SpawnPersistenceTest(unittest.TestCase):
    """active_spawns 进存档、读档还原。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def test_active_spawns_round_trip(self):
        mcp_server.SESSION.state.position = "plains"
        mcp_server.SESSION.state.active_spawns = ["killer_rabbit", "gale_wolf"]
        mcp_server.save_game("spawn_test")
        mcp_server.start_game("aincrad")              # 清掉内存态
        self.assertEqual(mcp_server.SESSION.state.active_spawns, [])
        mcp_server.load_game("spawn_test")
        self.assertEqual(mcp_server.SESSION.state.active_spawns, ["killer_rabbit", "gale_wolf"])


if __name__ == "__main__":
    unittest.main()
