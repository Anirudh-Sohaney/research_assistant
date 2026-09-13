# Daemon Service Subsystem

## 1. Final Deliverable
A background supervisor and process lifecycle subsystem (`daemon_service.service.DaemonSupervisor`) providing:
- Single-instance lock file acquisition and automatic stale-lock recovery (`acquire_single_instance_lock`).
- Background daemon supervisor initialization and graceful shutdown (`start_daemon`, `stop_daemon`).
- Embedded TCP/IPC command listener servicing `ping`, `health`, and `stop` commands.
- Live process diagnostics and system health probes (`get_daemon_health`), tracking CPU usage, RSS memory, and subsystem states.
- Typed process control models (`DaemonConfig`, `DaemonStatus`, `HealthStatus`, `ShutdownReport`).

## 2. Algorithm Used
- **Single-Instance Mutex & Stale Lock Recovery**:
  1. Inspect target PID file on disk.
  2. If file exists, read encoded PID and evaluate `psutil.pid_exists(pid)`.
  3. If process is alive and distinct from current PID, abort startup to prevent resource or hook conflicts.
  4. If process is dead (stale crash artifact) or file absent, atomically write current PID to lock file.
- **IPC Command Loop & Graceful Teardown**:
  1. Bind non-blocking TCP socket to localhost endpoint (`127.0.0.1:port`).
  2. In worker thread, poll incoming JSON request messages with socket timeouts.
  3. On teardown, close server listener, await server thread join within timeout, and unlink the lock file.

## 3. Description
The `daemon_service` module forms the operational backbone of the Research Aid Desktop Assistant. Operating silently as an autonomous background process, it supervises the application lifecycle across Word, Google Docs, LaTeX, and Markdown workflows. It guarantees single-instance execution via lock file enforcement, hosts an internal IPC endpoint for tray menu and foreground communication, and monitors system resource health (CPU and RAM) to prevent desktop lag or memory leaks.
