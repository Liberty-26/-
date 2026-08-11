import unittest

from session_harness import MAX_SUMMARY_CHARS, SessionHarness


class SessionHarnessTest(unittest.TestCase):
    def test_rollup_is_triggered_by_code_not_model(self):
        self.assertIsNone(SessionHarness.rollup_cutoff(40, 30, 10, 0))
        self.assertEqual(SessionHarness.rollup_cutoff(41, 30, 10, 0), 11)
        self.assertIsNone(SessionHarness.rollup_cutoff(41, 30, 10, 11))

    def test_summary_candidate_has_a_hard_size_limit(self):
        result = SessionHarness.normalize_candidate("x" * (MAX_SUMMARY_CHARS + 50), "旧摘要")
        self.assertEqual(len(result), MAX_SUMMARY_CHARS)
        self.assertTrue(result.startswith("旧摘要"))
