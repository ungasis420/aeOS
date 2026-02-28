"""Unit tests for src.calc.calc_bestmoves."""
import unittest

from src.calc.calc_bestmoves import (
    calculate_v70,
    calculate_v75,
    get_bias_multiplier,
    get_fresh_multiplier,
    get_pain_multiplier,
)


class TestGetPainMultiplier(unittest.TestCase):
    """Tests for get_pain_multiplier."""

    def test_no_linkage_returns_075(self):
        self.assertEqual(get_pain_multiplier(80, False), 0.75)

    def test_high_pain_returns_135(self):
        self.assertEqual(get_pain_multiplier(70, True), 1.35)

    def test_mid_pain_returns_115(self):
        self.assertEqual(get_pain_multiplier(50, True), 1.15)

    def test_low_pain_returns_100(self):
        self.assertEqual(get_pain_multiplier(30, True), 1.00)

    def test_missing_linkage_defaults_100(self):
        self.assertEqual(get_pain_multiplier(80, None), 1.00)

    def test_missing_score_with_linkage_defaults_100(self):
        self.assertEqual(get_pain_multiplier(None, True), 1.00)

    def test_boundary_pain_0(self):
        self.assertEqual(get_pain_multiplier(0, True), 1.00)

    def test_boundary_pain_100(self):
        self.assertEqual(get_pain_multiplier(100, True), 1.35)

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            get_pain_multiplier(101, True)


class TestGetBiasMultiplier(unittest.TestCase):
    """Tests for get_bias_multiplier."""

    def test_low_bias_returns_100(self):
        self.assertEqual(get_bias_multiplier(10), 1.00)

    def test_bias_20_returns_095(self):
        self.assertEqual(get_bias_multiplier(20), 0.95)

    def test_bias_40_returns_085(self):
        self.assertEqual(get_bias_multiplier(40), 0.85)

    def test_bias_60_returns_070(self):
        self.assertEqual(get_bias_multiplier(60), 0.70)

    def test_bias_80_returns_050(self):
        self.assertEqual(get_bias_multiplier(80), 0.50)

    def test_missing_defaults_100(self):
        self.assertEqual(get_bias_multiplier(None), 1.00)

    def test_boundary_0(self):
        self.assertEqual(get_bias_multiplier(0), 1.00)

    def test_boundary_100(self):
        self.assertEqual(get_bias_multiplier(100), 0.50)

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            get_bias_multiplier(101)


class TestGetFreshMultiplier(unittest.TestCase):
    """Tests for get_fresh_multiplier."""

    def test_fresh_0_days(self):
        self.assertEqual(get_fresh_multiplier(0), 1.00)

    def test_fresh_30_days(self):
        self.assertEqual(get_fresh_multiplier(30), 1.00)

    def test_fresh_31_days(self):
        self.assertEqual(get_fresh_multiplier(31), 0.95)

    def test_fresh_90_days(self):
        self.assertEqual(get_fresh_multiplier(90), 0.88)

    def test_fresh_180_days(self):
        self.assertEqual(get_fresh_multiplier(180), 0.75)

    def test_fresh_365_days(self):
        self.assertEqual(get_fresh_multiplier(365), 0.60)

    def test_fresh_366_days(self):
        self.assertEqual(get_fresh_multiplier(366), 0.40)

    def test_missing_defaults_100(self):
        self.assertEqual(get_fresh_multiplier(None), 1.00)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            get_fresh_multiplier(-1)

    def test_float_raises_typeerror(self):
        with self.assertRaises(TypeError):
            get_fresh_multiplier(30.5)


class TestCalculateV70(unittest.TestCase):
    """Tests for calculate_v70."""

    def test_known_result(self):
        # 50*0.35 + 60*0.35 + 70*0.30 = 17.5+21+21 = 59.5
        self.assertAlmostEqual(calculate_v70(50, 60, 70), 59.5)

    def test_all_zeros(self):
        self.assertAlmostEqual(calculate_v70(0, 0, 0), 0.0)

    def test_all_100(self):
        # 100*0.35 + 100*0.35 + 100*0.30 = 35+35+30 = 100
        self.assertAlmostEqual(calculate_v70(100, 100, 100), 100.0)

    def test_return_type_is_float(self):
        self.assertIsInstance(calculate_v70(50, 50, 50), float)

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            calculate_v70(101, 50, 50)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            calculate_v70(-1, 50, 50)

    def test_string_raises_typeerror(self):
        with self.assertRaises(TypeError):
            calculate_v70("bad", 50, 50)


class TestCalculateV75(unittest.TestCase):
    """Tests for calculate_v75."""

    def test_returns_dict_with_expected_keys(self):
        result = calculate_v75(50, 60, 70, 80, True, 10, 5)
        for key in ("qBestMoves_v70", "PainM", "BiasM", "FreshM",
                     "qBestMoves_v75", "data_quality_flags"):
            self.assertIn(key, result)

    def test_v75_equals_v70_when_all_multipliers_default(self):
        result = calculate_v75(50, 60, 70, None, None, None, None)
        self.assertAlmostEqual(result["qBestMoves_v75"], result["qBestMoves_v70"])

    def test_missing_inputs_produce_quality_flags(self):
        result = calculate_v75(50, 60, 70, None, None, None, None)
        self.assertTrue(len(result["data_quality_flags"]) > 0)

    def test_no_flags_when_all_present(self):
        result = calculate_v75(50, 60, 70, 80, True, 10, 5)
        self.assertEqual(result["data_quality_flags"], [])

    def test_v75_less_than_v70_with_penalties(self):
        result = calculate_v75(50, 60, 70, 80, False, 80, 366)
        self.assertLess(result["qBestMoves_v75"], result["qBestMoves_v70"])


if __name__ == "__main__":
    unittest.main()
