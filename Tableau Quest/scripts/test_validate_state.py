#!/usr/bin/env python3

import unittest

from validate_state import validate


def valid_state():
    return {
        "mode": "single", "depth": "blitz", "lite": False,
        "experience": "intermediate", "tone": "straightforward",
        "focus": "performance", "audience": "mixed", "current_beat": "resolution",
        "decision_count": 3, "ended": True, "scars": [], "deferred_consequences": [],
        "judgment_signals": {"risk": "balanced", "governance": "medium", "empathy": "high",
                             "evidence": "strong", "repair": "consistent"},
    }


class StateTests(unittest.TestCase):
    def test_valid_completed_blitz(self):
        self.assertTrue(validate(valid_state())["valid"])

    def test_rejects_campaign_lite(self):
        state = valid_state()
        state.update(mode="campaign", lite=True)
        with self.assertRaisesRegex(ValueError, "incompatible"):
            validate(state)

    def test_rejects_early_ending(self):
        state = valid_state()
        state["decision_count"] = 2
        with self.assertRaisesRegex(ValueError, "before"):
            validate(state)

    def test_allows_interrupted_scenario(self):
        state = valid_state()
        state.update(ended=False, decision_count=1)
        self.assertTrue(validate(state)["valid"])


if __name__ == "__main__":
    unittest.main()
