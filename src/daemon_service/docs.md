# Daemon Service Subsystem Documentation

## Overview
The `daemon_service` package provides process lifecycle supervision, single-instance mutex enforcement, IPC communication, and health diagnostics for the background assistant.

---

## Architecture & Data Models

### `daemon_service.models`
- **`DaemonConfig`**:
  - `pid_file_path`: Path for file-based process locking.
  - `ipc_endpoint`: Host and port string (`127.0.0.1:49215`).
  - `log_level`: Logging verbosity (`INFO`, `DEBUG`, etc.).
  - `auto_restart_workers`: Boolean flag for worker supervision.
  - `max_memory_mb`: Memory limit before triggering cache pruning.
- **`DaemonStatus`**:
  - `pid`: Process identifier.
  - `status`: Running state string (`RUNNING`, `STOPPED`, `ERROR`).
  - `socket_ready`: Boolean indicating if IPC endpoint is accepting connections.
  - `uptime_seconds`: Elapsed time since supervisor startup.
  - `message`: Diagnostic message.
- **`ShutdownReport`**:
  - `success`: Boolean indicating clean termination.
  - `unlinked_pid_file`: Boolean indicating whether PID file was deleted.
  - `closed_socket`: Boolean indicating whether IPC server closed.
  - `elapsed_ms`: Shutdown duration in milliseconds.
- **`HealthStatus`**:
  - `pid`: Process PID.
  - `status`: Lifecycle state.
  - `cpu_percent`: Process CPU usage percentage.
  - `memory_mb`: Resident set size (RSS) in megabytes.
  - `active_subsystems`: Dictionary of subsystem operational flags.
  - `uptime_seconds`: Running duration.

---

## API Reference

### `start_daemon(config: Optional[DaemonConfig] = None) -> DaemonStatus`
Acquires single-instance lock, launches IPC command server, and begins background supervision.

### `stop_daemon(force: bool = False, timeout_ms: int = 3000) -> ShutdownReport`
Gracefully halts IPC server, waits for thread joins, and unlinks lock file.

### `get_daemon_health() -> HealthStatus`
Queries CPU, memory, uptime, and component status.

### `is_pid_alive(pid: int) -> bool`
Utility function checking whether a given PID is currently active.

---

## Usage Example

```python
from daemon_service import (
    DaemonConfig,
    start_daemon,
    stop_daemon,
    get_daemon_health,
)

# Start daemon service
config = DaemonConfig(ipc_endpoint="127.0.0.1:49215")
status = start_daemon(config)
print(f"Daemon running on PID {status.pid}, socket ready: {status.socket_ready}")

# Query health
health = get_daemon_health()
print(f"Memory: {health.memory_mb} MB, CPU: {health.cpu_percent}%")

# Stop daemon cleanly
report = stop_daemon()
print(f"Cleanly unlinked lock: {report.unlinked_pid_file}")
```

---

## Verification & Testing
Tests in `daemon_service/tests/test_daemon_service.py` verify:
- Accurate detection of active and dead process IDs.
- Atomic acquisition of single-instance locks and stale lock recovery.
- IPC command processing (`ping`, `health`, `stop`) over loopback TCP sockets.
- Diagnostic memory and CPU probes.
- Graceful termination and lock unlinking.
