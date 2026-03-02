"""Tests for HistoryManager (CommandHistory) in src/core/history.py"""
import pytest
from src.core.history import CommandHistory, ConcreteCommand, create_command


def test_execute_pushes_to_stack():
    h = CommandHistory()
    cmd = create_command("ADD", "Add item", {"item": "test"})
    assert h.execute_command(cmd) is True
    assert h.can_undo() is True
    assert h.get_undo_stack_size() == 1


def test_undo_reverses_action():
    h = CommandHistory()
    cmd = create_command("ADD", "Add item", {"item": "test"})
    h.execute_command(cmd)
    success, desc = h.undo()
    assert success is True
    assert desc == "Add item"
    assert h.can_redo() is True


def test_redo_reapplies():
    h = CommandHistory()
    cmd = create_command("ADD", "Add item", {"item": "test"})
    h.execute_command(cmd)
    h.undo()
    success, desc = h.redo()
    assert success is True
    assert desc == "Add item"


def test_max_50_enforced():
    h = CommandHistory(max_stack_size=50)
    for i in range(55):
        cmd = create_command("ADD", f"Add {i}", {"i": i})
        h.execute_command(cmd)
    assert h.get_undo_stack_size() == 50


def test_clear_empties_both_stacks():
    h = CommandHistory()
    cmd = create_command("ADD", "Add item", {})
    h.execute_command(cmd)
    h.undo()
    assert h.can_redo() is True
    h.clear()
    assert h.can_undo() is False
    assert h.can_redo() is False


def test_undo_on_empty_returns_safe():
    h = CommandHistory()
    success, desc = h.undo()
    assert success is False
    assert desc == ""


def test_redo_on_empty_returns_safe():
    h = CommandHistory()
    success, desc = h.redo()
    assert success is False


def test_get_history_newest_first():
    h = CommandHistory()
    for i in range(3):
        h.execute_command(create_command("ADD", f"Item {i}", {}))
    history = h.get_history(limit=3)
    assert len(history) == 3
    assert history[0]["description"] == "Item 2"
