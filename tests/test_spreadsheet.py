"""Tests for Spreadsheet"""
import pytest
from src.core.spreadsheet import Spreadsheet


def test_set_get_numeric():
    ss = Spreadsheet()
    ss.set_cell(0, 0, 42)
    assert ss.get_cell(0, 0) == 42


def test_sum_formula():
    ss = Spreadsheet()
    ss.set_cell(0, 0, 10)
    ss.set_cell(1, 0, 20)
    ss.set_cell(2, 0, 30)
    ss.set_cell(3, 0, "=SUM(A1:A3)")
    assert ss.get_cell(3, 0) == 60


def test_csv_import_loads():
    ss = Spreadsheet()
    csv_data = "1,2,3\n4,5,6\n7,8,9"
    result = ss.import_csv(csv_data)
    assert result["rows_loaded"] == 3
    assert result["cols_loaded"] == 3


def test_csv_export_roundtrip():
    ss = Spreadsheet()
    csv_in = "10,20\n30,40"
    ss.import_csv(csv_in)
    exported = ss.export_csv()
    assert "10" in exported
    assert "40" in exported


def test_cell_reference_in_formula():
    ss = Spreadsheet()
    ss.set_cell(0, 0, 100)  # A1
    ss.set_cell(0, 1, "=A1+50")  # B1
    assert ss.get_cell(0, 1) == 150


def test_avg_formula():
    ss = Spreadsheet()
    ss.set_cell(0, 0, 10)
    ss.set_cell(1, 0, 20)
    ss.set_cell(2, 0, "=AVG(A1:A2)")
    assert ss.get_cell(2, 0) == 15.0


def test_clear():
    ss = Spreadsheet()
    ss.set_cell(0, 0, 42)
    ss.clear()
    assert ss.get_cell(0, 0) is None


def test_get_range():
    ss = Spreadsheet()
    ss.set_cell(0, 0, 1)
    ss.set_cell(0, 1, 2)
    ss.set_cell(1, 0, 3)
    ss.set_cell(1, 1, 4)
    result = ss.get_range(0, 0, 1, 1)
    assert result == [[1, 2], [3, 4]]


def test_out_of_range_raises():
    ss = Spreadsheet(rows=10, cols=10)
    with pytest.raises(ValueError):
        ss.set_cell(100, 0, 1)
