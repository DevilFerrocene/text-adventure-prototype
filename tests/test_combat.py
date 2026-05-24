import unittest
from unittest.mock import patch

import mcp_server


class CombatTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    # ── start_combat：投影玩家 + 生成敌人 + initiative ──────────────

    def test_start_combat_with_canon_enemy(self):
        result = mcp_server.start_combat(canon=["frenzy_boar"])
        self.assertTrue(result["ok"])
        enc = result["encounter"]
        self.assertTrue(enc["active"])
        ids = {c["id"] for c in enc["combatants"]}
        self.assertIn("player", ids)
        self.assertIn("enemy_frenzy_boar", ids)
        # player always acts first in initiative
        self.assertEqual(enc["turn_order"][0], "player")

    def test_start_combat_unknown_enemy_fails(self):
        result = mcp_server.start_combat(canon=["no_such_enemy"])
        self.assertFalse(result["ok"])

    def test_cannot_start_combat_twice(self):
        self.assertTrue(mcp_server.start_combat(canon=["frenzy_boar"])["ok"])
        again = mcp_server.start_combat(canon=["frenzy_boar"])
        self.assertFalse(again["ok"])

    def test_improvised_enemy_count_spawns_multiple(self):
        result = mcp_server.start_combat(
            improvised=[{"name": "醉汉", "archetype": "brute_low", "count": 2}]
        )
        self.assertTrue(result["ok"])
        enemies = [c for c in result["encounter"]["combatants"] if c["side"] == "enemy"]
        self.assertEqual(len(enemies), 2)

    def test_unknown_archetype_fails(self):
        result = mcp_server.start_combat(
            improvised=[{"name": "X", "archetype": "godzilla", "count": 1}]
        )
        self.assertFalse(result["ok"])

    # ── declare_intent attack：命中判定 + 伤害 + 死亡 ──────────────

    def test_attack_hit_deals_damage(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        # pad the thug's hp so a single crit hit wounds rather than kills,
        # keeping combat live so the encounter snapshot still has combatants
        thug = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        thug.hp = thug.max_hp = 50
        # crit-success roll (nat 20) guarantees a hit; fixed damage roll
        with patch("mcp_server.random.randint", return_value=20):
            result = mcp_server.declare_intent(
                actor="player", intent="attack", target="enemy_frenzy_boar"
            )
        self.assertTrue(result["ok"])
        kinds = [e["kind"] for e in result["events"]]
        self.assertIn("hit", kinds)
        thug_snap = next(c for c in result["encounter"]["combatants"]
                         if c["id"] == "enemy_frenzy_boar")
        self.assertLess(thug_snap["hp"], thug_snap["max_hp"])

    def test_attack_miss_no_damage(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        # nat 1 is a critical failure → miss regardless of AC
        with patch("mcp_server.random.randint", return_value=1):
            result = mcp_server.declare_intent(
                actor="player", intent="attack", target="enemy_frenzy_boar"
            )
        self.assertTrue(result["ok"])
        kinds = [e["kind"] for e in result["events"]]
        self.assertIn("miss", kinds)
        thug = next(c for c in result["encounter"]["combatants"]
                    if c["id"] == "enemy_frenzy_boar")
        self.assertEqual(thug["hp"], thug["max_hp"])

    def test_killing_only_enemy_ends_combat(self):
        # 1-hp improvised enemy dies to any hit and ends the encounter
        mcp_server.start_combat(
            improvised=[{"name": "纸人", "archetype": "brute_low", "count": 1}]
        )
        enemy_id = next(
            c["id"] for c in mcp_server._encounter_snapshot()["combatants"]
            if c["side"] == "enemy"
        )
        # force the enemy to 1 hp so one hit kills
        mcp_server.SESSION.encounter.combatants[enemy_id].hp = 1
        with patch("mcp_server.random.randint", return_value=20):
            result = mcp_server.declare_intent(
                actor="player", intent="attack", target=enemy_id
            )
        self.assertTrue(result["ok"])
        kinds = [e["kind"] for e in result["events"]]
        self.assertIn("kill", kinds)
        self.assertTrue(result["encounter"].get("combat_ended"))
        self.assertFalse(mcp_server.SESSION.in_combat)

    def test_declare_intent_wrong_turn_rejected(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        # not the enemy's turn yet (player is active)
        result = mcp_server.declare_intent(
            actor="enemy_frenzy_boar", intent="attack", target="player"
        )
        self.assertFalse(result["ok"])

    def test_defend_grants_temp_ac(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        before = next(c for c in mcp_server._encounter_snapshot()["combatants"]
                      if c["id"] == "player")["ac"]
        result = mcp_server.declare_intent(actor="player", intent="defend")
        self.assertTrue(result["ok"])
        after = next(c for c in result["encounter"]["combatants"]
                     if c["id"] == "player")["ac"]
        self.assertEqual(after, before + 2)

    # ── 敌人 buff 在战斗轮 tick（流血/灼烧）───────────────────────

    def test_enemy_hp_buff_ticks_each_round(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        bleed = mcp_server.add_improvised_buff(
            name="流血", desc="伤口不止", polarity="debuff",
            target="hp", op="add", value=-2, duration=5,
            timing="turn_start", bearer_id="enemy_frenzy_boar",
        )
        self.assertTrue(bleed["ok"])
        thug = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        hp_before = thug.hp
        # player then enemy act → wrap to player bumps the round → tick
        with patch("mcp_server.random.randint", return_value=1):
            mcp_server.declare_intent(actor="player", intent="defend")
            mcp_server.declare_intent(
                actor="enemy_frenzy_boar", intent="attack", target="player"
            )
        self.assertLess(thug.hp, hp_before)

    # ── end_combat 写回玩家 hp ────────────────────────────────────

    def test_end_combat_writes_back_player_hp(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        player = mcp_server.SESSION.encounter.combatants["player"]
        player.hp = 3
        result = mcp_server.end_combat(reason="负伤撤退")
        self.assertTrue(result["ok"])
        self.assertEqual(mcp_server.SESSION.state.vitals.hp, 3)
        self.assertFalse(mcp_server.SESSION.in_combat)


class ActionEconomyTest(unittest.TestCase):
    """§14-R2：action_economy=True 下，每回合 1 大动 + 1 小动。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])
        mcp_server.start_combat(canon=["frenzy_boar"])
        self.enc = mcp_server.SESSION.encounter
        self.enc.action_economy = True
        # 敌人血量拉满，避免一刀斩杀提前结束遭遇
        thug = self.enc.combatants["enemy_frenzy_boar"]
        thug.hp = thug.max_hp = 999

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_major_keeps_turn_then_minor_advances(self):
        # 大动（攻击）后回合不过，仍是 player，且小动可用
        r1 = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_frenzy_boar")
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["next_actor"], "player")
        self.assertEqual(r1["actions_left"], {"major": False, "minor": True})
        # 小动（走位）耗尽第二槽 → 回合推进给敌人
        r2 = mcp_server.declare_intent(
            actor="player", intent="move", target="retreat")
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["next_actor"], "enemy_frenzy_boar")

    def test_second_major_rejected(self):
        mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_frenzy_boar")
        r = mcp_server.declare_intent(
            actor="player", intent="defend")
        self.assertFalse(r["ok"])
        self.assertIn("大动", r["error"])

    def test_end_turn_forfeits_remaining(self):
        # 直接 end_turn，放弃两槽 → 立刻轮到敌人
        r = mcp_server.declare_intent(actor="player", intent="end_turn")
        self.assertTrue(r["ok"])
        self.assertEqual(r["next_actor"], "enemy_frenzy_boar")

    def test_move_changes_rank_and_clamps(self):
        self.enc.rank_depth = 2
        player = self.enc.combatants["player"]
        player.rank = 0
        r = mcp_server.declare_intent(
            actor="player", intent="move", target="retreat")
        self.assertTrue(r["ok"])
        self.assertEqual(player.rank, 1)
        # 再退一步被 rank_depth 钳制（仍是同回合的大动尚未用，回合不过）
        # 此时小动已用完，move 应被拒
        r2 = mcp_server.declare_intent(
            actor="player", intent="move", target="retreat")
        self.assertFalse(r2["ok"])
        self.assertIn("小动", r2["error"])

    def test_next_actor_slots_reset(self):
        # 玩家用满两槽推进 → 敌人回合开始，敌人两槽应为初始 False
        mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_frenzy_boar")
        mcp_server.declare_intent(actor="player", intent="end_turn")
        thug = self.enc.combatants["enemy_frenzy_boar"]
        self.assertFalse(thug.acted_major)
        self.assertFalse(thug.acted_minor)

    def test_legacy_mode_unchanged(self):
        # action_economy=False 时，一动即过（回归保证）
        self.enc.action_economy = False
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_frenzy_boar")
        self.assertTrue(r["ok"])
        self.assertEqual(r["next_actor"], "enemy_frenzy_boar")

    def test_reach_gates_attack_out_of_range(self):
        # 近战 reach=1：玩家在前排(0)，敌人在后排(1) → gap=1≥reach → 打不到
        player = self.enc.combatants["player"]
        thug = self.enc.combatants["enemy_frenzy_boar"]
        player.rank, player.reach = 0, 1
        thug.rank = 1
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_frenzy_boar")
        self.assertFalse(r["ok"])
        self.assertIn("触及范围外", r["error"])
        # 敌人移到前排 → gap=0 < reach → 可打
        thug.rank = 0
        r2 = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_frenzy_boar")
        self.assertTrue(r2["ok"])

    def test_default_reach_unlimited(self):
        # 默认 reach=99：无论排位都打得到（现状行为）
        player = self.enc.combatants["player"]
        thug = self.enc.combatants["enemy_frenzy_boar"]
        player.rank, thug.rank = 0, 1
        self.assertEqual(player.reach, 99)
        r = mcp_server.declare_intent(
            actor="player", intent="attack", target="enemy_frenzy_boar")
        self.assertTrue(r["ok"])


class TacticalSetupTest(unittest.TestCase):
    """§14-R2：GM 凭工具自编战术战斗（start_combat tactical 参数 + 武器 reach）。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game()["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="test cleanup")

    def test_start_combat_tactical_sets_ranks_and_economy(self):
        res = mcp_server.start_combat(
            improvised=[
                {"name": "打手", "archetype": "brute_mid", "rank": 0, "reach": 1},
                {"name": "弓手", "archetype": "scout", "rank": 1, "reach": 99,
                 "max_poise": 8},
            ],
            tactical=True, rank_depth=2, player_rank=0,
        )
        self.assertTrue(res["ok"])
        enc = mcp_server.SESSION.encounter
        self.assertTrue(enc.action_economy)
        self.assertEqual(enc.rank_depth, 2)
        ranks = {c.name: c.rank for c in enc.combatants.values()}
        self.assertEqual(ranks["打手"], 0)
        self.assertEqual(ranks["弓手"], 1)
        # 快照在战术模式下暴露排位 + 行动经济
        snap = res["encounter"]
        self.assertTrue(snap.get("action_economy"))
        self.assertIn("actions_left", snap)
        archer = next(c for c in snap["combatants"] if c["name"] == "弓手")
        self.assertEqual(archer["rank"], 1)
        self.assertEqual(archer["max_poise"], 8)

    def test_weapon_reach_gates_then_ranged_reaches(self):
        from core.types import InventoryItem
        st = mcp_server.SESSION.state
        st.add_item(InventoryItem(id="dagger", name="匕首", kind="weapon",
                                  equip_slot="weapon", damage_expr="1d4", reach=1))
        st.add_item(InventoryItem(id="sling", name="投石索", kind="weapon",
                                  equip_slot="weapon", damage_expr="1d4", reach=99))
        mcp_server.equip("dagger")
        mcp_server.start_combat(
            improvised=[{"name": "弓手", "archetype": "scout", "rank": 1, "reach": 99}],
            tactical=True, rank_depth=2, player_rank=0,
        )
        archer = next(c.id for c in mcp_server.SESSION.encounter.combatants.values()
                      if c.side == "enemy")
        # 匕首 reach=1，后排弓手 gap=0+1=1 ≥ 1 → 触及不到
        r1 = mcp_server.declare_intent(
            actor="player", intent="attack", target=archer, weapon="dagger")
        self.assertFalse(r1["ok"])
        self.assertIn("触及范围外", r1["error"])
        # 投石索 reach=99 → 同样排位，够得到
        r2 = mcp_server.declare_intent(
            actor="player", intent="attack", target=archer, weapon="sling")
        self.assertTrue(r2["ok"])

    def test_non_tactical_combat_snapshot_omits_ranks(self):
        # tactical=False（默认）→ 快照不塞排位/行动经济，旧前端零负担
        res = mcp_server.start_combat(canon=["frenzy_boar"])
        snap = res["encounter"]
        self.assertNotIn("action_economy", snap)
        self.assertNotIn("rank", snap["combatants"][0])


class CritDoubleTest(unittest.TestCase):
    """大成功(自然20)命中 → 攻击伤害翻倍。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="t")

    def _hit_damage(self, d20):
        mcp_server.start_combat(canon=["frenzy_boar"])
        boar = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        boar.hp = boar.max_hp = 100
        # 第一掷=命中骰，第二掷=伤害骰(固定3)；多垫几个防额外调用
        with patch("mcp_server.random.randint", side_effect=[d20, 3, 3, 3]):
            r = mcp_server.declare_intent(actor="player", intent="attack",
                                          target="enemy_frenzy_boar")
        hit = next(e for e in r["events"] if e["kind"] == "hit")
        mcp_server.end_combat(reason="t")
        return hit["detail"]

    def test_critical_hit_doubles_damage(self):
        crit = self._hit_damage(20)      # 自然20=大成功
        normal = self._hit_damage(15)    # 普通命中
        self.assertTrue(crit["crit"])
        self.assertFalse(normal["crit"])
        self.assertEqual(crit["damage"], normal["damage"] * 2)   # 同伤害骰，暴击×2


class AdvantageRollTest(unittest.TestCase):
    """偷袭走优势：roll_check / declare_intent 一次性 advantage = 双骰取高。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="t")

    def test_advantage_takes_higher(self):
        with patch("mcp_server.random.randint", side_effect=[5, 18]):
            r = mcp_server.roll_check(reason="偷袭", advantage="advantage")
        self.assertEqual(r["raw"], 18)

    def test_disadvantage_takes_lower(self):
        with patch("mcp_server.random.randint", side_effect=[5, 18]):
            r = mcp_server.roll_check(reason="被压制", advantage="disadvantage")
        self.assertEqual(r["raw"], 5)

    def test_declare_intent_attack_advantage(self):
        mcp_server.start_combat(canon=["frenzy_boar"])
        boar = mcp_server.SESSION.encounter.combatants["enemy_frenzy_boar"]
        boar.hp = boar.max_hp = 100
        with patch("mcp_server.random.randint", side_effect=[3, 19, 3, 3]):  # 双骰取高 19
            r = mcp_server.declare_intent(actor="player", intent="attack",
                                          target="enemy_frenzy_boar", advantage="advantage")
        atk = next(e for e in r["events"] if e["kind"] in ("attack", "hit"))
        self.assertEqual(atk["detail"]["roll"], 19)


class OpportunityAttackTest(unittest.TestCase):
    """§14-R3：战术下脱离敌人触及范围 → 借机攻击；每敌每回合一次；非战术不触发。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="t")

    def _start_tactical_melee(self):
        mcp_server.start_combat(
            tactical=True, rank_depth=2,
            improvised=[{"name": "持刀兵", "archetype": "brute_low",
                         "count": 1, "rank": 0, "reach": 1}])
        enc = mcp_server.SESSION.encounter
        enc.combatants["player"].rank = 0          # 同在前排，敌触及内
        enc.combatants["player"].hp = 100           # 撑住，别被借机打死偏离测试
        return enc

    def test_retreat_provokes_opportunity_attack(self):
        self._start_tactical_melee()
        with patch("mcp_server.random.randint", return_value=18):
            r = mcp_server.declare_intent(actor="player", intent="move", target="retreat")
        self.assertIn("move", [e["kind"] for e in r["events"]])
        self.assertTrue(any(e["detail"].get("opportunity") for e in r["events"]))

    def test_aoo_once_per_round(self):
        enc = self._start_tactical_melee()
        p = enc.combatants["player"]
        with patch("mcp_server.random.randint", return_value=18):
            ev1 = []
            mcp_server._trigger_opportunity_attacks(enc, "player", p, 0, 1, ev1)
            self.assertTrue(any(e.detail.get("opportunity") for e in ev1))
            p.rank = 0                              # 假想同回合再次脱离
            ev2 = []
            mcp_server._trigger_opportunity_attacks(enc, "player", p, 0, 1, ev2)
            self.assertFalse(any(e.detail.get("opportunity") for e in ev2))  # 本回合已借机

    def test_no_aoo_in_non_tactical(self):
        mcp_server.start_combat(
            improvised=[{"name": "兵", "archetype": "brute_low", "count": 1}])  # 非战术
        r = mcp_server.declare_intent(actor="player", intent="move", target="retreat")
        self.assertFalse(any(e["detail"].get("opportunity") for e in r["events"]))


class TacticalR3Test(unittest.TestCase):
    """§14-R3：蓄力/打断（windup/release/poise/stagger）+ 敌人战术 AI。"""

    def setUp(self):
        self.assertTrue(mcp_server.start_game("aincrad")["ok"])

    def tearDown(self):
        if mcp_server.SESSION.in_combat:
            mcp_server.end_combat(reason="t")

    def _elite(self, max_poise=4, reach=1, e_rank=0):
        mcp_server.start_combat(tactical=True, rank_depth=2, improvised=[
            {"name": "石巨像", "archetype": "brute_mid", "count": 1,
             "rank": e_rank, "reach": reach, "max_poise": max_poise}])
        enc = mcp_server.SESSION.encounter
        eid = next(c for c in enc.combatants if c.startswith("enemy_"))
        enc.combatants["player"].hp = 100
        enc.combatants[eid].hp = enc.combatants[eid].max_hp = 100
        return enc, eid

    def _activate(self, cid):
        enc = mcp_server.SESSION.encounter
        enc.active_idx = enc.turn_order.index(cid)
        c = enc.combatants[cid]; c.acted_major = c.acted_minor = False

    # ── 削韧 / 破防 ──
    def test_poise_break_staggers_and_cancels_windup(self):
        enc, eid = self._elite(max_poise=3)
        e = enc.combatants[eid]; e.windup = {"target": "player"}
        events = []
        self.assertTrue(mcp_server._apply_poise(e, 3, events))   # 削满
        self.assertTrue(e.staggered)
        self.assertIsNone(e.windup)                              # 蓄力被打断
        self.assertEqual(e.poise, 0)
        self.assertTrue(any(ev.kind == "staggered" and ev.detail.get("windup_cancelled")
                            for ev in events))

    def test_normal_mob_has_no_poise(self):
        enc, eid = self._elite(max_poise=0)
        e = enc.combatants[eid]
        self.assertFalse(mcp_server._apply_poise(e, 99, []))     # 杂兵无韧条
        self.assertFalse(e.staggered)

    def test_attacks_accrue_poise_and_interrupt(self):
        enc, eid = self._elite(max_poise=4)
        enc.combatants[eid].windup = {"target": "player"}
        with patch("mcp_server.random.randint", side_effect=[18, 2, 18, 2]):
            self._activate("player"); mcp_server.declare_intent("player", "attack", target=eid)
            self._activate("player"); mcp_server.declare_intent("player", "attack", target=eid)
        e = enc.combatants[eid]
        self.assertTrue(e.staggered)
        self.assertIsNone(e.windup)                              # 两击削破 → 打断蓄力

    # ── 蓄力 / 释放 ──
    def test_windup_sets_telegraph(self):
        enc, eid = self._elite()
        self._activate(eid)
        r = mcp_server.declare_intent(eid, "windup", target="player")
        self.assertTrue(r["ok"])
        self.assertIsNotNone(enc.combatants[eid].windup)
        self.assertTrue(any(e["kind"] == "windup_start" for e in r["events"]))
        snap = next(c for c in r["encounter"]["combatants"] if c["id"] == eid)
        self.assertTrue(snap.get("winding_up"))

    def test_release_deals_charged_double(self):
        mcp_server.start_combat(improvised=[{"name": "靶", "archetype": "brute_low", "count": 1}])
        enc = mcp_server.SESSION.encounter
        tid = next(c for c in enc.combatants if c.startswith("enemy_"))
        enc.combatants[tid].hp = enc.combatants[tid].max_hp = 100
        self._activate("player")
        enc.combatants["player"].windup = {"target": tid, "damage_expr": "1d6",
                                           "dmg_type": "slash", "scaling": None, "reach": 99}
        with patch("mcp_server.random.randint", side_effect=[15, 3]):
            r = mcp_server.declare_intent("player", "release")
        hit = next(e for e in r["events"] if e["kind"] == "hit")
        self.assertEqual(hit["detail"]["damage"], 6)             # 1d6=3 ×2 蓄力
        self.assertTrue(hit["detail"]["charged"])
        self.assertIsNone(enc.combatants["player"].windup)       # 用掉即清

    def test_release_without_windup_errors(self):
        mcp_server.start_combat(improvised=[{"name": "靶", "archetype": "brute_low", "count": 1}])
        self._activate("player")
        self.assertFalse(mcp_server.declare_intent("player", "release")["ok"])

    # ── 敌人战术 AI ──
    def test_ai_elite_suggests_windup(self):
        enc, eid = self._elite()
        self.assertEqual(mcp_server.enemy_suggest(eid)["suggested_intent"], "windup")

    def test_ai_staggered_suggests_recover(self):
        enc, eid = self._elite()
        enc.combatants[eid].staggered = True
        self.assertEqual(mcp_server.enemy_suggest(eid)["suggested_intent"], "recover")

    def test_ai_pending_windup_suggests_release(self):
        enc, eid = self._elite()
        enc.combatants[eid].windup = {"target": "player"}
        self.assertEqual(mcp_server.enemy_suggest(eid)["suggested_intent"], "release")

    def test_ai_backline_out_of_reach_advances(self):
        # 后排近战(reach1,rank1)够不到前排玩家(rank0) → 建议前压
        enc, eid = self._elite(reach=1, e_rank=1)
        enc.combatants["player"].rank = 0
        s = mcp_server.enemy_suggest(eid)
        self.assertEqual(s["suggested_intent"], "move")
        self.assertEqual(s["suggested_target"], "advance")


if __name__ == "__main__":
    unittest.main()
