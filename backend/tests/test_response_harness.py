import unittest

from response_harness import format_reply, outcome_from_audit


class ResponseHarnessTest(unittest.TestCase):
    def test_verified_write_is_completed(self):
        audit = {"verified_writes": 1, "blocked_calls": 0, "execution_failures": []}
        self.assertEqual(outcome_from_audit(audit), "completed")
        self.assertTrue(format_reply("### 结论\n已写入。", audit).startswith("【状态：已完成】"))

    def test_blocked_call_cannot_be_reported_as_completed(self):
        audit = {"verified_writes": 0, "blocked_calls": 1, "execution_failures": []}
        self.assertEqual(outcome_from_audit(audit), "needs_confirmation")
        self.assertIn("需确认", format_reply("我已经完成了", audit))

    def test_failure_reason_is_added_from_runtime(self):
        audit = {"verified_writes": 0, "blocked_calls": 0, "execution_failures": ["文件不存在"]}
        reply = format_reply("无法处理", audit)
        self.assertIn("系统核验：文件不存在", reply)
