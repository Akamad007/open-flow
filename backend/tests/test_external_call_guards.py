"""Verifies the conftest guards block external calls (positive proof)."""

from __future__ import annotations

import asyncio
import subprocess
import urllib.request

import httpx
import pytest


def test_httpx_sync_blocked_for_remote_host():
    with pytest.raises(RuntimeError, match="HTTP request"):
        httpx.get("https://api.openai.com/v1/models")


async def test_httpx_async_blocked_for_remote_host():
    with pytest.raises(RuntimeError, match="HTTP request"):
        async with httpx.AsyncClient() as client:
            await client.get("https://api.openai.com/v1/models")


def test_httpx_local_host_allowed_through_guard():
    """Guard allows localhost/127.0.0.1 — used by in-process ASGI tests."""
    # Verify the predicate directly (no real connection needed).
    import httpx
    req = httpx.Request("GET", "http://test/api/health")
    # Build a minimal client and verify our guard does NOT raise on this request.
    # We simulate by calling the guard's predicate via the client's send chain.
    client = httpx.Client()
    # Don't actually send — just check that constructing a local-host request
    # does not raise at guard-evaluation time. The guard fires inside `send()`.
    # If guard misclassifies "test" as remote, this would hit the block; instead it
    # would try to make a real connection (no listener on host "test"), which we
    # detect via a non-RuntimeError ConnectError.
    try:
        client.send(req)
    except RuntimeError as e:
        if "HTTP request" in str(e):
            pytest.fail(f"Guard incorrectly blocked local host: {e}")
        raise
    except Exception:
        pass  # Real network attempt — that's fine, we only care guard didn't fire.
    finally:
        client.close()


def test_urllib_blocked():
    with pytest.raises(RuntimeError, match="HTTP request"):
        urllib.request.urlopen("https://api.openai.com/v1/models")


def test_subprocess_popen_blocked_for_disallowed_command():
    with pytest.raises(RuntimeError, match="subprocess spawn"):
        subprocess.Popen(["python", "-c", "print(1)"])


async def test_create_subprocess_exec_blocked_for_disallowed_command():
    with pytest.raises(RuntimeError, match="subprocess spawn"):
        await asyncio.create_subprocess_exec("python", "-c", "print(1)")


async def test_create_subprocess_shell_blocked():
    with pytest.raises(RuntimeError, match="subprocess spawn"):
        await asyncio.create_subprocess_shell("echo hi")


def test_ffmpeg_subprocess_is_allowed():
    """Allowlisted: stub providers shell out to ffmpeg for placeholder media."""
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed locally")
    proc = subprocess.Popen(
        ["ffmpeg", "-version"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    proc.communicate()
    assert proc.returncode == 0


def test_settings_force_stub_providers_in_tests():
    """conftest sets *_PROVIDER=stub before app imports — verify it took effect."""
    from app.config import settings
    assert settings.llm_provider == "stub"
    assert settings.video_provider == "stub"
    assert settings.audio_provider == "stub"
    assert settings.image_provider == "stub"
