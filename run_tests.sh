#!/usr/bin/env bash
# run_tests.sh — Run the aeOS calc-layer unit tests and report pass/fail count.
set -eo pipefail

cd "$(dirname "$0")"

echo "=============================="
echo "  aeOS — Running unit tests"
echo "=============================="
echo

python3 -m unittest discover -s tests -p "test_*.py" -v 2>&1 | tee /tmp/aeos_test_output.txt
exit_code=${PIPESTATUS[0]}

echo
echo "=============================="

# Count results from the verbose output
passed=$(grep -cE '\.\.\. ok$' /tmp/aeos_test_output.txt || true)
failed=$(grep -cE '(FAIL|ERROR)$' /tmp/aeos_test_output.txt || true)
total=$((passed + failed))

echo "  Total : $total"
echo "  Passed: $passed"
echo "  Failed: $failed"
echo "=============================="

rm -f /tmp/aeos_test_output.txt
exit "$exit_code"
