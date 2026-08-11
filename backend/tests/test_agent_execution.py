import os
import tempfile
import unittest

from agent import AGENT_TOOLS, execute_tool
import config
from spreadsheet import export_receipts


class AgentExecutionTest(unittest.TestCase):
    def test_write_tool_always_returns_verification_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filepath = os.path.join(temp_dir, "对账单.xlsx")
            old_work_dir = config.WORK_DIR
            config.WORK_DIR = temp_dir
            try:
                result = execute_tool("spreadsheet_write_batch", {
                    "filepath": filepath,
                    "sheet": "水电",
                    "mode": "new",
                    "start_row": 2,
                    "seq": 1,
                    "receipt_no": "0001",
                    "date": "2026-08-11",
                    "items": [{"name": "镀锌管", "spec": "DN50", "unit": "米", "qty": 2, "price": 10}],
                })
            finally:
                config.WORK_DIR = old_work_dir

            self.assertTrue(result["success"], result)
            self.assertTrue(result["verified"], result)
            self.assertEqual(result["verification"]["row_count"], 1)
            self.assertEqual(result["verification"]["total_amount"], 20)
            self.assertTrue(os.path.exists(filepath))

    def test_atomic_export_uses_authoritative_receipt_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filepath = os.path.join(temp_dir, "批量对账单.xlsx")
            result = export_receipts(filepath, "水电", "new", [
                {"id": 101, "receipt_no": "A001", "date": "2026-08-11", "items": [
                    {"name": "钢管", "spec": "DN50", "unit": "米", "qty": 2, "price": 10},
                ]},
                {"id": 102, "receipt_no": "A002", "date": "2026-08-11", "items": [
                    {"name": "角钢", "spec": "50×5", "unit": "支", "qty": 3, "price": 20},
                ]},
            ])
            self.assertTrue(result["success"], result)
            self.assertTrue(result["verified"], result)
            self.assertEqual(result["receipt_ids"], [101, 102])
            self.assertEqual(result["item_count"], 2)
            self.assertEqual(result["total_amount"], 80)

    def test_new_export_does_not_recreate_deleted_work_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            deleted_dir = os.path.join(temp_dir, "deleted")
            old_work_dir = config.WORK_DIR
            config.WORK_DIR = deleted_dir
            try:
                result = execute_tool("spreadsheet_export_receipts", {
                    "filepath": "对账单.xlsx",
                    "sheet": "对账单",
                    "mode": "new",
                    "receipt_ids": [101],
                })
            finally:
                config.WORK_DIR = old_work_dir

            self.assertFalse(result["success"], result)
            self.assertIn("工作目录不存在", result["error"])
            self.assertFalse(os.path.exists(deleted_dir))

    def test_model_tool_surface_hides_low_level_write_primitives(self):
        names = {tool["function"]["name"] for tool in AGENT_TOOLS}
        self.assertIn("spreadsheet_export_receipts", names)
        self.assertNotIn("spreadsheet_write_batch", names)
        self.assertNotIn("spreadsheet_create_new", names)


if __name__ == "__main__":
    unittest.main()
