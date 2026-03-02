"""Spreadsheet — In-app spreadsheet engine for aeOS.

Supports basic formulas, cell references, CSV import/export.
Not a full Excel replacement — covers ad-hoc calculations.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple


class Spreadsheet:
    """Lightweight in-app spreadsheet engine.

    Supports basic formulas, cell references, CSV import/export.
    """

    def __init__(self, rows: int = 100, cols: int = 26) -> None:
        self._rows = max(rows, 1)
        self._cols = max(cols, 1)
        self._cells: Dict[Tuple[int, int], Any] = {}

    def set_cell(self, row: int, col: int, value: Any) -> None:
        """Set cell value. Accepts number, string, or formula (starts with '=')."""
        if row < 0 or row >= self._rows or col < 0 or col >= self._cols:
            raise ValueError(
                f"Cell ({row}, {col}) out of range "
                f"(0-{self._rows - 1}, 0-{self._cols - 1})"
            )
        self._cells[(row, col)] = value

    def get_cell(self, row: int, col: int) -> Any:
        """Return computed cell value (evaluates formula if present)."""
        raw = self._cells.get((row, col))
        if raw is None:
            return None
        if isinstance(raw, str) and raw.startswith("="):
            return self.evaluate_formula(raw)
        return raw

    def evaluate_formula(self, formula: str) -> Any:
        """Evaluate formula string.

        Supported: SUM(A1:A10), AVG(A1:A10), MAX, MIN, COUNT,
                  arithmetic (+, -, *, /), cell references (A1, B2).

        Returns computed value or FormulaError string on failure.
        """
        if not isinstance(formula, str) or not formula.startswith("="):
            return formula

        expr = formula[1:].strip()

        try:
            # Replace function calls
            expr = self._expand_functions(expr)
            # Replace cell references
            expr = self._resolve_cell_refs(expr)
            # Evaluate
            result = self._safe_eval(expr)
            return result
        except Exception as exc:
            return f"FormulaError: {str(exc)}"

    def import_csv(self, csv_text: str) -> dict:
        """Load CSV into spreadsheet starting at A1.

        Returns:
            {rows_loaded: int, cols_loaded: int, errors: list[str]}
        """
        if not isinstance(csv_text, str) or not csv_text.strip():
            return {"rows_loaded": 0, "cols_loaded": 0, "errors": ["Empty CSV"]}

        errors = []
        reader = csv.reader(io.StringIO(csv_text))
        max_col = 0
        row_count = 0

        for row_idx, row_data in enumerate(reader):
            if row_idx >= self._rows:
                errors.append(f"Truncated at row {self._rows}")
                break
            for col_idx, value in enumerate(row_data):
                if col_idx >= self._cols:
                    continue
                # Try to parse as number
                try:
                    num = float(value)
                    if num == int(num):
                        self._cells[(row_idx, col_idx)] = int(num)
                    else:
                        self._cells[(row_idx, col_idx)] = num
                except ValueError:
                    self._cells[(row_idx, col_idx)] = value
                max_col = max(max_col, col_idx + 1)
            row_count = row_idx + 1

        return {
            "rows_loaded": row_count,
            "cols_loaded": max_col,
            "errors": errors,
        }

    def export_csv(self) -> str:
        """Export spreadsheet to CSV string."""
        if not self._cells:
            return ""

        max_row = max(r for r, c in self._cells.keys()) + 1
        max_col = max(c for r, c in self._cells.keys()) + 1

        output = io.StringIO()
        writer = csv.writer(output)

        for row in range(max_row):
            row_data = []
            for col in range(max_col):
                val = self.get_cell(row, col)
                row_data.append("" if val is None else str(val))
            writer.writerow(row_data)

        return output.getvalue()

    def get_range(
        self,
        start_row: int,
        start_col: int,
        end_row: int,
        end_col: int,
    ) -> List[List[Any]]:
        """Return 2D list of computed values for the range."""
        result = []
        for r in range(start_row, end_row + 1):
            row_vals = []
            for c in range(start_col, end_col + 1):
                row_vals.append(self.get_cell(r, c))
            result.append(row_vals)
        return result

    def clear(self) -> None:
        """Clear all cells."""
        self._cells.clear()

    # ── Internal helpers ───────────────────────────────────────

    def _cell_ref_to_rc(self, ref: str) -> Tuple[int, int]:
        """Convert A1-style reference to (row, col) tuple."""
        match = re.match(r"^([A-Z]+)(\d+)$", ref.upper())
        if not match:
            raise ValueError(f"Invalid cell reference: {ref}")
        col_str = match.group(1)
        row_num = int(match.group(2)) - 1  # 0-indexed

        col = 0
        for ch in col_str:
            col = col * 26 + (ord(ch) - ord("A") + 1)
        col -= 1  # 0-indexed

        return row_num, col

    def _resolve_cell_refs(self, expr: str) -> str:
        """Replace cell references (A1, B2) with their values."""
        def replacer(match: re.Match) -> str:
            ref = match.group(0)
            try:
                r, c = self._cell_ref_to_rc(ref)
                val = self.get_cell(r, c)
                if val is None:
                    return "0"
                return str(val)
            except (ValueError, IndexError):
                return "0"

        return re.sub(r"\b([A-Z]+\d+)\b", replacer, expr)

    def _expand_functions(self, expr: str) -> str:
        """Expand SUM, AVG, MAX, MIN, COUNT functions."""
        func_pattern = re.compile(
            r"(SUM|AVG|AVERAGE|MAX|MIN|COUNT)\(([A-Z]+\d+):([A-Z]+\d+)\)",
            re.IGNORECASE,
        )

        def func_replacer(match: re.Match) -> str:
            func = match.group(1).upper()
            start_ref = match.group(2)
            end_ref = match.group(3)

            try:
                sr, sc = self._cell_ref_to_rc(start_ref)
                er, ec = self._cell_ref_to_rc(end_ref)
            except ValueError:
                return "0"

            values = []
            for r in range(sr, er + 1):
                for c in range(sc, ec + 1):
                    val = self.get_cell(r, c)
                    if isinstance(val, (int, float)):
                        values.append(float(val))

            if not values:
                return "0"

            if func == "SUM":
                return str(sum(values))
            elif func in ("AVG", "AVERAGE"):
                return str(sum(values) / len(values))
            elif func == "MAX":
                return str(max(values))
            elif func == "MIN":
                return str(min(values))
            elif func == "COUNT":
                return str(len(values))
            return "0"

        return func_pattern.sub(func_replacer, expr)

    @staticmethod
    def _safe_eval(expr: str) -> Any:
        """Safely evaluate arithmetic expression."""
        # Only allow numbers, operators, parens, dots, spaces
        cleaned = expr.strip()
        if not re.match(r"^[\d\s\+\-\*/\.\(\)]+$", cleaned):
            raise ValueError(f"Unsafe expression: {cleaned}")
        try:
            result = eval(cleaned, {"__builtins__": {}}, {})  # noqa: S307
            if isinstance(result, float) and result == int(result):
                return int(result)
            return result
        except Exception as e:
            raise ValueError(f"Evaluation failed: {e}")
