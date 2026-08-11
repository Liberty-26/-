import os
import tempfile
import unittest

import database
from memory_harness import COMPACTION_TARGET, COMPACTION_THRESHOLD, MemoryHarness


class MemoryHarnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp.name, "memory-test.db")
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        self.temp.cleanup()

    def test_replace_requires_current_revision_and_keeps_snapshot(self):
        first = MemoryHarness.read()
        self.assertEqual(first["revision"], 0)

        saved = MemoryHarness.replace("这是完整的 Agent 记忆。", first["revision"], "settings")
        self.assertTrue(saved["success"], saved)
        self.assertEqual(saved["revision"], 1)

        stale = MemoryHarness.replace("过期覆盖", 0, "settings")
        self.assertFalse(stale["success"])
        self.assertEqual(stale["code"], "stale_revision")

        conn = database.get_conn()
        try:
            version = conn.execute(
                "SELECT revision, content FROM assistant_memory_versions WHERE revision = 0"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(version["content"], "")

    def test_settings_can_clear_but_agent_candidate_cannot_be_empty(self):
        initial = MemoryHarness.read()
        cleared = MemoryHarness.replace("", initial["revision"], "settings")
        self.assertTrue(cleared["success"], cleared)

        agent = MemoryHarness.replace("", cleared["revision"], "agent")
        self.assertFalse(agent["success"])
        self.assertIn("不能为空", agent["error"])

    def test_agent_is_forced_to_compact_at_capacity_threshold(self):
        initial = MemoryHarness.read()
        full = MemoryHarness.replace("a" * COMPACTION_THRESHOLD, initial["revision"], "settings")
        self.assertTrue(full["success"], full)
        blocked = MemoryHarness.replace("b" * (COMPACTION_TARGET + 1), full["revision"], "agent")
        self.assertFalse(blocked["success"])
        self.assertEqual(blocked["code"], "compaction_required")
        compacted = MemoryHarness.replace("c" * COMPACTION_TARGET, full["revision"], "agent")
        self.assertTrue(compacted["success"], compacted)
