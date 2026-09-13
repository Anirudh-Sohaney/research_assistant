"""Tests for daemon_service subsystem."""

import json
import os
import socket
import tempfile
import time
import pytest

from daemon_service.models import (
    DaemonConfig,
    DaemonStatus,
    HealthStatus,
    ShutdownReport,
)
from daemon_service.service import (
    DaemonSupervisor,
    get_daemon_health,
    is_pid_alive,
    start_daemon,
    stop_daemon,
)


def test_is_pid_alive():
    current_pid = os.getpid()
    assert is_pid_alive(current_pid) is True
    assert is_pid_alive(-1) is False
    assert is_pid_alive(99999999) is False


def test_single_instance_lock_and_collision():
    with tempfile.TemporaryDirectory() as tmpdir:
        pid_file = os.path.join(tmpdir, "test_daemon.pid")

        sup1 = DaemonSupervisor()
        assert sup1.acquire_single_instance_lock(pid_file) is True
        assert os.path.exists(pid_file)
        with open(pid_file, "r") as f:
            assert f.read().strip() == str(os.getpid())

        # Second supervisor should detect collision if process is alive
        sup2 = DaemonSupervisor()
        # Since sup2 has the same pid in this test process, let's simulate an external alive pid
        # In this test, sup2.acquire_single_instance_lock with same pid will succeed because existing_pid == self.pid
        # Let's test stale pid recovery:
        with open(pid_file, "w") as f:
            f.write("99999999")  # dead PID

        assert sup2.acquire_single_instance_lock(pid_file) is True
        with open(pid_file, "r") as f:
            assert f.read().strip() == str(os.getpid())

        sup1.release_single_instance_lock()
        assert not os.path.exists(pid_file)


def test_daemon_lifecycle_and_ipc():
    with tempfile.TemporaryDirectory() as tmpdir:
        pid_file = os.path.join(tmpdir, "lifecycle.pid")
        test_port = 49299
        config = DaemonConfig(
            pid_file_path=pid_file,
            ipc_endpoint=f"127.0.0.1:{test_port}",
        )

        supervisor = DaemonSupervisor()
        status = supervisor.start(config)

        assert status.status == "RUNNING"
        assert status.socket_ready is True
        assert status.pid == os.getpid()
        assert os.path.exists(pid_file)

        # Query health
        health = supervisor.get_health()
        assert isinstance(health, HealthStatus)
        assert health.status == "RUNNING"
        assert health.memory_mb > 0

        # Send IPC Ping request
        time.sleep(0.05)
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", test_port))
        client.sendall(json.dumps({"command": "ping"}).encode("utf-8"))
        resp_data = client.recv(4096).decode("utf-8")
        client.close()

        resp = json.loads(resp_data)
        assert resp.get("status") == "ok"
        assert resp.get("response") == "pong"

        # Stop daemon
        report = supervisor.stop(timeout_ms=1000)
        assert report.success is True
        assert not os.path.exists(pid_file)
        assert supervisor.is_running is False


def test_global_helpers():
    with tempfile.TemporaryDirectory() as tmpdir:
        pid_file = os.path.join(tmpdir, "global_test.pid")
        cfg = DaemonConfig(pid_file_path=pid_file, ipc_endpoint="127.0.0.1:49298")

        stat = start_daemon(cfg)
        assert stat.status == "RUNNING"

        health = get_daemon_health()
        assert health.status == "RUNNING"

        shutdown = stop_daemon()
        assert shutdown.success is True
        assert not os.path.exists(pid_file)
