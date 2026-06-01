"""Standalone 30-second ad demo using Wan22VideoProvider with smart LoRA selection.

Renders 6 × 5s scenes spanning different scene_types, then stitches with ffmpeg.
Demonstrates the full provider + classifier + post-process chain end-to-end.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ["GPU_PYTHON_PATH"] = "/home/akash/.pyenv/versions/video-app/bin/python"

sys.path.insert(0, "/home/akash/PycharmProjects/video-app/backend")
from app.providers.video.wan22_provider import Wan22VideoProvider

OUT_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/demo_30s_ad")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 6 prompts spanning scene types — exercises 4+ LoRAs, both post-process branches.
SCENES = [
    ("01_chef_flames",   "A chef in a black apron tosses vegetables into a wok over leaping orange flames, closeup of hands and pan, dramatic kitchen lighting"),
    ("02_runner_park",   "A man in athletic gear running through a tree-lined park at golden hour, side view, full body visible, autumn leaves on the ground, wide shot, cinematic"),
    ("03_model_runway",  "A fashion model in a designer coat strutting down a runway with a brown leather handbag, soft editorial lighting, medium shot, blurred audience"),
    ("04_samurai_war",   "A samurai warrior in heavy armor charging across a misty ancient battlefield, swords drawn, dramatic golden lighting, cinematic wide shot"),
    ("05_dancer_red",    "Closeup of a dancer spinning in a flowing red dress, warm tungsten backlight, slow motion feel, intimate portrait framing"),
    ("06_rally_crowd",   "A massive crowd chanting in unison at an outdoor evening rally, raised fists, banners waving overhead, energetic atmosphere, wide cinematic shot"),
]


async def render_scene(provider, name: str, prompt: str) -> dict:
    out_path = OUT_DIR / f"{name}.mp4"
    print(f"\n[{time.strftime('%H:%M:%S')}] === {name} ===")
    print(f"prompt: {prompt[:100]}...")
    t0 = time.time()
    result = await provider.generate_video(
        prompt=prompt,
        negative_prompt="blurry, low quality, distorted, oversaturated, watermark, text, logo, deformed hands, extra limbs",
        output_path=out_path,
    )
    elapsed = time.time() - t0
    status = "OK" if result.success else "FAIL"
    print(f"[{status}] {elapsed:.0f}s  meta={result.metadata}")
    if not result.success:
        print(f"   error: {result.error}")
    return {"name": name, "success": result.success, "elapsed_s": elapsed,
            "path": result.file_path, "metadata": result.metadata}


def stitch(scene_paths: list[Path], out: Path):
    listf = out.with_suffix(".txt")
    listf.write_text("\n".join(f"file '{p.absolute()}'" for p in scene_paths))
    # Re-encode to ensure uniform output (resolutions differ if post-process upscaled some)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listf), "-vf", "scale=1280:720", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "18", str(out)], check=True)
    listf.unlink()


async def main():
    print(f"=== Wan22 30s ad demo — {len(SCENES)} scenes ===")
    provider = Wan22VideoProvider()
    results = []
    for name, prompt in SCENES:
        results.append(await render_scene(provider, name, prompt))

    ok_paths = [Path(r["path"]) for r in results if r["success"]]
    print(f"\n=== Stitching {len(ok_paths)}/{len(SCENES)} scenes ===")
    if ok_paths:
        final = OUT_DIR / "30s_ad_final.mp4"
        stitch(ok_paths, final)
        print(f"\nfinal -> {final}")
        # Summary table
        print("\n=== Summary ===")
        for r in results:
            md = r.get("metadata", {})
            print(f"  {r['name']:25s} {'OK' if r['success'] else 'FAIL':5s} "
                  f"{int(r['elapsed_s']):4d}s  scene={md.get('scene_type','?'):20s} "
                  f"shot={md.get('shot_type','?'):8s} lora={md.get('lora_id','?'):14s}"
                  f"@{md.get('lora_weight','?')}")
    else:
        print("no scenes succeeded — nothing to stitch")


if __name__ == "__main__":
    asyncio.run(main())
