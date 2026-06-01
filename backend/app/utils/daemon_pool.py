"""Persistent image-gen daemon manager.

Spawns one long-running daemon per GPU and reuses it across requests
instead of paying ~25 s of model-load cost on every call. Communicates
over a Unix-domain socket with newline-delimited JSON.

Loop-agnostic: daemon processes are tracked with `subprocess.Popen` and
`threading.Lock`, so a manager created in one asyncio loop is reusable
from another loop in the same process (celery's per-task asyncio.run
pattern). The per-request connection itself is async and loop-bound,
but ephemeral.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DAEMON_SCRIPT = Path.home() / "instantid" / "instantid_daemon.py"


def _kill_orphan_daemons() -> None:
    """Kill any instantid_daemon.py processes left over from a prior celery
    run. Their sockets reference dead PIDs and they keep the GPU held,
    which OOMs the next Wan22/LTX video job. Called at module import
    (once per celery worker startup)."""
    import glob
    try:
        out = subprocess.run(
            ["pgrep", "-f", "instantid_daemon.py"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0:
            for token in out.stdout.split():
                try:
                    pid = int(token)
                except ValueError:
                    continue
                if pid == os.getpid():
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                    logger.info("Killed orphan instantid_daemon pid=%d", pid)
                except ProcessLookupError:
                    pass
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    for sock in glob.glob("/tmp/instantid-gpu*-*.sock"):
        try:
            Path(sock).unlink()
        except OSError:
            pass


_kill_orphan_daemons()


class DaemonManager:
    """Owns persistent daemon processes keyed by GPU index. Process state
    (Popen handles, sockets) is loop-independent so the same manager can
    be used across asyncio.run() boundaries within one celery worker."""

    def __init__(self, kind: str, script: Path, python_path: str):
        self.kind = kind
        self.script = script
        self.python_path = python_path
        self._procs: dict[int, subprocess.Popen] = {}
        self._sockets: dict[int, str] = {}
        self._lock = threading.Lock()
        atexit.register(self._cleanup)

    def _socket_path(self, gpu_idx: int) -> str:
        return f"/tmp/{self.kind}-gpu{gpu_idx}-{os.getpid()}.sock"

    def _ensure(self, gpu_idx: int) -> str:
        with self._lock:
            proc = self._procs.get(gpu_idx)
            if proc and proc.poll() is None:
                return self._sockets[gpu_idx]
            sock = self._socket_path(gpu_idx)
            env = {
                **os.environ,
                "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
                "CUDA_VISIBLE_DEVICES": str(gpu_idx),
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            }
            logger.info("Spawning %s daemon on GPU %d (sock=%s)",
                        self.kind, gpu_idx, sock)
            proc = subprocess.Popen(
                [self.python_path, str(self.script), "--socket", sock],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # warnings/progress noise — drop
                env=env,
            )
            if proc.stdout is None:
                raise RuntimeError(
                    f"{self.kind} daemon GPU {gpu_idx} subprocess opened with no stdout"
                )
            # Skip any pre-READY stdout (HF hub cache messages, deprecation
            # warnings, etc). The daemon emits READY\n on a clean line.
            import time
            deadline = time.time() + 180  # 3 min cap for first-time model warmup
            ready = False
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break  # EOF — daemon exited
                if line.strip() == b"READY":
                    ready = True
                    break
            if not ready:
                proc.terminate()
                raise RuntimeError(
                    f"{self.kind} daemon GPU {gpu_idx} failed to warm "
                    f"(no READY before timeout/EOF; rc={proc.poll()})"
                )
            self._procs[gpu_idx] = proc
            self._sockets[gpu_idx] = sock
            logger.info("%s daemon GPU %d ready", self.kind, gpu_idx)
            return sock

    async def request(
        self, gpu_idx: int, payload: dict, timeout: float = 600.0,
    ) -> dict:
        sock = await asyncio.get_event_loop().run_in_executor(
            None, self._ensure, gpu_idx,
        )
        reader, writer = await asyncio.open_unix_connection(sock)
        try:
            writer.write((json.dumps(payload) + "\n").encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=timeout)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionResetError) as e:
                logger.debug("wait_closed failed (gpu=%d): %s", gpu_idx, e)
        return json.loads(line.decode().strip())

    def shutdown_all(self) -> None:
        """Public shutdown — call at end of image_pregen so LTX (which lives
        on cuda:0) doesn't OOM against the daemon's resident SDXL+CN stack.
        Idempotent; daemons re-spawn lazily on the next request."""
        self._cleanup()
        self._procs.clear()
        self._sockets.clear()

    def _cleanup(self) -> None:
        for gpu_idx, proc in list(self._procs.items()):
            if proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGTERM)
                    proc.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
            sock = self._sockets.get(gpu_idx)
            if sock and Path(sock).exists():
                try:
                    Path(sock).unlink()
                except OSError:
                    pass


_managers: dict[str, DaemonManager] = {}
_managers_lock = threading.Lock()


def get_instantid_manager() -> Optional[DaemonManager]:
    if not _DAEMON_SCRIPT.exists():
        return None
    with _managers_lock:
        if "instantid" not in _managers:
            _managers["instantid"] = DaemonManager(
                kind="instantid",
                script=_DAEMON_SCRIPT,
                python_path=sys.executable,
            )
    return _managers["instantid"]
