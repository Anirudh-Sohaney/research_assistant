"""Data models for Daemon Service Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class DaemonConfig:
    pid_file_path: Optional[str] = None
    ipc_endpoint: Optional[str] = None
    log_level: str = "INFO"
    auto_restart_workers: bool = True
    max_memory_mb: int = 512


@dataclass
class DaemonStatus:
    pid: int
    status: str  # "RUNNING", "STOPPED", "ERROR"
    socket_ready: bool
    uptime_seconds: float
    message: Optional[str] = None


@dataclass
class ShutdownReport:
    success: bool
    unlinked_pid_file: bool
    closed_socket: bool
    elapsed_ms: float
    message: Optional[str] = None


@dataclass
class HealthStatus:
    pid: int
    status: str
    cpu_percent: float
    memory_mb: float
    active_subsystems: Dict[str, bool] = field(default_factory=dict)
    uptime_seconds: float = 0.0
