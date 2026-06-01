"""Core video-evaluation logic: per-clip metrics + lever-tuning suggestions.

Used by both the CLI (scripts/evaluate_video.py) and the post-stitch celery
task (task_evaluate_project). Defaults to CPU so it never fights an active
video-gen run for GPU.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Levers:
    num_inference_steps: int = 50
    guidance_text: float = 7.5
    guidance_img: float = 5.0
    seed: int = 42
    num_frames: int = 81

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Levers":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Metrics:
    video: str
    frames_sampled: int
    clip: dict[str, float] = field(default_factory=dict)
    identity: dict[str, float] = field(default_factory=dict)
    motion: dict[str, float] = field(default_factory=dict)
    smoothness: dict[str, float] = field(default_factory=dict)
    verdict: list[str] = field(default_factory=list)


def _sample_frames(path: Path, n: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            raise RuntimeError(f"no frames in {path}")
        idxs = np.linspace(0, total - 1, min(n, total), dtype=int)
        frames: list[np.ndarray] = []
        for i in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, frame = cap.read()
            if ok:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        return frames
    finally:
        cap.release()


def _all_gray_frames(path: Path, max_n: int = 60) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    try:
        out: list[np.ndarray] = []
        while len(out) < max_n:
            ok, frame = cap.read()
            if not ok:
                break
            out.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        return out
    finally:
        cap.release()


def _clip_score(frames: list[np.ndarray], prompt: str, device: str) -> dict[str, float]:
    from PIL import Image
    import torch
    from transformers import CLIPModel, CLIPProcessor
    name = "openai/clip-vit-base-patch32"
    proc = CLIPProcessor.from_pretrained(name)
    model = CLIPModel.from_pretrained(name).to(device).eval()
    imgs = [Image.fromarray(f) for f in frames]
    with torch.no_grad():
        inp = proc(text=[prompt], images=imgs, return_tensors="pt", padding=True, truncation=True).to(device)
        out = model(**inp)
        img_e = out.image_embeds / out.image_embeds.norm(dim=-1, keepdim=True)
        txt_e = out.text_embeds / out.text_embeds.norm(dim=-1, keepdim=True)
        sims = (img_e @ txt_e.T).squeeze(-1).cpu().numpy()
    return {"mean": float(sims.mean()), "min": float(sims.min()), "max": float(sims.max())}


def _identity_score(frames: list[np.ndarray], ref_path: Path, device: str) -> dict[str, float]:
    from insightface.app import FaceAnalysis
    ctx = 0 if device.startswith("cuda") else -1
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if ctx == 0 else ["CPUExecutionProvider"]
    app = FaceAnalysis(name="buffalo_l", providers=providers)
    app.prepare(ctx_id=ctx, det_size=(640, 640))
    ref_img = cv2.cvtColor(cv2.imread(str(ref_path)), cv2.COLOR_BGR2RGB)
    ref_faces = app.get(ref_img)
    if not ref_faces:
        return {"mean": 0.0, "frames_with_face": 0.0, "ref_face_found": 0.0}
    ref_emb = ref_faces[0].normed_embedding
    sims, hits = [], 0
    for f in frames:
        faces = app.get(f)
        if faces:
            hits += 1
            sims.append(float(np.dot(faces[0].normed_embedding, ref_emb)))
    return {
        "mean": float(np.mean(sims)) if sims else 0.0,
        "frames_with_face": hits / max(1, len(frames)),
        "ref_face_found": 1.0,
    }


def _motion_and_smoothness(gray: list[np.ndarray]) -> tuple[dict[str, float], dict[str, float]]:
    if len(gray) < 2:
        return {"mean_flow_mag": 0.0}, {"mean_ssim": 1.0}
    mags, ssims = [], []
    for a, b in zip(gray[:-1], gray[1:]):
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mags.append(float(np.linalg.norm(flow, axis=2).mean()))
        a32, b32 = a.astype(np.float32), b.astype(np.float32)
        num = ((a32 - a32.mean()) * (b32 - b32.mean())).mean()
        den = (a32.std() * b32.std()) + 1e-6
        ssims.append(float(np.clip(num / den, -1.0, 1.0)))
    return {"mean_flow_mag": float(np.mean(mags))}, {"mean_ssim": float(np.mean(ssims))}


def _verdict(m: Metrics) -> list[str]:
    out = []
    c = m.clip.get("mean", 0)
    out.append(f"prompt_adherence: {'weak' if c < 0.22 else 'ok' if c < 0.28 else 'strong'} ({c:.3f})")
    if m.identity:
        i = m.identity.get("mean", 0)
        fhit = m.identity.get("frames_with_face", 0)
        out.append(f"identity: {'weak' if i < 0.30 else 'ok' if i < 0.45 else 'strong'} ({i:.3f}, face_hit={fhit:.0%})")
    flow = m.motion.get("mean_flow_mag", 0)
    out.append(f"motion: {'static' if flow < 0.4 else 'ok' if flow < 6 else 'frantic'} ({flow:.2f} px/frame)")
    s = m.smoothness.get("mean_ssim", 1)
    out.append(f"smoothness: {'jittery' if s < 0.80 else 'ok' if s < 0.97 else 'too_static'} ({s:.3f})")
    return out


def evaluate(video: Path, prompt: str | None, ref_image: Path | None,
             n_frames: int = 8, device: str = "cpu") -> Metrics:
    frames = _sample_frames(video, n_frames)
    gray = _all_gray_frames(video, max_n=60)
    m = Metrics(video=str(video), frames_sampled=len(frames))
    if prompt:
        m.clip = _clip_score(frames, prompt, device)
    if ref_image and ref_image.exists():
        m.identity = _identity_score(frames, ref_image, device)
    m.motion, m.smoothness = _motion_and_smoothness(gray)
    m.verdict = _verdict(m)
    return m


def suggest(metrics: Metrics, levers: Levers) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    reasons: list[str] = []

    c = metrics.clip.get("mean", 1.0)
    if metrics.clip and c < 0.22:
        new = min(12.0, round(levers.guidance_text + 1.0, 2))
        if new != levers.guidance_text:
            deltas["guidance_text"] = new
            reasons.append(f"low CLIP ({c:.3f}) → guidance_text +1.0 → {new}")
        else:
            new_steps = min(80, levers.num_inference_steps + 10)
            deltas["num_inference_steps"] = new_steps
            reasons.append(f"low CLIP, guidance_text capped → steps +10 → {new_steps}")

    if metrics.identity:
        i = metrics.identity.get("mean", 1.0)
        if i < 0.30 and metrics.identity.get("ref_face_found", 0) == 1.0:
            new = min(10.0, round(levers.guidance_img + 1.0, 2))
            if new != levers.guidance_img:
                deltas["guidance_img"] = new
                reasons.append(f"low identity ({i:.3f}) → guidance_img +1.0 → {new}")

    flow = metrics.motion.get("mean_flow_mag", 1.0)
    smooth = metrics.smoothness.get("mean_ssim", 0.9)
    if flow < 0.4 or smooth > 0.97:
        deltas["seed"] = (levers.seed + 17) % 100_000
        reasons.append(f"static (flow={flow:.2f}, ssim={smooth:.3f}) → reseed → {deltas['seed']}")
        if levers.guidance_text > 5.5:
            deltas["guidance_text"] = round(levers.guidance_text - 0.5, 2)
            reasons.append(f"static → guidance_text -0.5 → {deltas['guidance_text']}")
    elif smooth < 0.80:
        new_steps = min(80, levers.num_inference_steps + 10)
        deltas["num_inference_steps"] = new_steps
        reasons.append(f"jittery (ssim={smooth:.3f}) → steps +10 → {new_steps}")

    return {"current": asdict(levers), "deltas": deltas, "reasons": reasons}


def to_dict(m: Metrics) -> dict[str, Any]:
    return asdict(m)
