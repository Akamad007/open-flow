#!/usr/bin/env python3
"""Manual FrameINO inference using the local 10 GB transformer weights.

FrameINO is an I2V model that takes:
  1. A canvas image  (input frame — the scene + starting subject placement)
  2. A trajectory    (list of (x, y) points the subject travels through)
  3. An ID reference (optional — keeps subject identity stable)
  4. A text prompt   (scene description)

This is a standalone CLI that bypasses the production wan22 pipeline. The
production pipeline uses vanilla TI2V-5B (FrameINO is architecturally
incompatible with WanPipeline — it needs the custom WanImageToVideoPipeline
from the UVA repo with 96-channel input encoding for trajectory + ID).

Example:
    python scripts/frameino_manual.py \\
        --prompt "A sprinter explodes from blocks down a dawn track" \\
        --canvas /tmp/track_canvas.jpg \\
        --id-image /tmp/sprinter_portrait.jpg \\
        --trajectory "100,240;400,240;700,240" \\
        --output /tmp/sprinter_frameino.mp4

Trajectory coordinates are in (x, y) pixels relative to --canvas-width by
--canvas-height. Multiple points become a path; the script linearly samples
it down to one (x, y) per output frame.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
from PIL import Image

# Wire the FrameINO repo into sys.path so we can import their custom pipeline.
FRAMEINO_REPO = Path("/home/akash/FrameINO-repo")
if not FRAMEINO_REPO.exists():
    sys.exit(f"FrameINO repo not found at {FRAMEINO_REPO} — clone it first.")
sys.path.insert(0, str(FRAMEINO_REPO))

from architecture.autoencoder_kl_wan import AutoencoderKLWan  # noqa: E402
from architecture.transformer_wan import WanTransformer3DModel  # noqa: E402
from data_loader.video_dataset_motion import VideoDataset_Motion  # noqa: E402
from diffusers.utils import export_to_video  # noqa: E402
from pipelines.pipeline_wan_i2v_motion_FrameINO import WanImageToVideoPipeline  # noqa: E402

# Local paths
LOCAL_FRAMEINO_TRANSFORMER = "/home/akash/Wan2.2-Models/FrameINO-5B-MotionINO-v1.6"
BASE_MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"  # for VAE + scheduler + text encoder


def parse_trajectory(spec: str) -> list[tuple[int, int]]:
    """'100,240;400,240;700,240' → [(100,240), (400,240), (700,240)]."""
    pts: list[tuple[int, int]] = []
    for chunk in spec.split(";"):
        x_str, y_str = chunk.strip().split(",")
        pts.append((int(x_str), int(y_str)))
    if len(pts) < 2:
        raise ValueError("Trajectory needs at least 2 points")
    return pts


def sample_traj_uniform(points: list[tuple[int, int]], num_samples: int) -> list[tuple[int, int]]:
    """Linearly sample points along the polyline by arc length. Mirrors
    app.py:sample_traj_by_length."""
    pts = np.array(points, dtype=float)
    seg = pts[1:] - pts[:-1]
    seg_len = np.sqrt((seg ** 2).sum(axis=1))
    cum = np.cumsum(seg_len)
    total = cum[-1]
    targets = np.linspace(0, total, num_samples)
    out: list[tuple[int, int]] = []
    for t in targets:
        idx = int(np.searchsorted(cum, t))
        prev_cum = 0.0 if idx == 0 else cum[idx - 1]
        seg_t = (t - prev_cum) / max(seg_len[min(idx, len(seg_len) - 1)], 1e-9)
        a, b = pts[min(idx, len(pts) - 1)], pts[min(idx + 1, len(pts) - 1)]
        p = a + seg_t * (b - a)
        out.append((int(p[0]), int(p[1])))
    return out


def load_canvas(path: str, width: int, height: int) -> np.ndarray:
    img = Image.open(path).convert("RGB").resize((width, height), Image.LANCZOS)
    return np.array(img)


def load_id_image(path: str | None, width: int, height: int) -> np.ndarray:
    """Returns a (H, W, 3) uint8 array. No SAM masking — caller should crop/mask
    the subject in advance. None → black placeholder (unconditional ID)."""
    if not path:
        return np.zeros((height, width, 3), dtype=np.uint8)
    img = Image.open(path).convert("RGB")
    ref_h, ref_w = img.height, img.width
    scale = min(height / ref_h, width / ref_w)
    new_w, new_h = int(ref_w * scale), int(ref_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    arr = np.array(img)
    pad_top = (height - new_h) // 2
    pad_bot = height - new_h - pad_top
    pad_left = (width - new_w) // 2
    pad_right = width - new_w - pad_left
    return np.pad(arr, ((pad_top, pad_bot), (pad_left, pad_right), (0, 0)),
                  mode="constant", constant_values=0)


def build_id_tensor(id_img: np.ndarray) -> torch.Tensor:
    """ID_tensor shape: (B=1, C=3, F=1, H, W), values in [-1, 1]."""
    t = torch.tensor(id_img).float() / 255.0 * 2.0 - 1.0  # H, W, 3
    t = t.permute(2, 0, 1).contiguous()                   # 3, H, W
    return t.unsqueeze(0).unsqueeze(2)                    # 1, 3, 1, H, W


def run_clip(pipe, canvas_img, id_img, traj_pts_raw, args, label):
    """Run one FrameINO inference. Returns list of PIL frames."""
    sampled = sample_traj_uniform(parse_trajectory(traj_pts_raw), args.num_frames)
    full_pred_tracks = [[[pt]] for pt in sampled]
    traj_tensor, *_ = VideoDataset_Motion.prepare_traj_tensor(
        full_pred_tracks, args.height, args.width,
        [], args.dot_radius, args.width, args.height,
        idx=0, first_frame_img=canvas_img,
    )
    id_tensor = build_id_tensor(id_img) if args.id_image else None
    print(f"[FrameINO] {label}: denoising ({args.steps} steps, CFG {args.guidance}, "
          f"{args.num_frames}f @ {args.width}x{args.height}) traj={traj_pts_raw}")
    out = pipe(
        image=Image.fromarray(canvas_img),
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
        traj_tensor=traj_tensor,
        ID_tensor=id_tensor,
        height=args.height, width=args.width,
        num_frames=args.num_frames,
        num_inference_steps=args.steps,
        guidance_scale=args.guidance,
    )
    return out.frames[0]


def concat_clips_ffmpeg(clip_paths: list[Path], out_path: Path) -> None:
    """Stream-copy concat using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for cp in clip_paths:
            f.write(f"file '{cp.resolve()}'\n")
        list_file = f.name
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c", "copy", str(out_path)],
        check=True, capture_output=True,
    )
    Path(list_file).unlink()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prompt", required=True)
    p.add_argument("--canvas", required=True, help="Path to initial canvas / first-frame image")
    p.add_argument("--id-image", default=None, help="Path to subject ID reference (pre-masked) or omit for unconditional")
    p.add_argument("--trajectory", help="Single-clip path: 'x1,y1;x2,y2;...'. Mutually exclusive with --clips.")
    p.add_argument("--clips", help="Multi-clip continuity: trajectories separated by '|'. Each clip uses prev clip's last frame as canvas.")
    p.add_argument("--output", default="/tmp/frameino_out.mp4")
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--num-frames", type=int, default=81)
    p.add_argument("--steps", type=int, default=50)
    p.add_argument("--guidance", type=float, default=5.0)
    p.add_argument("--negative-prompt", default="blurry, low quality, distorted, watermark")
    p.add_argument("--dot-radius", type=int, default=6, help="Visual size of trajectory dots in the traj tensor")
    p.add_argument("--fps", type=int, default=8)
    args = p.parse_args()

    if not (args.trajectory or args.clips):
        p.error("Provide --trajectory (single clip) or --clips (continuity chain).")
    if args.trajectory and args.clips:
        p.error("--trajectory and --clips are mutually exclusive.")

    trajectories = args.clips.split("|") if args.clips else [args.trajectory]
    print(f"[FrameINO] canvas={args.canvas} clips={len(trajectories)}")

    canvas_img = load_canvas(args.canvas, args.width, args.height)
    id_img = load_id_image(args.id_image, args.width, args.height)

    print("[FrameINO] loading transformer (10 GB)...")
    transformer = WanTransformer3DModel.from_pretrained(
        LOCAL_FRAMEINO_TRANSFORMER, torch_dtype=torch.float16,
    )
    print("[FrameINO] loading VAE from base TI2V-5B (fp32, required for latents_mean/std)...")
    vae = AutoencoderKLWan.from_pretrained(BASE_MODEL_ID, subfolder="vae", torch_dtype=torch.float32)
    print("[FrameINO] assembling pipeline (bf16)...")
    pipe = WanImageToVideoPipeline.from_pretrained(
        BASE_MODEL_ID, transformer=transformer, vae=vae, torch_dtype=torch.bfloat16,
    )
    pipe.enable_sequential_cpu_offload()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clip_paths: list[Path] = []
    current_canvas = canvas_img

    for i, traj in enumerate(trajectories):
        frames = run_clip(pipe, current_canvas, id_img, traj.strip(), args, f"clip {i + 1}/{len(trajectories)}")
        clip_path = out_path.with_name(f"{out_path.stem}_clip{i:02d}.mp4")
        export_to_video(frames, str(clip_path), fps=args.fps)
        clip_paths.append(clip_path)
        last = frames[-1]
        if hasattr(last, "convert"):
            current_canvas = np.array(last.convert("RGB"))
        else:
            arr = np.asarray(last)
            if arr.dtype.kind == "f":
                arr = (arr.clip(0, 1) * 255).astype(np.uint8)
            current_canvas = arr if arr.ndim == 3 else arr.squeeze()
        print(f"[FrameINO] wrote {clip_path}  ({len(frames)}f, last-frame chained)")

    if len(clip_paths) == 1:
        clip_paths[0].rename(out_path)
        print(f"[FrameINO] wrote {out_path}")
    else:
        concat_clips_ffmpeg(clip_paths, out_path)
        print(f"[FrameINO] wrote {out_path}  ({len(clip_paths)} clips concatenated)")


if __name__ == "__main__":
    main()
