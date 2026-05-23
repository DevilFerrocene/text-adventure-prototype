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


if __name__ == "__main__":
    unittest.main()
