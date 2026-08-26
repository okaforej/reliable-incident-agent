from __future__ import annotations

import unittest

from agent import run_investigation
from evaluation import evaluate_trace


class RuntimeEvaluationTests(unittest.TestCase):
    def test_same_correct_rca_has_different_behavioral_outcomes(self) -> None:
        incident_id = "inc_checkout_db_pool_001"

        weak = evaluate_trace(run_investigation(incident_id, mode="weak"))
        reliable = evaluate_trace(run_investigation(incident_id, mode="reliable"))

        self.assertTrue(weak.rca_correct)
        self.assertFalse(weak.behavioral_slo_pass)
        self.assertTrue(reliable.rca_correct)
        self.assertTrue(reliable.behavioral_slo_pass)


if __name__ == "__main__":
    unittest.main()