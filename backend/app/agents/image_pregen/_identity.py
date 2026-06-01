"""Face-embedding cache for identity-aware image providers.

Extracts the InsightFace embedding for a character portrait ONCE and
writes it to a sidecar `.idemb.pt` file next to the portrait. The cache
is invalidated whenever the portrait file mtime changes (a re-rendered
portrait → fresh embedding). Per-still cost stays low because the
InstantID/PuLID subprocess loads the cached `.pt` instead of re-running
the face encoder.
"""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from pathlib import Path

from app.config import settings as cfg
from app.providers.image.base import IdentityRef
from app.utils.gpu import apply_gpu_env, largest_gpu_index

logger = logging.getLogger(__name__)

# Per-loop lock map: each event loop gets its own dict of {portrait_path: Lock}.
# asyncio.Lock binds to the loop it was created in; celery runs one task per
# worker with a fresh asyncio.run(), so a WeakKeyDictionary self-cleans.
_lock_maps: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


def _lock_for(portrait_path: str) -> asyncio.Lock:
    loop = asyncio.get_event_loop()
    m = _lock_maps.get(loop)
    if m is None:
        m = {}
        _lock_maps[loop] = m
    lock = m.get(portrait_path)
    if lock is None:
        lock = asyncio.Lock()
        m[portrait_path] = lock
    return lock

# Bumped manually whenever the encoder model changes — invalidates ALL
# cached embeddings. Keep in lock-step with the encoder pinned in the
# subprocess script (~/instantid/generate_instantid.py).
ENCODER_VERSION = "buffalo_l-v1"

# Subprocess that extracts and writes a single .idemb.pt for a portrait.
# Lives outside the app for the same reason SD 3.5 lives in ~/sd35-medium:
# heavyweight model loads, fully released after each call.
EMBED_SCRIPT = Path.home() / "instantid" / "extract_embedding.py"


def _embedding_path(portrait_path: str) -> Path:
    """`storage/.../sadhguru.png` → `storage/.../sadhguru.idemb.pt`."""
    p = Path(portrait_path)
    return p.with_name(p.stem + f".{ENCODER_VERSION}.idemb.pt")


def _is_fresh(portrait_path: str, embedding_path: Path) -> bool:
    """True if the embedding exists AND is newer than the portrait. Stale
    if the portrait was re-rendered after the cache was written."""
    if not embedding_path.exists():
        return False
    return embedding_path.stat().st_mtime >= Path(portrait_path).stat().st_mtime


async def get_or_create_identity_ref(portrait_path: str) -> IdentityRef:
    """Return an IdentityRef pointing at a fresh embedding for `portrait_path`.

    If the cached `.idemb.pt` is missing or older than the portrait,
    extract a new one via the subprocess. Otherwise reuse the cached one.
    Raises FileNotFoundError if the portrait itself doesn't exist.
    """
    if not Path(portrait_path).exists():
        raise FileNotFoundError(f"portrait not found for identity ref: {portrait_path}")

    emb = _embedding_path(portrait_path)
    if _is_fresh(portrait_path, emb):
        logger.debug("Identity embedding cache hit: %s", emb)
        return IdentityRef(portrait_path=portrait_path, embedding_path=str(emb))

    if not EMBED_SCRIPT.exists():
        logger.warning(
            "InstantID embedding extractor not found at %s — provider must "
            "extract on the GPU side per call (slower).", EMBED_SCRIPT,
        )
        return IdentityRef(portrait_path=portrait_path, embedding_path=str(emb))

    # Single-flight: 30+ action-still tasks call this concurrently for the
    # SAME portrait. Without the lock all of them race past the cache-miss
    # check and spawn parallel InsightFace subprocesses — ONNX silently
    # falls back to CPU when CUDA can't allocate, which drowns the host.
    async with _lock_for(portrait_path):
        if _is_fresh(portrait_path, emb):
            return IdentityRef(portrait_path=portrait_path, embedding_path=str(emb))

        # Pin the subprocess to the larger GPU so ONNX's CUDA provider
        # always wins — no silent CPU fallback.
        env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
        apply_gpu_env(env, largest_gpu_index())

        cmd = [cfg.gpu_python_path, str(EMBED_SCRIPT),
               "--portrait", portrait_path,
               "--out", str(emb)]
        logger.info("Extracting face embedding for %s", portrait_path)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("Embedding extraction timed out for %s", portrait_path)
            return IdentityRef(portrait_path=portrait_path, embedding_path=str(emb))
        if proc.returncode != 0 or not emb.exists():
            err = (stderr.decode() if stderr else "").strip()[-300:]
            logger.warning("Embedding extraction failed (rc=%d): %s", proc.returncode, err)
        else:
            logger.info("Cached embedding → %s", emb)

    return IdentityRef(portrait_path=portrait_path, embedding_path=str(emb))
