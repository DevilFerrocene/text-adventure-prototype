import unittest

from core.types import (
    GameObject, Combatant, GameState, VitalStats,
    is_damageable, is_buff_bearer, is_actor,
)


class EntityCapabilityTest(unittest.TestCase):
    """运行期能力判定（is_*）+ GameObject 默认实体字段。

    这些是 E3 统一伤害入口的地基：deal_damage 会用 is_damageable 决定
    target 合法性。先把判定锁死，E3 接入时才有回归网。
    """

    # ── is_damageable：BG3 式万物可破坏，indestructible 例外 ───────

    def test_default_object_is_damageable(self):
        obj = GameObject(id="dung", name="牛粪", description="一坨")
        self.assertTrue(is_damageable(obj))
        # 默认实体字段
        self.assertEqual(obj.hp, 5)
        self.assertEqual(obj.max_hp, 5)
        self.assertEqual(obj.ac, 5)

    def test_indestructible_object_not_damageable(self):
        wall = GameObject(id="wall", name="砖墙", description="结实",
                          indestructible=True)
        self.assertFalse(is_damageable(wall))

    def test_combatant_is_damageable(self):
        c = Combatant(id="thug", name="打手", side="enemy",
                      hp=8, max_hp=8, ac=10, speed=8)
        self.assertTrue(is_damageable(c))

    def test_object_without_hp_not_damageable(self):
        class NoHp:
            id = "ghost"
        self.assertFalse(is_damageable(NoHp()))

    # ── is_buff_bearer：有 buffs 列表即可挂 buff ─────────────────

    def test_object_is_buff_bearer(self):
        obj = GameObject(id="crate", name="木箱", description="")
        self.assertTrue(is_buff_bearer(obj))

    def test_combatant_is_buff_bearer(self):
        c = Combatant(id="thug", name="打手", side="enemy",
                      hp=8, max_hp=8, ac=10, speed=8)
        self.assertTrue(is_buff_bearer(c))

    def test_plain_object_not_buff_bearer(self):
        class Plain:
            id = "x"
        self.assertFalse(is_buff_bearer(Plain()))

    # ── is_actor：有 speed + behavior_profile 才有回合 ────────────

    def test_combatant_is_actor(self):
        c = Combatant(id="thug", name="打手", side="enemy",
                      hp=8, max_hp=8, ac=10, speed=8,
                      behavior_profile="aggressive")
        self.assertTrue(is_actor(c))

    def test_scenery_object_not_actor(self):
        # GameObject has no speed/behavior_profile → not an actor
        obj = GameObject(id="dung", name="牛粪", description="")
        self.assertFalse(is_actor(obj))

    # ── GameState 不是实体：hp 在 vitals 里，不该被判为 damageable ──

    def test_gamestate_is_not_damageable(self):
        state = GameState(position="apartment", vitals=VitalStats(hp=10, max_hp=10))
        # GameState has no top-level hp attribute; hp lives on vitals
        self.assertFalse(is_damageable(state))

    def test_gamestate_is_buff_bearer(self):
        # player carries buffs directly on GameState
        state = GameState(position="apartment")
        self.assertTrue(is_buff_bearer(state))

    # ── on_destroyed 默认空，可挂 step ───────────────────────────

    def test_object_on_destroyed_defaults_empty(self):
        obj = GameObject(id="jar", name="陶罐", description="")
        self.assertEqual(obj.on_destroyed, [])
        # 独立 default factory：两个对象不共享同一 list
        other = GameObject(id="jar2", name="陶罐2", description="")
        obj.on_destroyed.append({"flag": "broken"})
        self.assertEqual(other.on_destroyed, [])


if __name__ == "__main__":
    unittest.main()
