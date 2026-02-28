"""
aeOS — history.py
In-memory command history with undo/redo support.
- Pure Python data structures (no DB reads).
- PERSIST integration is a stub: save/load session history to/from JSON.
Key concepts
-----------
- Command: Abstract base class for undoable commands.
- ConcreteCommand: Generic default command implementation.
- CommandHistory: Manages undo/redo stacks with a maximum size (FIFO drop on oldest).
This module is intentionally domain-agnostic: payload contents are opaque to the history system.
"""
from __future__ import annotations
import abc
import json
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Tuple, Type, TypeVar, Optional
TCommand = TypeVar("TCommand", bound="Command")
def _iso_utc_now() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
class Command(abc.ABC):
    """
    Abstract base for all undoable commands.
    Attributes:
        command_id: Unique identifier for this command (uuid4 string).
        command_type: Domain label for the command (e.g. "ADD_IDEA", "EDIT_PAIN").
        timestamp: ISO datetime string (UTC by default).
        description: Human-readable summary.
        payload: Data needed to execute and undo the command.
        executed: True if the command has been executed successfully.
        undone: True if the command has been undone successfully.
    """
    command_id: str
    command_type: str
    timestamp: str
    description: str
    payload: Dict[str, Any]
    executed: bool
    undone: bool
    def __init__(
        self,
        command_type: str,
        description: str,
        payload: Optional[Dict[str, Any]] = None,
        command_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        executed: bool = False,
        undone: bool = False,
    ) -> None:
        if not isinstance(command_type, str) or not command_type.strip():
            raise ValueError("command_type must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description must be a non-empty string")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload must be a dict if provided")
        self.command_id = command_id or str(uuid.uuid4())
        self.command_type = command_type
        self.timestamp = timestamp or _iso_utc_now()
        self.description = description
        self.payload = payload or {}
        self.executed = bool(executed)
        self.undone = bool(undone)
    @abc.abstractmethod
    def execute(self) -> bool:
        """
        Execute the command.
        Returns:
            True if execution succeeded, otherwise False.
        """
        raise NotImplementedError
    @abc.abstractmethod
    def undo(self) -> bool:
        """
        Undo the command.
        Returns:
            True if undo succeeded, otherwise False.
        """
        raise NotImplementedError
    @abc.abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize command into a JSON-serializable dict.
        Returns:
            A dict representation of the command.
        """
        raise NotImplementedError
    @classmethod
    @abc.abstractmethod
    def from_dict(cls: Type[TCommand], data: Dict[str, Any]) -> TCommand:
        """
        Reconstruct a Command instance from a dict.
        Args:
            data: A dict produced by to_dict().
        Returns:
            A Command instance.
        """
        raise NotImplementedError
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"id={self.command_id!r}, type={self.command_type!r}, "
            f"executed={self.executed}, undone={self.undone})"
        )
class ConcreteCommand(Command):
    """
    Concrete implementation for generic commands.
    This default command does not perform domain-side effects. It simply tracks
    state flags (executed/undone). Domain-specific behavior should be implemented
    later via specialized Command subclasses that override execute/undo.
    """
    def execute(self) -> bool:
        """
        Execute the command.
        Behavior:
            - If already executed and not undone, returns False (no-op).
            - Otherwise sets executed=True and undone=False and returns True.
        """
        if self.executed and not self.undone:
            return False
        self.executed = True
        self.undone = False
        return True
    def undo(self) -> bool:
        """
        Undo the command.
        Behavior:
            - Only allowed if executed=True and undone=False.
            - Sets undone=True and returns True.
        """
        if not self.executed or self.undone:
            return False
        self.undone = True
        return True
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to a JSON-serializable dict.
        Note:
            payload must itself be JSON-serializable for persistence to succeed.
        """
        return {
            "command_class": self.__class__.__name__,
            "command_id": self.command_id,
            "command_type": self.command_type,
            "timestamp": self.timestamp,
            "description": self.description,
            "payload": self.payload,
            "executed": self.executed,
            "undone": self.undone,
        }
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConcreteCommand":
        """
        Reconstruct a ConcreteCommand from a dict.
        Missing optional fields are defaulted safely.
        """
        if not isinstance(data, dict):
            raise ValueError("data must be a dict")
        payload = data.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            # Defensive: if payload was corrupted, coerce to empty dict.
            payload = {}
        return cls(
            command_type=str(data.get("command_type", "")).strip() or "UNKNOWN",
            description=str(data.get("description", "")).strip() or "No description",
            payload=payload,
            command_id=str(data.get("command_id") or str(uuid.uuid4())),
            timestamp=str(data.get("timestamp") or _iso_utc_now()),
            executed=bool(data.get("executed", False)),
            undone=bool(data.get("undone", False)),
        )
class CommandHistory:
    """
    The undo/redo stack manager.
    Notes:
        - Undo stack holds executed commands (most recent at the right side).
        - Redo stack holds undone commands (most recent at the right side).
        - Max stack size is enforced on the undo stack using FIFO drop on oldest.
    """
    def __init__(self, max_stack_size: int = 50) -> None:
        if not isinstance(max_stack_size, int) or max_stack_size <= 0:
            raise ValueError("max_stack_size must be a positive integer")
        self.max_stack_size: int = max_stack_size
        self._undo_stack: Deque[Command] = deque()
        self._redo_stack: Deque[Command] = deque()
        # Registry for reconstructing commands by class name (extensible).
        self._command_registry: Dict[str, Type[Command]] = {
            "ConcreteCommand": ConcreteCommand,
        }
    def execute_command(self, command: Command) -> bool:
        """
        Execute a command and push it onto the undo stack.
        Behavior:
            - Executes the command.
            - On success: pushes to undo stack, clears redo stack.
            - Enforces max_stack_size by dropping oldest entry from undo stack.
        Args:
            command: A Command instance to execute.
        Returns:
            True if executed and recorded, otherwise False.
        """
        if not isinstance(command, Command):
            raise ValueError("command must be an instance of Command")
        success = command.execute()
        if not success:
            return False
        # New command invalidates redo history.
        self._redo_stack.clear()
        # Enforce max size (FIFO drop on oldest).
        if len(self._undo_stack) >= self.max_stack_size:
            self._undo_stack.popleft()
        self._undo_stack.append(command)
        return True
    def undo(self) -> Tuple[bool, str]:
        """
        Undo the most recent command.
        Returns:
            (success, description_of_what_was_undone)
        """
        if not self._undo_stack:
            return False, ""
        command = self._undo_stack.pop()
        success = command.undo()
        if not success:
            # Restore the command back to undo stack since undo failed.
            self._undo_stack.append(command)
            return False, ""
        self._redo_stack.append(command)
        return True, command.description
    def redo(self) -> Tuple[bool, str]:
        """
        Redo the most recently undone command.
        Returns:
            (success, description_of_what_was_redone)
        """
        if not self._redo_stack:
            return False, ""
        command = self._redo_stack.pop()
        success = command.execute()
        if not success:
            # Restore to redo stack since redo failed.
            self._redo_stack.append(command)
            return False, ""
        # Enforce max size (FIFO drop on oldest) on undo stack again.
        if len(self._undo_stack) >= self.max_stack_size:
            self._undo_stack.popleft()
        self._undo_stack.append(command)
        return True, command.description
    def can_undo(self) -> bool:
        """Return True if there is at least one command to undo."""
        return len(self._undo_stack) > 0
    def can_redo(self) -> bool:
        """Return True if there is at least one command to redo."""
        return len(self._redo_stack) > 0
    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get most recent command history (newest first) from the undo stack.
        Args:
            limit: Maximum number of command entries to return.
        Returns:
            A list of serialized command dicts (newest first).
        """
        if not isinstance(limit, int) or limit <= 0:
            return []
        items: List[Dict[str, Any]] = []
        count = 0
        for cmd in reversed(self._undo_stack):
            items.append(cmd.to_dict())
            count += 1
            if count >= limit:
                break
        return items
    def get_undo_stack_size(self) -> int:
        """Return current size of the undo stack."""
        return len(self._undo_stack)
    def get_redo_stack_size(self) -> int:
        """Return current size of the redo stack."""
        return len(self._redo_stack)
    def clear(self) -> None:
        """Clear both undo and redo stacks."""
        self._undo_stack.clear()
        self._redo_stack.clear()
    # -------------------------
    # PERSIST stub (file-based)
    # -------------------------
    def save_session_history(self, filepath: str) -> bool:
        """
        Serialize full undo/redo stack to JSON and write to file.
        Args:
            filepath: Path to write JSON (overwrites).
        Returns:
            True if write succeeded, otherwise False.
        """
        if not isinstance(filepath, str) or not filepath.strip():
            return False
        data = {
            "schema_version": 1,
            "max_stack_size": self.max_stack_size,
            "undo_stack": [cmd.to_dict() for cmd in self._undo_stack],
            "redo_stack": [cmd.to_dict() for cmd in self._redo_stack],
        }
        try:
            # Validate JSON-serializability early to avoid partial writes.
            payload_json = json.dumps(data, ensure_ascii=False, indent=2)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(payload_json)
            return True
        except (OSError, TypeError, ValueError):
            return False
    def load_session_history(self, filepath: str) -> bool:
        """
        Restore undo/redo stacks from JSON file if it exists.
        Args:
            filepath: Path to JSON file.
        Returns:
            True if load succeeded, otherwise False.
        """
        if not isinstance(filepath, str) or not filepath.strip():
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = f.read()
            data = json.loads(raw)
        except FileNotFoundError:
            return False
        except (OSError, json.JSONDecodeError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        # Optionally restore max_stack_size (keeps behavior consistent with saved session).
        mss = data.get("max_stack_size")
        if isinstance(mss, int) and mss > 0:
            self.max_stack_size = mss
        undo_items = data.get("undo_stack", [])
        redo_items = data.get("redo_stack", [])
        if not isinstance(undo_items, list) or not isinstance(redo_items, list):
            return False
        # Clear existing session first.
        self.clear()
        # Enforce max_stack_size on load: keep most recent commands.
        if len(undo_items) > self.max_stack_size:
            undo_items = undo_items[-self.max_stack_size :]
        if len(redo_items) > self.max_stack_size:
            redo_items = redo_items[-self.max_stack_size :]
        try:
            for item in undo_items:
                cmd = self._rehydrate_command(item)
                self._undo_stack.append(cmd)
            for item in redo_items:
                cmd = self._rehydrate_command(item)
                self._redo_stack.append(cmd)
        except Exception:
            # If anything goes wrong, do not leave partial state.
            self.clear()
            return False
        return True
    def _rehydrate_command(self, data: Dict[str, Any]) -> Command:
        """
        Convert a serialized command dict into a Command instance.
        Supports future extension by adding new command classes to the registry.
        Unknown classes fall back to ConcreteCommand.
        """
        if not isinstance(data, dict):
            raise ValueError("Command entry must be a dict")
        class_name = data.get("command_class") or data.get("class") or "ConcreteCommand"
        class_name = str(class_name)
        cmd_cls = self._command_registry.get(class_name, ConcreteCommand)
        return cmd_cls.from_dict(data)
    def register_command_class(self, cls: Type[Command]) -> None:
        """
        Register a command class for future from_dict() restoration.
        Args:
            cls: A Command subclass.
        """
        name = cls.__name__
        self._command_registry[name] = cls
def create_command(command_type: str, description: str, payload: Dict[str, Any]) -> ConcreteCommand:
    """
    Factory function to build a ready-to-execute ConcreteCommand.
    Args:
        command_type: Domain label for the command.
        description: Human-readable summary.
        payload: Command data needed to execute/undo.
    Returns:
        A ConcreteCommand instance (not executed yet).
    """
    return ConcreteCommand(
        command_type=command_type,
        description=description,
        payload=payload,
        command_id=str(uuid.uuid4()),
        timestamp=_iso_utc_now(),
        executed=False,
        undone=False,
    )
