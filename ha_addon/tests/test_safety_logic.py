"""Safe/unsafe evaluation of the Home Assistant add-on (ha_addon/safety_logic.py)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the ha_addon folder

from safety_logic import (  # noqa: E402
    MIN_STALE_AFTER,
    SafeCondition,
    SafetyTracker,
    parse_safe_conditions,
    reading_is_safe,
    stale_after_for,
)


def tracker(safe_wait=300, unsafe_wait=0, stale_after=180, labels=None, now=0.0):
    conditions, _ = parse_safe_conditions(labels or [{"label": "Clear", "threshold": 50}])
    return SafetyTracker(conditions, safe_wait, unsafe_wait, stale_after, now)


class ParseSafeConditionsTest(unittest.TestCase):

    def test_dicts_and_plain_strings(self):
        conditions, problems = parse_safe_conditions([{"label": " Clear ", "threshold": 60}, "Wisps"])
        self.assertEqual(conditions, [SafeCondition("clear", 60.0), SafeCondition("wisps", 50.0)])
        self.assertEqual(problems, [])

    def test_empty_label_is_ignored_and_reported(self):
        conditions, problems = parse_safe_conditions([{"label": "", "threshold": 50}, {"label": "  "}])
        self.assertEqual(conditions, [])
        self.assertEqual(len(problems), 2)

    def test_bad_threshold_falls_back_to_default(self):
        conditions, problems = parse_safe_conditions([{"label": "Clear", "threshold": "high"}])
        self.assertEqual(conditions, [SafeCondition("clear", 50.0)])
        self.assertEqual(len(problems), 1)

    def test_none_gives_nothing(self):
        self.assertEqual(parse_safe_conditions(None), ([], []))


class ReadingIsSafeTest(unittest.TestCase):

    def setUp(self):
        self.conditions, _ = parse_safe_conditions([{"label": "Clear", "threshold": 50}])

    def test_exact_label_ignoring_case_and_spaces(self):
        self.assertTrue(reading_is_safe(" clear ", 80, self.conditions))

    def test_label_that_only_contains_the_configured_one_is_not_safe(self):
        self.assertFalse(reading_is_safe("Not Clear", 99, self.conditions))
        self.assertFalse(reading_is_safe("Partly Clear", 99, self.conditions))

    def test_threshold_is_inclusive(self):
        self.assertTrue(reading_is_safe("Clear", 50, self.conditions))
        self.assertFalse(reading_is_safe("Clear", 49.99, self.conditions))

    def test_no_conditions_is_never_safe(self):
        self.assertFalse(reading_is_safe("Clear", 100, []))


class SafetyTrackerWaitTimesTest(unittest.TestCase):

    def test_safe_is_released_only_after_the_safe_wait(self):
        t = tracker(safe_wait=300)
        self.assertFalse(t.on_result("Clear", 90, 0))
        self.assertIsNone(t.reported)
        self.assertFalse(t.on_result("Clear", 90, 299))
        self.assertTrue(t.on_result("Clear", 90, 300))
        self.assertIs(t.reported, True)

    def test_unsafe_is_released_at_once_with_wait_zero(self):
        t = tracker()
        self.assertTrue(t.on_result("Overcast", 90, 0))
        self.assertIs(t.reported, False)

    def test_safe_to_unsafe_uses_the_unsafe_wait(self):
        t = tracker(safe_wait=0, unsafe_wait=120)
        t.on_result("Clear", 90, 0)
        self.assertIs(t.reported, True)
        self.assertFalse(t.on_result("Overcast", 90, 10))
        self.assertIs(t.reported, True)
        self.assertFalse(t.on_result("Overcast", 90, 129))
        self.assertTrue(t.on_result("Overcast", 90, 130))
        self.assertIs(t.reported, False)

    def test_interrupted_safe_confirmation_starts_over(self):
        t = tracker(safe_wait=300)
        t.on_result("Overcast", 90, 0)  # reported unsafe
        t.on_result("Clear", 90, 10)
        t.on_result("Overcast", 90, 110)  # interrupts
        t.on_result("Clear", 90, 160)
        self.assertFalse(t.on_result("Clear", 90, 459))
        self.assertTrue(t.on_result("Clear", 90, 460))

    def test_a_blip_that_returns_to_the_reported_state_leaves_no_timer(self):
        # Reported safe, one unsafe reading while unsafe_wait is running, then safe again:
        # nothing is pending and SAFE does not have to be confirmed for safe_wait again.
        t = tracker(safe_wait=300, unsafe_wait=120)
        t.on_result("Clear", 90, 0)
        t.on_result("Clear", 90, 300)
        self.assertIs(t.reported, True)
        t.on_result("Overcast", 90, 360)
        self.assertEqual(t.snapshot(360)["pending_target"], "unsafe")
        t.on_result("Clear", 90, 420)
        self.assertIs(t.reported, True)
        self.assertFalse(t.snapshot(420)["is_pending"])

    def test_snapshot_counts_down(self):
        t = tracker(safe_wait=300)
        t.on_result("Clear", 90, 0)
        snap = t.snapshot(100)
        self.assertTrue(snap["is_pending"])
        self.assertEqual(snap["pending_target"], "safe")
        self.assertEqual(snap["countdown_total"], 300)
        self.assertEqual(snap["countdown_remaining"], 200)

    def test_low_confidence_counts_as_unsafe(self):
        t = tracker()
        t.on_result("Clear", 40, 0)
        self.assertIs(t.reported, False)


class SafetyTrackerFailSafeTest(unittest.TestCase):

    def safe_tracker(self):
        t = tracker(safe_wait=0, stale_after=180)
        t.on_result("Clear", 90, 0)
        self.assertIs(t.reported, True)
        return t

    def test_short_failures_keep_the_state(self):
        t = self.safe_tracker()
        self.assertFalse(t.on_failure(60))
        self.assertFalse(t.on_failure(179))
        self.assertIs(t.reported, True)

    def test_state_falls_back_to_unsafe_after_the_limit(self):
        t = self.safe_tracker()
        self.assertTrue(t.on_failure(180))
        self.assertIs(t.reported, False)
        self.assertFalse(t.on_failure(240))  # already reported, no further change

    def test_failure_before_any_reading_reports_unsafe_after_the_limit(self):
        t = tracker(stale_after=180)
        self.assertFalse(t.on_failure(100))
        self.assertIsNone(t.reported)
        self.assertTrue(t.on_failure(180))
        self.assertIs(t.reported, False)

    def test_recovery_needs_the_safe_wait_again(self):
        t = tracker(safe_wait=300, stale_after=180)
        t.on_result("Clear", 90, 0)
        t.on_result("Clear", 90, 300)
        self.assertIs(t.reported, True)
        t.on_failure(480)
        self.assertIs(t.reported, False)
        self.assertFalse(t.on_result("Clear", 90, 540))
        self.assertIs(t.reported, False)
        self.assertTrue(t.on_result("Clear", 90, 840))

    def test_a_confirmation_does_not_span_a_dead_camera(self):
        t = tracker(safe_wait=300, stale_after=180)
        t.on_result("Overcast", 90, 0)  # reported unsafe
        t.on_result("Clear", 90, 10)  # confirmation starts
        t.on_failure(200)  # camera dead for longer than the limit
        # First picture afterwards must not complete the old confirmation (10 + 300 < 330).
        self.assertFalse(t.on_result("Clear", 90, 330))
        self.assertIs(t.reported, False)

    def test_stale_after_has_a_floor(self):
        self.assertEqual(stale_after_for(10), MIN_STALE_AFTER)
        self.assertEqual(stale_after_for(60), 180)


if __name__ == '__main__':
    unittest.main()
