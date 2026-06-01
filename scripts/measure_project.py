#!/usr/bin/env python
"""
Score a finished project and report what's likely wrong.

Computes a quality vector from DB + filesystem + frame samples and emits
a JSON report with concrete failure-mode flags. Designed to be the
"measure" half of the iterate-improve loop.

Usage:
    python scripts/measure_project.py <project_id>
    python scripts/measure_project.py <project_id> --api http://localhost:8002
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

STORAGE_ROOT = Path("/home/akash/PycharmProjects/video-app/backend/storage")
SADHGURU_TOKENS = ("turban", "robe", "beard", "sadhguru", "white kurta")


def fetch_json(url: str) -> Any:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def sample_frame_hash(video_path: Path, frame_n: int) -> str | None:
    """Extract one frame and return a perceptual-ish hash (downscaled MD5)."""
    if not video_path.exists():
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(video_path),
                "-vf", f"select=eq(n\\,{frame_n}),scale=64:64",
                "-frames:v", "1", tmp_path,
            ],
            capture_output=True, timeout=20,
        )
        if r.returncode != 0 or not Path(tmp_path).exists():
            return None
        return hashlib.md5(Path(tmp_path).read_bytes()).hexdigest()[:16]
    except Exception:
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def hamming_like(a: str, b: str) -> float:
    """Hex-pair similarity. 1.0 = identical, 0.0 = totally different."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def measure(api: str, project_id: str) -> dict:
    project = fetch_json(f"{api}/api/projects/{project_id}")
    scenes = fetch_json(f"{api}/api/projects/{project_id}/scenes")
    images = fetch_json(f"{api}/api/projects/{project_id}/images")

    n_scenes = len(scenes)
    n_locations = len(images.get("locations", []))
    n_characters = len(images.get("characters", []))

    # Per-scene counts
    scene_chars = []
    scene_loc = []
    scene_seq_count = []
    scenes_with_no_char = 0
    scenes_with_no_loc = 0
    scenes_with_no_stills = 0
    char_hallucination = []  # scenes where prompt mentions Sadhguru but no Sadhguru in chars

    for s in scenes:
        chars = [c.get("canonical_name", "") for c in (s.get("characters") or [])]
        scene_chars.append(chars)
        loc = (s.get("location") or {}).get("name") if s.get("location") else None
        scene_loc.append(loc)
        if not chars:
            scenes_with_no_char += 1
        if not loc:
            scenes_with_no_loc += 1

        seq = next(
            (sr.get("action_image_seq_urls", [])
             for sr in images.get("scene_refs", [])
             if sr.get("order_index") == s.get("order_index")),
            [],
        )
        scene_seq_count.append(len(seq))
        if len(seq) == 0:
            scenes_with_no_stills += 1

        # Detect Sadhguru-leak in scenes that don't have him
        prompt = s.get("prompt") or {}
        vp = (prompt.get("video_prompt") or "").lower()
        has_sadhguru_link = any("sadhguru" in c.lower() for c in chars)
        leak_tokens = [t for t in SADHGURU_TOKENS if t in vp]
        if leak_tokens and not has_sadhguru_link:
            char_hallucination.append({
                "scene": s.get("order_index"),
                "linked_chars": chars,
                "leaked_tokens": leak_tokens,
            })

    # Cross-scene frame similarity — proxy for scene-bleed
    video_dir = STORAGE_ROOT / "videos" / project_id
    similarity_pairs = []
    last_frames: dict[int, str] = {}
    for i, s in enumerate(scenes):
        order_idx = s.get("order_index")
        files = list(video_dir.glob(f"scene_{order_idx:03d}_*.mp4"))
        if not files:
            continue
        h_start = sample_frame_hash(files[0], 0)
        h_mid = sample_frame_hash(files[0], 30)
        if h_mid:
            last_frames[order_idx] = h_mid
        if i > 0 and (order_idx - 1) in last_frames and h_start:
            sim = hamming_like(last_frames[order_idx - 1], h_start)
            similarity_pairs.append({
                "from": order_idx - 1, "to": order_idx, "similarity": round(sim, 3),
            })

    # All-mid-frames pairwise similarity → high mean = scenes look the same
    mid_hashes = [h for h in last_frames.values() if h]
    pairwise_mid = []
    for i in range(len(mid_hashes)):
        for j in range(i + 1, len(mid_hashes)):
            pairwise_mid.append(hamming_like(mid_hashes[i], mid_hashes[j]))
    mean_pairwise_mid = statistics.mean(pairwise_mid) if pairwise_mid else 0.0
    max_pairwise_mid = max(pairwise_mid) if pairwise_mid else 0.0

    # Final video presence
    final_render = STORAGE_ROOT / "renders" / project_id / "final_render.mp4"

    # Score & flags
    flags: list[str] = []
    if scenes_with_no_char and scenes_with_no_char / max(n_scenes, 1) >= 0.3:
        flags.append("HIGH_UNLINKED_CHAR_RATE")
    if scenes_with_no_stills and scenes_with_no_stills / max(n_scenes, 1) >= 0.3:
        flags.append("MANY_SCENES_WITHOUT_STILLS")
    if scenes_with_no_loc:
        flags.append("MISSING_LOCATIONS")
    if mean_pairwise_mid > 0.55:
        flags.append("HIGH_SCENE_SIMILARITY")
    if max_pairwise_mid > 0.85:
        flags.append("DUPLICATE_LOOKING_SCENES")
    if char_hallucination:
        flags.append("CHARACTER_HALLUCINATION_IN_PROMPTS")
    if not final_render.exists():
        flags.append("NO_FINAL_RENDER")
    if n_locations > 4 and n_scenes <= 6:
        flags.append("TOO_MANY_LOCATIONS")

    score = 100
    score -= 25 if "HIGH_UNLINKED_CHAR_RATE" in flags else 0
    score -= 20 if "MANY_SCENES_WITHOUT_STILLS" in flags else 0
    score -= 15 if "MISSING_LOCATIONS" in flags else 0
    score -= 25 if "DUPLICATE_LOOKING_SCENES" in flags else 0
    score -= 15 if "HIGH_SCENE_SIMILARITY" in flags else 0
    score -= 20 if "CHARACTER_HALLUCINATION_IN_PROMPTS" in flags else 0
    score -= 10 if "TOO_MANY_LOCATIONS" in flags else 0
    score -= 50 if "NO_FINAL_RENDER" in flags else 0
    score = max(0, score)

    return {
        "project_id": project_id,
        "title": project.get("title"),
        "status": project.get("status"),
        "n_scenes": n_scenes,
        "n_locations": n_locations,
        "n_characters": n_characters,
        "scenes_with_no_char": scenes_with_no_char,
        "scenes_with_no_stills": scenes_with_no_stills,
        "scenes_with_no_loc": scenes_with_no_loc,
        "scene_seq_counts": scene_seq_count,
        "char_hallucination": char_hallucination,
        "frame_similarity": {
            "consecutive_pairs": similarity_pairs,
            "all_pairs_mean": round(mean_pairwise_mid, 3),
            "all_pairs_max": round(max_pairwise_mid, 3),
        },
        "final_render": str(final_render) if final_render.exists() else None,
        "flags": flags,
        "score": score,
        "verdict": (
            "GREAT" if score >= 90 and not flags else
            "OK" if score >= 70 else
            "POOR" if score >= 40 else
            "BROKEN"
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project_id")
    p.add_argument("--api", default="http://localhost:8002")
    p.add_argument("--out", help="Write JSON to file (also prints to stdout)")
    args = p.parse_args()

    report = measure(args.api, args.project_id)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return 0 if report["verdict"] in ("GREAT", "OK") else 1


if __name__ == "__main__":
    sys.exit(main())
