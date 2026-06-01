#!/usr/bin/env python
"""CLI wrapper around backend.app.agents.video_evaluator.

Usage
  evaluate_video.py evaluate VIDEO --prompt "..." [--ref-image PATH] [--frames 8] [--device cpu]
  evaluate_video.py suggest --metrics metrics.json [--levers '{"guidance_text":7.5,...}']
  evaluate_video.py loop VIDEO --prompt "..." --levers '{...}' [--ref-image PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app.agents.video_evaluator import Levers, Metrics, evaluate, suggest, to_dict  # noqa: E402


def _print(m: Metrics) -> None:
    print(json.dumps(to_dict(m), indent=2))
    print("\n— verdict —", file=sys.stderr)
    for v in m.verdict:
        print(" ·", v, file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("evaluate", "loop"):
        sp = sub.add_parser(name, help=f"{name} a rendered MP4")
        sp.add_argument("video", type=Path)
        sp.add_argument("--prompt", required=True)
        sp.add_argument("--ref-image", type=Path, default=None)
        sp.add_argument("--frames", type=int, default=8)
        sp.add_argument("--device", default="cpu", choices=["cpu", "cuda:0", "cuda:1"])
        if name == "loop":
            sp.add_argument("--levers", type=str, default="{}")

    sp = sub.add_parser("suggest", help="propose lever deltas from a metrics JSON")
    sp.add_argument("--metrics", type=Path, required=True)
    sp.add_argument("--levers", type=str, default="{}")

    args = ap.parse_args()

    if args.cmd == "evaluate":
        m = evaluate(args.video, args.prompt, args.ref_image, args.frames, args.device)
        _print(m)
        return 0

    if args.cmd == "suggest":
        m_dict = json.loads(args.metrics.read_text())
        m = Metrics(**{k: v for k, v in m_dict.items() if k in Metrics.__dataclass_fields__})
        out = suggest(m, Levers.from_dict(json.loads(args.levers)))
        print(json.dumps(out, indent=2))
        return 0

    if args.cmd == "loop":
        m = evaluate(args.video, args.prompt, args.ref_image, args.frames, args.device)
        _print(m)
        out = suggest(m, Levers.from_dict(json.loads(args.levers)))
        print("\n— suggestion —", file=sys.stderr)
        print(json.dumps(out, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
