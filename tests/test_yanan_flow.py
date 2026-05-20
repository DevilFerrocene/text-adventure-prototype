import unittest
from pathlib import Path

import mcp_server


def object_ids(scene_result):
    return {obj["id"] for obj in scene_result["scene"]["objects"]}


def inventory_ids(result):
    return {item["id"] for item in result["inventory"]}


class YananFlowTest(unittest.TestCase):
    def setUp(self):
        result = mcp_server.start_game()
        self.assertTrue(result["ok"])

    def test_read_letter_reveals_takeable_dock_key(self):
        result = mcp_server.call_affordance("sealed_letter", "read")
        self.assertTrue(result["ok"])
        self.assertIn("dock_key", object_ids(result))

        take_result = mcp_server.take_item("dock_key")
        self.assertTrue(take_result["ok"])
        self.assertIn("dock_key", inventory_ids(take_result))
        self.assertNotIn("dock_key", object_ids(take_result))

    def test_hidden_items_cannot_be_taken_before_reveal(self):
        result = mcp_server.take_item("dock_key")
        self.assertFalse(result["ok"])

    def test_inspect_object_adds_hidden_clue_once(self):
        first = mcp_server.inspect_object("cracked_window")
        self.assertTrue(first["ok"])
        self.assertIn("noticed_tower_light", first["flags_set"])

        second = mcp_server.inspect_object("cracked_window")
        self.assertTrue(second["ok"])
        self.assertEqual(second["clues_added"], [])

    def test_minimal_happy_path_reaches_warehouse(self):
        self.assertTrue(mcp_server.call_affordance("sealed_letter", "read")["ok"])
        self.assertTrue(mcp_server.take_item("dock_key")["ok"])
        self.assertTrue(mcp_server.move("south")["ok"])
        self.assertTrue(mcp_server.move("south")["ok"])

        locked = mcp_server.move("east")
        self.assertFalse(locked["ok"])

        unlock = mcp_server.call_affordance("dock_key", "show")
        self.assertTrue(unlock["ok"])
        self.assertFalse(unlock["scene"]["exits"]["east"]["locked"])

        moved = mcp_server.move("east")
        self.assertTrue(moved["ok"])
        self.assertEqual(mcp_server.get_state()["position"], "warehouse")

    def test_initial_world_model_context(self):
        result = mcp_server.start_game()
        context = result["state_context"]

        self.assertEqual(context["vitals"]["gold"], 50000)
        self.assertEqual(context["world_time"]["phase"], "deep_night")
        self.assertEqual(context["world_time"]["weather"], "heavy_rain")
        self.assertEqual(context["quest_log"][0]["id"], "assassination_contract")
        self.assertEqual(context["quest_log"][0]["stage"], "received_contract")
        self.assertEqual(result["scene"]["area"], "亚楠下层区")
        self.assertEqual(result["scene"]["coords"], [0, 0])

        letter = result["inventory"][0]
        self.assertEqual(letter["kind"], "document")
        self.assertIn("quest_item", letter["named_tags"])

    def test_world_time_advances_with_turns(self):
        start = mcp_server.get_state()["state_context"]["world_time"]["minute"]
        result = mcp_server.inspect_object("cracked_window")
        self.assertTrue(result["ok"])
        self.assertEqual(mcp_server.get_state()["state_context"]["world_time"]["minute"], start + 5)

    def test_custom_attributes_can_extend_player_and_world_context(self):
        crit = mcp_server.set_custom_attribute(
            scope="player",
            key="crit_rate",
            value="0.15",
            value_type="float",
            label="暴击率",
            note="临时战斗规则用。",
        )
        self.assertTrue(crit["ok"])
        self.assertEqual(crit["attribute"]["value"], 0.15)

        omen = mcp_server.set_custom_attribute(
            scope="world",
            key="celestial_omen",
            value="血月被煤烟遮蔽",
            value_type="text",
            label="天象",
        )
        self.assertTrue(omen["ok"])

        context = mcp_server.get_state()["state_context"]["custom"]
        self.assertEqual(context["player_attrs"]["crit_rate"]["label"], "暴击率")
        self.assertEqual(context["world_attrs"]["celestial_omen"]["value"], "血月被煤烟遮蔽")

    def test_custom_attributes_round_trip_through_save(self):
        self.assertTrue(mcp_server.set_custom_attribute(
            scope="world",
            key="moon_phase",
            value="waning",
            value_type="text",
        )["ok"])
        saved = mcp_server.save_game("custom_attr_test")
        self.assertTrue(saved["ok"])

        loaded = mcp_server.load_game("custom_attr_test")
        self.assertTrue(loaded["ok"])
        attrs = loaded["state_context"]["custom"]["world_attrs"]
        self.assertEqual(attrs["moon_phase"]["value"], "waning")
        Path(saved["path"]).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
