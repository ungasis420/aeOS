"""Unit tests for src.calc.calc_calibration."""
import unittest

from src.calc.calc_calibration import CalibrationTracker


class TestCalibrationTrackerUpdate(unittest.TestCase):
    """Tests for CalibrationTracker.update."""

    def test_single_perfect_prediction(self):
        t = CalibrationTracker()
        score = t.update(1.0, 1)
        self.assertAlmostEqual(score, 0.0)

    def test_single_worst_prediction(self):
        t = CalibrationTracker()
        score = t.update(0.0, 1)
        self.assertAlmostEqual(score, 1.0)

    def test_running_mean_two_updates(self):
        t = CalibrationTracker()
        t.update(1.0, 1)  # score=0.0
        mean = t.update(0.0, 1)  # score=1.0, mean=0.5
        self.assertAlmostEqual(mean, 0.5)

    def test_return_type_is_float(self):
        t = CalibrationTracker()
        result = t.update(0.5, 0)
        self.assertIsInstance(result, float)

    def test_boundary_predicted_0(self):
        t = CalibrationTracker()
        score = t.update(0.0, 0)
        self.assertAlmostEqual(score, 0.0)

    def test_boundary_predicted_1(self):
        t = CalibrationTracker()
        score = t.update(1.0, 0)
        self.assertAlmostEqual(score, 1.0)

    def test_bool_predicted_raises_typeerror(self):
        t = CalibrationTracker()
        with self.assertRaises(TypeError):
            t.update(True, 1)

    def test_string_predicted_raises_typeerror(self):
        t = CalibrationTracker()
        with self.assertRaises(TypeError):
            t.update("0.5", 1)

    def test_out_of_range_predicted_raises_valueerror(self):
        t = CalibrationTracker()
        with self.assertRaises(ValueError):
            t.update(1.5, 1)

    def test_invalid_actual_raises_valueerror(self):
        t = CalibrationTracker()
        with self.assertRaises(ValueError):
            t.update(0.5, 2)

    def test_bool_actual_raises_typeerror(self):
        t = CalibrationTracker()
        with self.assertRaises(TypeError):
            t.update(0.5, True)


class TestCalibrationTrackerGetScore(unittest.TestCase):
    """Tests for CalibrationTracker.get_score."""

    def test_empty_tracker_returns_zero(self):
        t = CalibrationTracker()
        self.assertAlmostEqual(t.get_score(), 0.0)

    def test_after_updates(self):
        t = CalibrationTracker()
        t.update(0.9, 1)
        score = t.get_score()
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestCalibrationTrackerReset(unittest.TestCase):
    """Tests for CalibrationTracker.reset."""

    def test_reset_clears_score(self):
        t = CalibrationTracker()
        t.update(0.5, 1)
        t.reset()
        self.assertAlmostEqual(t.get_score(), 0.0)

    def test_reset_clears_history(self):
        t = CalibrationTracker()
        t.update(0.5, 1)
        t.reset()
        self.assertEqual(t.get_history(), [])


class TestCalibrationTrackerSerialization(unittest.TestCase):
    """Tests for to_dict / from_dict round-trip."""

    def test_round_trip_preserves_score(self):
        t = CalibrationTracker()
        t.update(0.8, 1)
        t.update(0.3, 0)
        data = t.to_dict()
        restored = CalibrationTracker.from_dict(data)
        self.assertAlmostEqual(restored.get_score(), t.get_score())

    def test_round_trip_preserves_history_length(self):
        t = CalibrationTracker()
        t.update(0.7, 1)
        t.update(0.2, 0)
        data = t.to_dict()
        restored = CalibrationTracker.from_dict(data)
        self.assertEqual(len(restored.get_history()), 2)

    def test_from_dict_invalid_type_raises(self):
        with self.assertRaises(TypeError):
            CalibrationTracker.from_dict("not a dict")

    def test_from_dict_bad_history_entry_raises(self):
        with self.assertRaises(ValueError):
            CalibrationTracker.from_dict({"history": [[0.5]]})


class TestCalibrationTrackerSummary(unittest.TestCase):
    """Tests for CalibrationTracker.summary."""

    def test_summary_keys(self):
        t = CalibrationTracker()
        t.update(0.5, 1)
        s = t.summary()
        for key in ("count", "mean_score", "best_score", "worst_score"):
            self.assertIn(key, s)

    def test_summary_count(self):
        t = CalibrationTracker()
        t.update(0.9, 1)
        t.update(0.1, 0)
        self.assertEqual(t.summary()["count"], 2)

    def test_empty_summary(self):
        t = CalibrationTracker()
        s = t.summary()
        self.assertEqual(s["count"], 0)
        self.assertIsNone(s["best_score"])
        self.assertIsNone(s["worst_score"])


if __name__ == "__main__":
    unittest.main()
