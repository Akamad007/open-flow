#!/usr/bin/env python
"""Score a yoga_mat (or any) ad project against the rubric in
docs/ad-quality-metrics.md.

Computes the cheap metrics we can automate (M1, M3, M6, M7, M9, M10).
Color/outfit metrics (M2, M4, M8) require hand-grading for now and are
left blank in the JSON output.

Usage:
    python eval_run.py <project_uuid>

Writes JSON to docs/runs/<timestamp>__<short_uuid>.json plus a one-line
summary appended to docs/runs/INDEX.md.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).parent
STORAGE = ROOT / "backend" / "storage"
RUNS = ROOT / "docs" / "runs"


# InsightFace is ~10x more accurate than OpenCV Haar at counting people in
# the styles of frames LTX produces (close-ups, side angles, high-contrast
# studio lighting). Haar produced false positives on hands/cloth folds and
# missed faces under non-frontal angles. We load it lazily because the
# weights are 100MB and only needed when grading.
_FACE_APP = None


def _face_app():
    global _FACE_APP
    if _FACE_APP is None:
        from insightface.app import FaceAnalysis
        # Loading recognition too: M11 needs face embeddings to score
        # cross-frame identity coherence.
        app = FaceAnalysis(name="buffalo_l",
                           allowed_modules=["detection", "recognition"],
                           providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _FACE_APP = app
    return _FACE_APP


def _faces(img_path: Path) -> int:
    img = cv2.imread(str(img_path))
    if img is None:
        return 0
    return len(_face_app().get(img))


def _video_face_counts(mp4: Path, sample_every: float = 0.5) -> list[int]:
    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 12.0
    step = max(1, int(fps * sample_every))
    counts: list[int] = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            counts.append(len(_face_app().get(frame)))
        i += 1
    cap.release()
    return counts


def _optical_flow_mean(mp4: Path) -> float:
    cap = cv2.VideoCapture(str(mp4))
    ok, prev = cap.read()
    if not ok:
        return 0.0
    prev_g = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    mags: list[float] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        cur_g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            prev_g, cur_g, None, 0.5, 3, 15, 3, 5, 1.2, 0,
        )
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        mags.append(float(mag.mean()))
        prev_g = cur_g
    cap.release()
    return float(np.mean(mags)) if mags else 0.0


def _beat_distinctness(breakdowns: list[str]) -> float:
    """Stem the leading verb of each beat line; ratio of unique stems."""
    if not breakdowns:
        return 0.0
    stems: list[str] = []
    for bd in breakdowns:
        for line in (bd or "").split("\n"):
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^\d+[-–]\d+\s*s\s*[:\.]?\s*", "", line, flags=re.IGNORECASE)
            m = re.match(r"\b([a-z]+)\b", line.lower())
            if not m:
                continue
            verb = m.group(1)
            verb = re.sub(r"(ing|ed|es|s)$", "", verb)
            stems.append(verb)
    if not stems:
        return 0.0
    return len(set(stems)) / len(stems)


def _arc_score(purposes: list[str]) -> float:
    """≥2 distinct scene_purpose values → 1.0; only 1 → 0.0."""
    return 1.0 if len(set(p for p in purposes if p)) >= 2 else 0.0


def _stills_one_person_score(stills: list[Path]) -> tuple[float, list[int]]:
    counts = [_faces(p) for p in stills]
    if not counts:
        return 0.0, []
    ok = sum(1 for c in counts if c == 1)
    return ok / len(counts), counts


def _video_one_person_score(per_scene: dict[str, list[int]]) -> float:
    flat = [c for cs in per_scene.values() for c in cs]
    if not flat:
        return 0.0
    return sum(1 for c in flat if c == 1) / len(flat)


def _motion_score(flow_mags: list[float]) -> float:
    """Target: ≥1.5 px/frame mean. Score linearly capped at 1.0."""
    if not flow_mags:
        return 0.0
    return min(1.0, float(np.mean(flow_mags)) / 1.5)


def _bg_score(bg_face_count: int) -> float:
    return 1.0 if bg_face_count == 0 else 0.0


def _chest_bgr(img: np.ndarray) -> np.ndarray:
    """Mean BGR over a torso band: 35-55% height, central 50% width."""
    h, w = img.shape[:2]
    crop = img[int(h * 0.35):int(h * 0.55), int(w * 0.25):int(w * 0.75)]
    return crop.reshape(-1, 3).mean(axis=0)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _pairwise_mean(values: list[np.ndarray], fn) -> float:
    """Mean of fn(a,b) across distinct unordered pairs in values."""
    if len(values) < 2:
        return 0.0
    out: list[float] = []
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            out.append(fn(values[i], values[j]))
    return float(np.mean(out)) if out else 0.0


def _stills_outfit_match_score(stills: list[Path]) -> float:
    """M4: pairwise chest-color cosine across all stills. Outfit consistent
    across the 12 stills → ~1.0; drift → lower."""
    colors: list[np.ndarray] = []
    for p in stills:
        img = cv2.imread(str(p))
        if img is None:
            continue
        colors.append(_chest_bgr(img))
    return _pairwise_mean(colors, _cosine)


def _face_bbox_norm(img_path: Path) -> tuple[float, float, float, float] | None:
    """Returns the largest face's (cx, cy, w, h) normalized to [0,1] image
    extents, or None if no face detected."""
    img = cv2.imread(str(img_path))
    if img is None:
        return None
    H, W = img.shape[:2]
    faces = _face_app().get(img)
    if not faces:
        return None
    # Pick the largest face when multiple
    f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    x1, y1, x2, y2 = f.bbox
    return (((x1 + x2) / 2) / W, ((y1 + y2) / 2) / H,
            (x2 - x1) / W, (y2 - y1) / H)


def _pose_variance_per_scene(stills: list[Path]) -> float:
    """M5: pairwise L2 distance between face bbox signatures (cx,cy,w,h)
    *within the same scene*, averaged across scenes. Different body poses
    → different head position/size in frame → larger signature distance.
    Target 0.10 normalized → 1.0 (head moved ~10% of frame extent on
    average between any two stills of the scene)."""
    by_scene: dict[str, list[np.ndarray]] = {}
    for p in stills:
        bb = _face_bbox_norm(p)
        if bb is None:
            continue
        scene_key = p.stem.split("_s")[0]
        by_scene.setdefault(scene_key, []).append(np.array(bb, dtype=np.float32))
    if not by_scene:
        return 0.0
    scene_means: list[float] = []
    for vecs in by_scene.values():
        if len(vecs) < 2:
            continue
        scene_means.append(
            _pairwise_mean(vecs, lambda a, b: float(np.linalg.norm(a - b)))
        )
    if not scene_means:
        return 0.0
    return min(1.0, float(np.mean(scene_means)) / 0.10)


def _video_face_consistency(mp4: Path, sample_every: float = 0.5) -> float:
    """M11: pairwise cosine of InsightFace embeddings across video frames.
    Same face across all frames → ~1.0; identity drift mid-clip → lower.
    Skips frames where 0 or >1 faces detected (those are M6's job)."""
    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 12.0
    step = max(1, int(fps * sample_every))
    embeds: list[np.ndarray] = []
    i = 0
    app = _face_app()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            faces = app.get(frame)
            if len(faces) == 1:
                emb = getattr(faces[0], "normed_embedding", None)
                if emb is None:
                    emb = faces[0].embedding / (np.linalg.norm(faces[0].embedding) + 1e-8)
                embeds.append(np.asarray(emb, dtype=np.float32))
        i += 1
    cap.release()
    return _pairwise_mean(embeds, _cosine)


_MOTION_KEYWORDS = (
    "run", "running", "jog", "sprint", "walk", "stride", "step", "march",
    "jump", "leap", "hop", "skip", "dance", "twirl", "spin",
    "kneel", "kneels", "kneeling", "stand", "stands", "rise", "rises",
    "sit", "sits", "settle", "lift", "lifts", "raise", "raises",
    "bend", "bends", "stretch", "reaches", "swing", "throws", "pushes",
    "shoulders", "lac", "wears", "puts on", "shrug", "buttons",
)


def _scene_needs_full_body(breakdown: str) -> bool:
    """A scene needs full-body framing if its beats describe body motion."""
    if not breakdown:
        return False
    text = breakdown.lower()
    return any(kw in text for kw in _MOTION_KEYWORDS)


def _full_body_score(mp4: Path, sample_every: float = 0.5) -> float:
    """M12: % of frames in this scene where the face is positioned for
    full-body framing (face in upper third, face height < 12% of frame
    height). Heuristic — proxies for head-to-toe-in-frame without
    requiring a body-pose model."""
    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 12.0
    step = max(1, int(fps * sample_every))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1)
    app = _face_app()
    full_body = 0
    valid = 0
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            faces = app.get(frame)
            if len(faces) == 1:
                valid += 1
                x1, y1, x2, y2 = faces[0].bbox
                face_h = (y2 - y1) / H
                face_bottom = y2 / H
                # Head near top, face small relative to frame: full-body fits
                if face_bottom < 0.40 and face_h < 0.13:
                    full_body += 1
        i += 1
    cap.release()
    if valid == 0:
        return 0.0
    return full_body / valid


def _outfit_stability_score(mp4: Path, sample_every: float = 1.0) -> float:
    """M8: pairwise chest-color cosine across video frames sampled every
    `sample_every` seconds. Stable outfit → ~1.0; drifting outfit → lower."""
    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 12.0
    step = max(1, int(fps * sample_every))
    colors: list[np.ndarray] = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            colors.append(_chest_bgr(frame))
        i += 1
    cap.release()
    return _pairwise_mean(colors, _cosine)


def _read_db(project_id: str) -> dict:
    """Read screenplay structure from postgres."""
    import psycopg2
    conn = psycopg2.connect(
        "postgresql://storyvideouser:storyvideopass@localhost:5432/storyvideo"
    )
    cur = conn.cursor()
    cur.execute(
        "SELECT order_index, duration_seconds, scene_purpose, visual_summary "
        "FROM scenes WHERE project_id=%s ORDER BY order_index;",
        (project_id,),
    )
    scenes = cur.fetchall()
    cur.execute(
        "SELECT s.order_index, p.scene_breakdown, p.action_description, p.video_prompt "
        "FROM scenes s LEFT JOIN scene_prompts p ON p.scene_id=s.id "
        "WHERE s.project_id=%s ORDER BY s.order_index;",
        (project_id,),
    )
    prompts = cur.fetchall()
    cur.execute("SELECT story_summary FROM projects WHERE id=%s;", (project_id,))
    summary = cur.fetchone()
    cur.close()
    conn.close()
    return {
        "scenes": scenes,
        "prompts": prompts,
        "story_summary": summary[0] if summary else "",
    }


WEIGHTS = {
    # Bg quality
    "M1": 0.10,
    # Portrait/still quality (skipped under F-TEXT-ONLY-LTX — pregen off)
    "M2": 0.05, "M3": 0.05, "M4": 0.025, "M5": 0.025,
    # Video quality (the actual deliverable)
    "M6": 0.125, "M7": 0.125, "M8": 0.10, "M11": 0.125,
    # Screenplay / arc
    "M9": 0.05, "M10": 0.05,
    # Full-body framing on motion-heavy scenes (running, dancing, kneeling,
    # etc.) — user-flagged as critical for "actual ads".
    "M12": 0.175,
}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: eval_run.py <project_uuid>", file=sys.stderr)
        return 2
    project_id = sys.argv[1]

    bg_dir = STORAGE / "backgrounds" / project_id
    char_dir = STORAGE / "characters" / project_id
    stills_dir = STORAGE / "scene_actions" / project_id
    videos_dir = STORAGE / "videos" / project_id

    bg_pngs = sorted(bg_dir.glob("*.png"))
    bg_faces = max((_faces(p) for p in bg_pngs), default=0) if bg_pngs else 0

    stills = sorted(p for p in stills_dir.glob("scene_*.png") if "_opaque" not in p.stem)
    m3, still_face_counts = _stills_one_person_score(stills)

    scene_videos = sorted(videos_dir.glob("scene_*.mp4"))
    per_scene_face_counts: dict[str, list[int]] = {}
    flow_mags: list[float] = []
    for v in scene_videos:
        per_scene_face_counts[v.name] = _video_face_counts(v)
        flow_mags.append(_optical_flow_mean(v))

    db = _read_db(project_id)
    breakdowns = [row[1] for row in db["prompts"] if row[1]]
    purposes = [row[2] for row in db["scenes"]]

    # F-TEXT-ONLY-LTX: when image_pregen is disabled, stills won't exist
    # on disk. M3/M4/M5 should be None (skipped from weighted total),
    # not 0 — otherwise their absence drags auto_total down artificially.
    has_stills = bool(stills)
    m3 = m3 if has_stills else None
    m4 = _stills_outfit_match_score(stills) if has_stills else None
    m5 = _pose_variance_per_scene(stills) if has_stills else None
    m8_per_scene = [_outfit_stability_score(v) for v in scene_videos]
    m8 = float(np.mean(m8_per_scene)) if m8_per_scene else 0.0
    m11_per_scene = [_video_face_consistency(v) for v in scene_videos]
    m11 = float(np.mean(m11_per_scene)) if m11_per_scene else 0.0

    # M12: full-body framing per scene, ONLY scored on scenes whose beats
    # describe body motion. Non-motion scenes contribute None (skipped).
    breakdown_by_idx = {row[0]: (row[1] or "") for row in db["prompts"]}
    m12_per_scene: list[float] = []
    for v in scene_videos:
        # filename: scene_NNN_<uuid>.mp4 → idx N
        try:
            idx = int(v.stem.split("_")[1])
        except (ValueError, IndexError):
            continue
        if not _scene_needs_full_body(breakdown_by_idx.get(idx, "")):
            continue
        m12_per_scene.append(_full_body_score(v))
    m12 = float(np.mean(m12_per_scene)) if m12_per_scene else None

    metrics = {
        "M1_bg_zero_people": _bg_score(bg_faces),
        "M2_portrait_outfit_match": None,  # hand-grade — single-portrait color vs spec
        "M3_stills_one_person": m3,
        "M4_stills_outfit_match": m4,
        "M5_pose_variance": m5,
        "M6_video_one_person": _video_one_person_score(per_scene_face_counts),
        "M7_motion_magnitude": _motion_score(flow_mags),
        "M8_outfit_stability": m8,
        "M9_beat_distinctness": _beat_distinctness(breakdowns),
        "M10_story_has_arc": _arc_score(purposes),
        "M11_video_face_consistency": m11,
        "M12_full_body_when_needed": m12,
    }

    # Weighted total over the auto-graded subset (renormalize weights so
    # missing metrics don't drag the score to zero).
    auto_keys = [k for k, v in metrics.items() if v is not None]
    auto_w_sum = sum(WEIGHTS[k.split("_")[0]] for k in auto_keys)
    total = sum(metrics[k] * WEIGHTS[k.split("_")[0]] for k in auto_keys) / max(auto_w_sum, 1e-6)

    out = {
        "project_id": project_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "auto_total": total,
        "raw": {
            "bg_face_count": bg_faces,
            "still_face_counts": still_face_counts,
            "video_face_counts_per_scene": per_scene_face_counts,
            "flow_mags_per_scene": flow_mags,
            "scene_purposes": purposes,
            "story_summary": db["story_summary"],
        },
    }

    RUNS.mkdir(parents=True, exist_ok=True)
    short = project_id[:8]
    out_path = RUNS / f"{out['timestamp'].replace(':','-')}__{short}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
