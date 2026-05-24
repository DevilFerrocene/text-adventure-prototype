"""世界引用完整性：注册的世界不该有悬空 id（出口/物体/敌人/技能/揭示/开战）。

这层校验把"作者期拼写错"在测试期就抓出来——改内容时再也不用靠肉眼核对 id 对没对上。
"""
import unittest

import mcp_server
from runtime.game_world import GameWorld


class WorldIntegrityTest(unittest.TestCase):
    def test_all_registered_worlds_clean(self):
        for name, module in mcp_server.WORLDS.items():
            problems = GameWorld(content_module=module).validate()
            self.assertEqual(problems, [], f"世界 {name} 引用问题：\n  " + "\n  ".join(problems))


class ValidatorCatchesTest(unittest.TestCase):
    """负向测试：确认校验器真能逮到各类悬空引用（不是摆设）。"""

    def _world(self):
        return GameWorld(content_module=mcp_server.WORLDS["aincrad"])

    def test_dangling_exit_target(self):
        w = self._world()
        next(iter(w.rooms.values())).exits["__x__"] = "no_such_room"
        self.assertTrue(any("no_such_room" in p for p in w.validate()))

    def test_room_references_missing_object(self):
        w = self._world()
        next(iter(w.rooms.values())).objects.append("ghost_object")
        self.assertTrue(any("ghost_object" in p for p in w.validate()))

    def test_room_references_missing_enemy(self):
        w = self._world()
        next(iter(w.rooms.values())).enemies.append("no_such_enemy")
        self.assertTrue(any("no_such_enemy" in p for p in w.validate()))

    def test_locked_exit_not_in_exits(self):
        w = self._world()
        next(iter(w.rooms.values())).locked_exits["nowhere"] = "some_flag"
        self.assertTrue(any("nowhere" in p for p in w.validate()))

    def test_affordance_start_combat_missing_enemy(self):
        w = self._world()
        from core.types import Affordance
        obj = next(iter(w.objects.values()))
        obj.affordances["__fight__"] = Affordance(
            verb="__fight__", effect={"start_combat": {"canon": ["ghost_boss"]}})
        self.assertTrue(any("ghost_boss" in p for p in w.validate()))


class GridValidatorCatchesTest(unittest.TestCase):
    """二维棋盘校验：坐标越界 / 叠格 / 引用错 / 进门不可站 / 实体被墙死。"""

    def _world(self):
        return GameWorld(content_module=mcp_server.WORLDS["aincrad"])

    def test_out_of_bounds_coord(self):
        from core.types import RoomGrid
        w = self._world()
        r = w.get_room("tavern")
        r.grid = RoomGrid(width=3, height=3, entry=(0, 0),
                          objects={"tavern_keeper": (9, 9)})
        self.assertTrue(any("越界" in p for p in w.validate()))

    def test_overlap_two_entities_same_cell(self):
        from core.types import RoomGrid
        w = self._world()
        r = w.get_room("tavern")
        r.grid = RoomGrid(width=3, height=3, entry=(0, 0),
                          objects={"tavern_keeper": (1, 1)},
                          landmarks={"吧台": (1, 1)})
        self.assertTrue(any("叠了两样" in p for p in w.validate()))

    def test_grid_object_not_in_room(self):
        from core.types import RoomGrid
        w = self._world()
        r = w.get_room("tavern")
        r.grid = RoomGrid(width=3, height=3, entry=(0, 0),
                          objects={"ghost_thing": (1, 1)})
        self.assertTrue(any("不在 room.objects" in p for p in w.validate()))

    def test_entry_not_standable(self):
        from core.types import RoomGrid
        w = self._world()
        r = w.get_room("tavern")
        r.grid = RoomGrid(width=3, height=3, entry=(1, 1), blocked=[(1, 1)])
        self.assertTrue(any("进门落点" in p for p in w.validate()))

    def test_entity_walled_off_unreachable(self):
        from core.types import RoomGrid
        w = self._world()
        r = w.get_room("tavern")
        # 把酒瓶放中心 (2,2)、八方全堵 → 玩家从 entry(0,0) 走不到
        r.grid = RoomGrid(width=5, height=5, entry=(0, 0),
                          ambient={"桌上的酒瓶": (2, 2)},
                          blocked=[(1, 1), (2, 1), (3, 1), (1, 2), (3, 2), (1, 3), (2, 3), (3, 3)])
        self.assertTrue(any("被墙死" in p for p in w.validate()))


if __name__ == "__main__":
    unittest.main()
