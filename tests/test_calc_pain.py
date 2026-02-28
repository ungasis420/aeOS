"""Unit tests for src.calc.calc_pain."""
import unittest

from src.calc.calc_pain import (
    SOLUTION_BRIDGE_THRESHOLD,
    calculate_pain_score,
    get_pain_threshold_action,
    validate_pain_inputs,
)


class TestValidatePainInputs(unittest.TestCase):
    """Tests for validate_pain_inputs."""

    def test_valid_slider_inputs(self):
        ok, errors = validate_pain_inputs(8, 7, True, 6)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_valid_normalized_inputs(self):
        ok, errors = validate_pain_inputs(0.8, 0.7, False, 0.6)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_rejects_string_severity(self):
        ok, errors = validate_pain_inputs("high", 5, True, 5)
        self.assertFalse(ok)
        self.assertTrue(any("severity" in e for e in errors))

    def test_rejects_bool_severity(self):
        ok, errors = validate_pain_inputs(True, 5, True, 5)
        self.assertFalse(ok)
        self.assertTrue(any("severity" in e for e in errors))

    def test_rejects_negative_value(self):
        ok, errors = validate_pain_inputs(-1, 5, True, 5)
        self.assertFalse(ok)
        self.assertTrue(any(">= 0" in e for e in errors))

    def test_rejects_value_over_10(self):
        ok, errors = validate_pain_inputs(11, 5, True, 5)
        self.assertFalse(ok)
        self.assertTrue(any("<= 10" in e for e in errors))

    def test_rejects_mixed_scales(self):
        ok, errors = validate_pain_inputs(0.5, 7, True, 5)
        self.assertFalse(ok)
        self.assertTrue(any("mix" in e.lower() for e in errors))


class TestCalculatePainScore(unittest.TestCase):
    """Tests for calculate_pain_score."""

    def test_slider_known_result(self):
        # (8/10)*40 + (7/10)*30 + 20 + (8/10)*10 = 32+21+20+8 = 81
        score = calculate_pain_score(8, 7, True, 8)
        self.assertAlmostEqual(score, 81.0)

    def test_normalized_known_result(self):
        score = calculate_pain_score(0.8, 0.7, True, 0.8)
        self.assertAlmostEqual(score, 81.0)

    def test_return_type_is_float(self):
        score = calculate_pain_score(5, 5, False, 5)
        self.assertIsInstance(score, float)

    def test_zero_inputs_give_zero(self):
        # All zeros (slider): (0/10)*40 + (0/10)*30 + 0 + (0/10)*10 = 0
        # But 0,0,0 are all int-like and <= 1 → slider scale, so 0/10=0
        score = calculate_pain_score(0, 0, False, 0)
        self.assertAlmostEqual(score, 0.0)

    def test_max_slider_inputs(self):
        # (10/10)*40 + (10/10)*30 + 20 + (10/10)*10 = 40+30+20+10 = 100
        score = calculate_pain_score(10, 10, True, 10)
        self.assertAlmostEqual(score, 100.0)

    def test_score_in_valid_range(self):
        score = calculate_pain_score(5, 5, True, 5)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_invalid_input_raises_valueerror(self):
        with self.assertRaises(ValueError):
            calculate_pain_score("bad", 5, True, 5)

    def test_negative_input_raises_valueerror(self):
        with self.assertRaises(ValueError):
            calculate_pain_score(-1, 5, True, 5)


class TestGetPainThresholdAction(unittest.TestCase):
    """Tests for get_pain_threshold_action."""

    def test_below_threshold_stays_phase0(self):
        result = get_pain_threshold_action(30, False)
        self.assertEqual(result["next_phase"], "Phase_0")

    def test_at_threshold_without_monetize_goes_phase1(self):
        result = get_pain_threshold_action(SOLUTION_BRIDGE_THRESHOLD, False)
        self.assertEqual(result["next_phase"], "Phase_1")

    def test_at_threshold_with_monetize_goes_phase2(self):
        result = get_pain_threshold_action(SOLUTION_BRIDGE_THRESHOLD, True)
        self.assertEqual(result["next_phase"], "Phase_2")

    def test_high_score_with_monetize_goes_phase2(self):
        result = get_pain_threshold_action(100, True)
        self.assertEqual(result["next_phase"], "Phase_2")

    def test_returns_dict_with_expected_keys(self):
        result = get_pain_threshold_action(50, False)
        self.assertIn("recommended_action", result)
        self.assertIn("next_phase", result)

    def test_invalid_score_raises_valueerror(self):
        with self.assertRaises(ValueError):
            get_pain_threshold_action("bad", False)

    def test_invalid_flag_raises_valueerror(self):
        with self.assertRaises(ValueError):
            get_pain_threshold_action(70, "yes")


if __name__ == "__main__":
    unittest.main()
