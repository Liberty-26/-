import unittest

from agent_runtime import AgentRunState


WRITE_ARGS = {
    "filepath": "对账单.xlsx",
    "sheet": "水电",
    "mode": "new",
    "items": [{"name": "钢管", "spec": "DN50", "unit": "米", "qty": 1, "price": 10}],
}


class AgentRunStateTest(unittest.TestCase):
    def test_read_tool_is_normalized_and_allowed(self):
        state = AgentRunState("查一下最近的单据")
        ok, reason, args = state.authorize("db_lookup_receipt", {"limit": 999})
        self.assertTrue(ok, reason)
        self.assertEqual(args["limit"], 50)

    def test_write_requires_explicit_intent_or_confirmed_selection(self):
        state = AgentRunState("查一下最近的单据")
        ok, reason, _ = state.authorize("spreadsheet_write_batch", WRITE_ARGS)
        self.assertFalse(ok)
        self.assertIn("明确写入授权", reason)

        selected = AgentRunState("查一下最近的单据", selected_ids=[12])
        ok, reason, _ = selected.authorize("spreadsheet_write_batch", WRITE_ARGS)
        self.assertTrue(ok, reason)

    def test_negative_write_instruction_does_not_authorize(self):
        state = AgentRunState("先别写入，给我看看内容")
        ok, _, _ = state.authorize("spreadsheet_write_batch", WRITE_ARGS)
        self.assertFalse(ok)

    def test_short_followup_inherits_recent_write_intent(self):
        state = AgentRunState(
            "四张，就在桌面",
            recent_user_messages=["我把文件存放位置切换了，你重新做一份吧"],
        )
        self.assertTrue(state.write_authorized)

    def test_memory_requires_explicit_request(self):
        state = AgentRunState("我喜欢按日期排序")
        ok, reason, _ = state.authorize("memory_replace", {
            "content": "偏好按日期排序", "expected_revision": 0,
        })
        self.assertFalse(ok)
        self.assertIn("长期记忆", reason)

        explicit = AgentRunState("请记住：以后默认按日期排序")
        ok, reason, _ = explicit.authorize("memory_replace", {
            "content": "默认按日期排序", "expected_revision": 0,
        })
        self.assertFalse(ok)
        self.assertIn("先读取", reason)

        explicit.record("memory_list", {"success": True, "revision": 7})
        ok, reason, args = explicit.authorize("memory_replace", {
            "content": "默认按日期排序", "expected_revision": 7,
        })
        self.assertTrue(ok, reason)
        self.assertEqual(args["expected_revision"], 7)

    def test_memory_write_rejects_stale_or_fabricated_revision(self):
        state = AgentRunState("请记住：默认按日期排序")
        state.record("memory_list", {"success": True, "revision": 3})
        ok, reason, _ = state.authorize("memory_replace", {
            "content": "默认按日期排序", "expected_revision": 2,
        })
        self.assertFalse(ok)
        self.assertIn("版本已变化", reason)

    def test_duplicate_mutation_is_blocked(self):
        state = AgentRunState("把单据写入对账单")
        ok, reason, _ = state.authorize("spreadsheet_write_batch", WRITE_ARGS)
        self.assertTrue(ok, reason)
        ok, reason, _ = state.authorize("spreadsheet_write_batch", WRITE_ARGS)
        self.assertFalse(ok)
        self.assertIn("重复执行", reason)

    def test_only_verified_write_allows_export(self):
        state = AgentRunState("把单据写入对账单", selected_ids=[12])
        state.record("spreadsheet_write_batch", {"success": True, "verified": False})
        self.assertFalse(state.export_confirmed)
        state.record("spreadsheet_write_batch", {"success": True, "verified": True})
        self.assertTrue(state.export_confirmed)

    def test_atomic_export_requires_ids_and_tracks_verified_receipts(self):
        state = AgentRunState("把单据写入对账单")
        ok, reason, _ = state.authorize("spreadsheet_export_receipts", {
            "filepath": "对账单.xlsx", "sheet": "水电", "mode": "new", "receipt_ids": [],
        })
        self.assertFalse(ok)
        self.assertIn("receipt_ids", reason)

        state = AgentRunState("把单据写入对账单")
        ok, reason, _ = state.authorize("spreadsheet_export_receipts", {
            "filepath": "对账单.xlsx", "sheet": "水电", "mode": "new", "receipt_ids": [4, 4, 9],
        })
        self.assertTrue(ok, reason)
        state.record("spreadsheet_export_receipts", {"success": True, "verified": True, "receipt_ids": [4, 9]})
        self.assertEqual(state.verified_receipt_ids, {4, 9})


if __name__ == "__main__":
    unittest.main()
