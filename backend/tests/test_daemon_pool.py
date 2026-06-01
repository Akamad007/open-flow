"""Daemon manager wire protocol — verifies the JSON-line request/response
cycle against an in-process Unix socket server. No subprocess spawn (tests
block it); the DaemonManager's _ensure step is bypassed by pre-populating
the proc/socket maps with stubs."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.utils.daemon_pool import DaemonManager


class _FakeProc:
    """Stand-in for subprocess.Popen — always reports running."""
    def __init__(self):
        self.pid = -1
    def poll(self):
        return None
    def send_signal(self, *_):
        pass
    def wait(self, timeout=None):
        return 0


def _start_echo_server(sock_path: str) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        line = await reader.readuntil(b"\n")
        req = json.loads(line.decode().strip())
        resp = {"success": True, "echo": req}
        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
        writer.close()
    return handle, sock_path


@pytest.mark.asyncio
async def test_daemon_request_roundtrip(tmp_path: Path):
    sock_path = str(tmp_path / "fake.sock")
    handler, _ = _start_echo_server(sock_path)
    server = await asyncio.start_unix_server(handler, path=sock_path)

    try:
        mgr = DaemonManager(
            kind="fake", script=Path("/nonexistent"), python_path=sys.executable,
        )
        # Bypass subprocess spawn: pretend a daemon is already warm.
        mgr._procs[0] = _FakeProc()
        mgr._sockets[0] = sock_path

        resp = await mgr.request(gpu_idx=0, payload={"hello": "world"})
        assert resp == {"success": True, "echo": {"hello": "world"}}
    finally:
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.unlink(sock_path)


@pytest.mark.asyncio
async def test_daemon_request_serialises_large_payload(tmp_path: Path):
    sock_path = str(tmp_path / "fake2.sock")
    handler, _ = _start_echo_server(sock_path)
    server = await asyncio.start_unix_server(handler, path=sock_path)

    try:
        mgr = DaemonManager(
            kind="fake2", script=Path("/nonexistent"), python_path=sys.executable,
        )
        mgr._procs[0] = _FakeProc()
        mgr._sockets[0] = sock_path

        payload = {"prompt": "x" * 5000, "negative": "y" * 5000, "seed": 42}
        resp = await mgr.request(gpu_idx=0, payload=payload)
        assert resp["success"] is True
        assert resp["echo"] == payload
    finally:
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.unlink(sock_path)
