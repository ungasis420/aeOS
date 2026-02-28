# aeOS Test Suite

Unit tests for the `src/calc/` calculation layer.

## Test files

| File | Module under test | Focus |
|---|---|---|
| `test_calc_pain.py` | `src.calc.calc_pain` | Pain Score formula, validation, threshold routing |
| `test_calc_bestmoves.py` | `src.calc.calc_bestmoves` | qBestMoves v7.0/v7.5, multipliers (Pain/Bias/Fresh) |
| `test_calc_brier.py` | `src.calc.calc_brier` | Brier Score, delta, running mean, calibration labels |
| `test_calc_calibration.py` | `src.calc.calc_calibration` | CalibrationTracker: update, reset, serialization |

## Running tests

From the project root:

```bash
# Option 1 — helper script (verbose + pass/fail summary)
./run_tests.sh

# Option 2 — unittest discover
python3 -m unittest discover -s tests -p "test_*.py" -v

# Option 3 — run a single test file
python3 -m unittest tests.test_calc_pain -v
```

## Requirements

- Python 3.8+
- No external dependencies (stdlib `unittest` only)
