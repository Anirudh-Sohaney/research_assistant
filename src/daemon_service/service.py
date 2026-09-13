"""Daemon Service Subsystem managing background supervision, IPC, and single-instance locks."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from typing import Dict, Optional, Tuple

import psutil

from daemon_service.models import (
    DaemonConfig,
    DaemonStatus,
    HealthStatus,
    ShutdownReport,
)

log = logging.getLogger("daemon_service")

DEFAULT_PORT = 49215


def is_pid_alive(pid: int) -> bool:
    """Checks if a process with the given PID is currently active."""
    if pid <= 0:
        return False
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


class DaemonSupervisor:
    """Manages daemon lifecycle, single-instance lock file, IPC server, and health monitoring."""

    def __init__(self):
        self.config: Optional[DaemonConfig] = None
        self.pid: int = os.getpid()
        self.start_time: float = 0.0
        self.is_running: bool = False
        self.pid_file_path: Optional[str] = None
        self.server_socket: Optional[socket.socket] = None
        self.server_thread: Optional[threading.Thread] = None
        self.active_subsystems: Dict[str, bool] = {
            "hotkey_manager": False,
            "api_gateway": False,
            "rag_indexer": False,
            "overlay_ui": False,
        }
        self._lock = threading.Lock()

    def acquire_single_instance_lock(self, pid_file: str) -> bool:
        """Acquires single-instance lock or recovers from stale lock."""
        self.pid_file_path = pid_file
        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        existing_pid = int(content)
                        if existing_pid != self.pid and is_pid_alive(existing_pid):
                            log.error("Daemon already running with PID %d", existing_pid)
                            return False
            except Exception as exc:
                log.warning("Could not read existing pid file: %s", exc)

        # Write current PID
        try:
            os.makedirs(os.path.dirname(os.path.abspath(pid_file)), exist_ok=True)
            with open(pid_file, "w", encoding="utf-8") as f:
                f.write(str(self.pid))
            return True
        except Exception as exc:
            log.error("Failed to write PID file %s: %s", pid_file, exc)
            return False

    def release_single_instance_lock(self) -> bool:
        """Releases and unlinks the PID lock file."""
        if self.pid_file_path and os.path.exists(self.pid_file_path):
            try:
                os.remove(self.pid_file_path)
                return True
            except Exception as exc:
                log.warning("Failed to remove PID file: %s", exc)
                return False
        return True

    def _run_ipc_server(self, host: str, port: int) -> None:
        """Lightweight non-blocking TCP IPC command listener."""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(0.5)
            self.server_socket.bind((host, port))
            self.server_socket.listen(5)
        except Exception as exc:
            log.error("Failed to bind IPC socket on %s:%d: %s", host, port, exc)
            return

        while self.is_running:
            try:
                client_sock, _ = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                data = client_sock.recv(4096).decode("utf-8")
                if not data:
                    client_sock.close()
                    continue

                req = json.loads(data)
                cmd = req.get("command", "")
                if cmd == "ping":
                    resp = {"status": "ok", "response": "pong"}
                elif cmd == "health":
                    health = self.get_health()
                    resp = {"status": "ok", "response": asdict(health)}
                elif cmd == "stop":
                    resp = {"status": "ok", "response": "stopping"}
                    client_sock.sendall(json.dumps(resp).encode("utf-8"))
                    client_sock.close()
                    threading.Thread(target=self.stop, kwargs={"timeout_ms": 1000}, daemon=True).start()
                    break
                else:
                    resp = {"status": "error", "message": f"Unknown command: {cmd}"}

                client_sock.sendall(json.dumps(resp).encode("utf-8"))
                client_sock.close()
            except Exception as exc:
                log.warning("IPC connection error: %s", exc)

    def start(self, config: Optional[DaemonConfig] = None) -> DaemonStatus:
        """Initializes and starts the daemon supervisor."""
        with self._lock:
            if self.is_running:
                return DaemonStatus(
                    pid=self.pid,
                    status="RUNNING",
                    socket_ready=self.server_socket is not None,
                    uptime_seconds=time.monotonic() - self.start_time,
                    message="Daemon already running.",
                )

            self.config = config or DaemonConfig()
            pid_path = self.config.pid_file_path or os.path.join(
                tempfile.gettempdir(), "research_aid_daemon.pid"
            )

            if not self.acquire_single_instance_lock(pid_path):
                return DaemonStatus(
                    pid=self.pid,
                    status="ERROR",
                    socket_ready=False,
                    uptime_seconds=0.0,
                    message="Instance already running or PID lock acquisition failed.",
                )

            self.is_running = True
            self.start_time = time.monotonic()

            # Start IPC server
            port = DEFAULT_PORT
            if self.config.ipc_endpoint and ":" in self.config.ipc_endpoint:
                try:
                    port = int(self.config.ipc_endpoint.split(":")[-1])
                except ValueError:
                    port = DEFAULT_PORT

            self.server_thread = threading.Thread(
                target=self._run_ipc_server, args=("127.0.0.1", port), daemon=True
            )
            self.server_thread.start()

            # Brief pause to verify socket readiness
            time.sleep(0.05)
            socket_ready = self.server_socket is not None

            return DaemonStatus(
                pid=self.pid,
                status="RUNNING",
                socket_ready=socket_ready,
                uptime_seconds=time.monotonic() - self.start_time,
                message="Daemon started successfully.",
            )

    def stop(self, force: bool = False, timeout_ms: int = 3000) -> ShutdownReport:
        """Terminates background IPC server and releases lock files."""
        start = time.monotonic()
        with self._lock:
            if not self.is_running:
                return ShutdownReport(
                    success=True,
                    unlinked_pid_file=True,
                    closed_socket=True,
                    elapsed_ms=0.0,
                    message="Daemon was not running.",
                )

            self.is_running = False

            # Close server socket
            closed_socket = False
            if self.server_socket:
                try:
                    self.server_socket.close()
                    closed_socket = True
                except Exception as exc:
                    log.warning("Error closing server socket: %s", exc)
                self.server_socket = None

            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=timeout_ms / 1000.0)

            unlinked = self.release_single_instance_lock()
            elapsed = (time.monotonic() - start) * 1000.0

            return ShutdownReport(
                success=True,
                unlinked_pid_file=unlinked,
                closed_socket=closed_socket,
                elapsed_ms=elapsed,
                message="Daemon stopped cleanly.",
            )

    def get_health(self) -> HealthStatus:
        """Inspects CPU, RAM, subsystem statuses, and process uptime."""
        uptime = time.monotonic() - self.start_time if self.is_running else 0.0
        cpu = 0.0
        mem = 0.0
        try:
            proc = psutil.Process(self.pid)
            cpu = proc.cpu_percent(interval=None)
            mem = proc.memory_info().rss / (1024.0 * 1024.0)
        except Exception:
            pass

        return HealthStatus(
            pid=self.pid,
            status="RUNNING" if self.is_running else "STOPPED",
            cpu_percent=cpu,
            memory_mb=round(mem, 2),
            active_subsystems=dict(self.active_subsystems),
            uptime_seconds=round(uptime, 2),
        )


_global_daemon = DaemonSupervisor()


def start_daemon(config: Optional[DaemonConfig] = None) -> DaemonStatus:
    return _global_daemon.start(config)


def stop_daemon(force: bool = False, timeout_ms: int = 3000) -> ShutdownReport:
    return _global_daemon.stop(force=force, timeout_ms=timeout_ms)


def get_daemon_health() -> HealthStatus:
    return _global_daemon.get_health()
