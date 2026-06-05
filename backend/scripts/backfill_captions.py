"""Backfill story-driven per-scene captions and burn them onto final renders.

Captions are STORY captions: one short narrative beat per scene, generated from
the episode's story summary + each scene's generation prompt (text only — never
video frames), in order, so that read in sequence they carry the story forward.
Scenes that already have a caption are skipped unless --force.

Re-burn: for each episode, burns the captions onto the episode's current final
render (always starting from the clean, un-captioned original, so re-runs never
stack) into a NEW `*_captioned.mp4`. The original file is never touched; the
final_render asset + episode.final_video_path are repointed at the captioned one.
Timing reuses the stitch provider's xfade-aware windows, scaled to the render's
real duration.

Usage:
    python scripts/backfill_captions.py --latest                 # newest project
    python scripts/backfill_captions.py --all                    # all, newest first
    python scripts/backfill_captions.py <uuid> [<uuid> ...]      # specific
    python scripts/backfill_captions.py <uuid> --force           # regenerate captions
    python scripts/backfill_captions.py <uuid> --captions-only --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.episode import Episode
from app.models.project import Project
from app.models.scene import Scene
from app.orchestration._common import get_llm_provider
from app.providers.stitching.ffmpeg_provider import FFmpegStitchingProvider
from app.utils.subtitle_burn import burn_subtitles_into_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_captions")

CHUNK = 60
CAPTION_SYS = (
    "You are a storyteller narrating a tale to a viewer watching it unfold. You are given the FULL "
    "story of the episode, then its scenes in order, each with a short hint of what is on screen. "
    "For EACH scene write ONE caption that TELLS THE STORY at that moment — what is happening in the "
    "narrative and WHY it matters (the character's intent, the stakes, the turning point, the "
    "meaning) — using the full story to explain it, so the viewer UNDERSTANDS THE STORY behind the "
    "scene. Do NOT describe the picture, the setting, the action, or the camera. Narrate the story "
    "beat. Read in order, the captions must form a clear, flowing retelling of the story. Each under "
    "~90 characters, present tense, name the character(s), vivid plain language, no quotes. "
    'Return ONLY JSON: {"captions": [{"index": <int>, "caption": "<text>"}]}'
)


def _uuid(s: str) -> uuid.UUID:
    return uuid.UUID(str(s))


def _clean(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split()).strip().strip('"')
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] or text[:limit]


def _scene_hint(scene: Scene, limit: int = 160) -> str:
    """A short 'which moment' hint (no images). The model narrates the story
    meaning from the full-story context, not from this hint."""
    hint = scene.visual_summary or scene.source_excerpt or ""
    return " ".join(hint.split())[:limit]


def _story_context(ep: Episode, proj: Project | None, limit: int = 7000) -> str:
    """Richest available narrative text for the episode (full story preferred)."""
    for text in (
        ep.original_story_text, ep.story_summary,
        (proj.original_story_text if proj else None),
        (proj.story_summary if proj else None),
    ):
        if text and text.strip():
            return " ".join(text.split())[:limit]
    return ""


def _fallback(scene: Scene) -> str:
    return _clean(scene.scene_purpose or scene.visual_summary or "")


async def _generate(llm, story: str, scenes: list[Scene]) -> dict[uuid.UUID, str]:
    """Return {scene_id: story caption}, generated in scene order for coherence."""
    out: dict[uuid.UUID, str] = {}
    for i in range(0, len(scenes), CHUNK):
        batch = scenes[i : i + CHUNK]
        lines = [f"{i + pos}: {_scene_hint(s)}" for pos, s in enumerate(batch)]
        user = (
            f"FULL STORY:\n{story or '(none provided)'}\n\n"
            "SCENES (in order) — write a STORY caption for each index:\n" + "\n".join(lines)
        )
        covered: dict[int, str] = {}
        try:
            data = await llm.complete_json(CAPTION_SYS, user, temperature=0.5, max_tokens=3000)
            items = data.get("captions") if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for it in items or []:
                try:
                    covered[int(it["index"])] = _clean(it.get("caption", ""))
                except (KeyError, ValueError, TypeError):
                    continue
        except Exception:
            logger.exception("caption batch failed at %d — using purpose/summary fallback", i)
        for pos, s in enumerate(batch):
            out[s.id] = covered.get(i + pos) or _fallback(s)
    return out


async def caption_scenes(project_id: str, llm, dry_run: bool, force: bool) -> int:
    total = 0
    async with async_session_factory() as db:
        proj = await db.get(Project, _uuid(project_id))
        episodes = (await db.execute(
            select(Episode).where(Episode.project_id == _uuid(project_id)).order_by(Episode.order_index)
        )).scalars().all()
        for ep in episodes:
            scenes = (await db.execute(
                select(Scene).where(Scene.episode_id == ep.id)
                .options(selectinload(Scene.prompt)).order_by(Scene.order_index)
            )).scalars().all()
            todo = scenes if force else [s for s in scenes if not (s.caption or "").strip()]
            if not todo:
                continue
            story = _story_context(ep, proj)
            logger.info("ep%d %s: captioning %d/%d scene(s)", ep.order_index, ep.title, len(todo), len(scenes))
            total += len(todo)
            if dry_run:
                continue
            caps = await _generate(llm, story, todo)
            for s in todo:
                if caps.get(s.id):
                    s.caption = caps[s.id]
            await db.commit()
    return total


def _build_srt(provider, windows, captions, scale: float) -> tuple[str, int]:
    cues, idx = [], 1
    for (start, end), text in zip(windows, captions):
        text = (text or "").strip()
        if not text:
            continue
        s0 = start * scale + 0.15
        e0 = max(s0 + 0.6, end * scale - 0.15)
        cues.append(f"{idx}\n{provider._srt_ts(s0)} --> {provider._srt_ts(e0)}\n{text}\n")
        idx += 1
    return "\n".join(cues), idx - 1


async def _scene_durations(db, provider, scenes: list[Scene]) -> list[float]:
    durs = []
    for s in scenes:
        va = (await db.execute(
            select(Asset).where(
                Asset.scene_id == s.id, Asset.asset_type == AssetType.scene_video,
                Asset.status == AssetStatus.complete,
            ).order_by(Asset.created_at.desc()).limit(1)
        )).scalars().first()
        d = 0.0
        if va and va.file_path and Path(va.file_path).exists():
            d = await provider._get_duration(Path(va.file_path))
        durs.append(d if d > 0 else float(s.duration_seconds or 4.0))
    return durs


def _clean_original(current: Path) -> Path:
    """Strip a prior caption layer so re-runs burn from the un-captioned source."""
    if current.stem.endswith("_captioned"):
        return current.with_name(current.stem[: -len("_captioned")] + current.suffix)
    return current


async def reburn_episode(db, provider, episode: Episode, dry_run: bool) -> str:
    latest = (await db.execute(
        select(Asset).where(
            Asset.episode_id == episode.id, Asset.asset_type == AssetType.final_render,
            Asset.status == AssetStatus.complete,
        ).order_by(Asset.created_at.desc()).limit(1)
    )).scalars().first()
    current = episode.final_video_path or (latest.file_path if latest else None)
    if not current or not latest:
        return "skip: no final render"
    source = _clean_original(Path(current))
    if not source.exists():
        return f"skip: source missing ({source.name})"

    scenes = (await db.execute(
        select(Scene).where(Scene.episode_id == episode.id).order_by(Scene.order_index)
    )).scalars().all()
    captions = [(s.caption or "").strip() for s in scenes]
    if not any(captions):
        return "skip: no captions set"

    durs = await _scene_durations(db, provider, scenes)
    windows = provider._caption_windows(durs, True, 0.3)
    total = await provider._get_duration(source)
    raw_total = windows[-1][1] if windows else 0.0
    scale = (total / raw_total) if raw_total > 0 else 1.0
    srt_text, n = _build_srt(provider, windows, captions, scale)
    if n == 0:
        return "skip: no captions matched scenes"
    out = source.with_name(f"{source.stem}_captioned{source.suffix}")
    if dry_run:
        return f"DRY: burn {n} captions (scale={scale:.3f}) {source.name} -> {out.name}"

    # Keep the .srt sidecar next to the render so the UI can offer it for download.
    srt = source.with_name(f"{source.stem}_captions.srt")
    srt.write_text(srt_text, encoding="utf-8")
    await burn_subtitles_into_video(source, srt, out)
    latest.file_path = str(out)
    episode.final_video_path = str(out)
    await db.commit()
    return f"burned {n} captions -> {out.name}"


async def reburn_project(project_id: str, provider, dry_run: bool) -> None:
    async with async_session_factory() as db:
        episodes = (await db.execute(
            select(Episode).where(Episode.project_id == _uuid(project_id)).order_by(Episode.order_index)
        )).scalars().all()
        for ep in episodes:
            res = await reburn_episode(db, provider, ep, dry_run)
            logger.info("  ep%d %s: %s", ep.order_index, ep.title, res)


async def _resolve_projects(args) -> list[tuple[str, str]]:
    async with async_session_factory() as db:
        if args.projects:
            rows = (await db.execute(
                select(Project.id, Project.title).where(Project.id.in_([_uuid(p) for p in args.projects]))
            )).all()
            order = {p: i for i, p in enumerate(args.projects)}
            return sorted(((str(i), t) for i, t in rows), key=lambda x: order.get(x[0], 0))
        q = select(Project.id, Project.title).order_by(Project.created_at.desc())
        if args.latest:
            q = q.limit(1)
        return [(str(i), t) for i, t in (await db.execute(q)).all()]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="*", help="project UUIDs (order preserved)")
    ap.add_argument("--latest", action="store_true", help="only the most recently created project")
    ap.add_argument("--all", action="store_true", help="every project, newest first")
    ap.add_argument("--force", action="store_true", help="regenerate captions even if already set")
    ap.add_argument("--captions-only", action="store_true")
    ap.add_argument("--reburn-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.projects and not args.latest and not args.all:
        ap.error("specify project UUIDs, --latest, or --all")

    projects = await _resolve_projects(args)
    logger.info("=== backfill captions: %d project(s)%s ===", len(projects), " [DRY-RUN]" if args.dry_run else "")
    llm = get_llm_provider()
    provider = FFmpegStitchingProvider()
    for pid, title in projects:
        logger.info("=== PROJECT %s — %s ===", title, pid)
        if not args.reburn_only:
            await caption_scenes(pid, llm, args.dry_run, args.force)
        if not args.captions_only:
            await reburn_project(pid, provider, args.dry_run)
    logger.info("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
