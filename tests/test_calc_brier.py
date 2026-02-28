"""Unit tests for src.calc.calc_brier."""
import unittest

from src.calc.calc_brier import (
    calculate_brier_score,
    calculate_delta,
    calculate_running_brier,
    get_calibration_quality,
)


class TestCalculateBrierScore(unittest.TestCase):
    """Tests for calculate_brier_score."""

    def test_perfect_prediction_returns_zero(self):
        self.assertAlmostEqual(calculate_brier_score(1.0, 1.0), 0.0)

    def test_worst_prediction_returns_one(self):
        self.assertAlmostEqual(calculate_brier_score(0.0, 1.0), 1.0)

    def test_half_prediction(self):
        # (0.5 - 1.0)^2 = 0.25
        self.assertAlmostEqual(calculate_brier_score(0.5, 1.0), 0.25)

    def test_return_type_is_float(self):
        self.assertIsInstance(calculate_brier_score(0.5, 0.5), float)

    def test_boundary_zero_zero(self):
        self.assertAlmostEqual(calculate_brier_score(0.0, 0.0), 0.0)

    def test_score_in_valid_range(self):
        score = calculate_brier_score(0.3, 0.8)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_string_raises_typeerror(self):
        with self.assertRaises(TypeError):
            calculate_brier_score("bad", 0.5)

    def test_out_of_range_raises_valueerror(self):
        with self.assertRaises(ValueError):
            calculate_brier_score(1.5, 0.5)

    def test_negative_raises_valueerror(self):
        with self.assertRaises(ValueError):
            calculate_brier_score(-0.1, 0.5)


class TestCalculateDelta(unittest.TestCase):
    """Tests for calculate_delta."""

    def test_positive_delta(self):
        self.assertAlmostEqual(calculate_delta(0.8, 0.3), 0.5)

    def test_negative_delta(self):
        self.assertAlmostEqual(calculate_delta(0.2, 0.7), -0.5)

    def test_zero_delta(self):
        self.assertAlmostEqual(calculate_delta(0.5, 0.5), 0.0)

    def test_max_delta(self):
        self.assertAlmostEqual(calculate_delta(1.0, 0.0), 1.0)

    def test_min_delta(self):
        self.assertAlmostEqual(calculate_delta(0.0, 1.0), -1.0)


class TestCalculateRunningBrier(unittest.TestCase):
    """Tests for calculate_running_brier."""

    def test_single_perfect_score(self):
        self.assertAlmostEqual(calculate_running_brier([0.0]), 0.0)

    def test_single_worst_score(self):
        self.assertAlmostEqual(calculate_running_brier([1.0]), 1.0)

    def test_average_of_multiple(self):
        # mean of [0.0, 1.0] = 0.5
        self.assertAlmostEqual(calculate_running_brier([0.0, 1.0]), 0.5)

    def test_empty_raises_valueerror(self):
        with self.assertRaises(ValueError):
            calculate_running_brier([])

    def test_out_of_range_raises_valueerror(self):
        with self.assertRaises(ValueError):
            calculate_running_brier([0.5, 1.5])

    def test_string_in_list_raises_typeerror(self):
        with self.assertRaises(TypeError):
            calculate_running_brier([0.5, "bad"])


class TestGetCalibrationQuality(unittest.TestCase):
    """Tests for get_calibration_quality."""

    def test_excellent(self):
        self.assertEqual(get_calibration_quality(0.05), "Excellent")

    def test_good(self):
        self.assertEqual(get_calibration_quality(0.15), "Good")

    def test_fair(self):
        self.assertEqual(get_calibration_quality(0.25), "Fair")

    def test_poor(self):
        self.assertEqual(get_calibration_quality(0.5), "Poor")

    def test_boundary_0(self):
        self.assertEqual(get_calibration_quality(0.0), "Excellent")

    def test_boundary_1(self):
        self.assertEqual(get_calibration_quality(1.0), "Poor")

    def test_boundary_010(self):
        self.assertEqual(get_calibration_quality(0.1), "Good")

    def test_boundary_030(self):
        self.assertEqual(get_calibration_quality(0.3), "Fair")

    def test_string_raises_typeerror(self):
        with self.assertRaises(TypeError):
            get_calibration_quality("good")

    def test_out_of_range_raises_valueerror(self):
        with self.assertRaises(ValueError):
            get_calibration_quality(1.5)


if __name__ == "__main__":
    unittest.main()
