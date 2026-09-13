"""Data models for Master Application Orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ActionTrigger(str, Enum):
    FIND_SYNONYMS = "FIND_SYNONYMS"
    FIND_DEFINITIONS = "FIND_DEFINITIONS"
    REWORD_TEXT = "REWORD_TEXT"
    DISCOVER_PAPERS = "DISCOVER_PAPERS"
    RETRIEVE_EVIDENCE = "RETRIEVE_EVIDENCE"
    GENERATE_GRAPH = "GENERATE_GRAPH"
    SUMMARIZE_SOURCE = "SUMMARIZE_SOURCE"
    ANALYZE_PAPER = "ANALYZE_PAPER"


class ShutdownReason(str, Enum):
    USER_QUIT = "USER_QUIT"
    OS_LOGOUT = "OS_LOGOUT"
    FATAL_PANIC = "FATAL_PANIC"


@dataclass
class AppRuntimeContext:
    session_id: str
    daemon_pid: int
    active_subsystems: Dict[str, bool]
    hotkey_handle: Optional[Any] = None
    daemon_status: Optional[Any] = None
    is_healthy: bool = True
    total_tokens_consumed: int = 0


@dataclass
class ActionResult:
    success: bool
    action: ActionTrigger
    latency_ms: float
    tokens_used: int
    tier: str  # "TIER_1_LOCAL" or "TIER_2_HYBRID"
    output_summary: str
    ui_handle_id: Optional[str] = None
    injected: bool = False
    data: Any = None


@dataclass
class AppExitReport:
    success: bool
    reason: ShutdownReason
    subsystems_stopped: List[str]
    elapsed_ms: float
