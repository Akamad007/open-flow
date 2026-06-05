"""FFmpeg-based stitching provider — concatenates scene clips and overlays audio."""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.stitching.base import (
    SceneClip,
    StitchingProvider,
    StitchResult,
    StitchSettings,
)

logger = logging.getLogger(__name__)


class FFmpegStitchingProvider(StitchingProvider):
    """
    Stitches scene video clips into one continuous video with the full-story audio.

    Pipeline:
    1. Pad/trim each scene clip to its target duration
    2. Concatenate all clips using FFmpeg concat demuxer
    3. Overlay the continuous audio
    4. Export final MP4
    """

    async def stitch(
        self,
        scene_clips: list[SceneClip],
        audio_path: Optional[Path],
        output_path: Path,
        stitch_settings: Optional[StitchSettings] = None,
    ) -> StitchResult:
        ss = stitch_settings or StitchSettings()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not scene_clips:
            return StitchResult(success=False, error="No scene clips to stitch")

        # Sort clips by order_index
        sorted_clips = sorted(scene_clips, key=lambda c: c.order_index)

        try:
            # Step 1: Normalize each clip to target duration
            normalized_paths = []
            for clip in sorted_clips:
                norm_path = await self._normalize_clip(clip, ss)
                normalized_paths.append(norm_path)

            # Step 2: Concatenate clips (with optional xfade transitions).
            # When skipping audio, concat straight into the final output —
            # no overlay step needed.
            if audio_path is None:
                concat_path = output_path
            else:
                concat_path = output_path.parent / f"{output_path.stem}_concat.mp4"
            # Use ACTUAL probed durations (set by _normalize_clip) so the
            # xfade offset math matches the file on disk — not the stale
            # planner target. Falls back to target_duration only if probing
            # somehow returned 0.
            durations = [
                c.actual_duration if (c.actual_duration and c.actual_duration > 0) else c.target_duration
                for c in sorted_clips
            ]
            if ss.apply_crossfades and len(normalized_paths) > 1:
                await self._concatenate_with_xfade(normalized_paths, durations, concat_path, ss)
            else:
                await self._concatenate_clips(normalized_paths, concat_path, ss)

            # Step 3: Overlay audio (skipped for silent background renders).
            if audio_path is not None:
                await self._overlay_audio(concat_path, audio_path, output_path, ss)

            # Cleanup temp files
            for p in normalized_paths:
                if p.exists() and "normalized_" in p.name:
                    p.unlink()
            if audio_path is not None and concat_path.exists() and concat_path != output_path:
                concat_path.unlink()

            # Step 4: Burn in per-scene captions (no-op if none are set).
            await self._burn_captions(output_path, sorted_clips, durations, ss)

            # Get final duration
            duration = await self._get_duration(output_path)

            return StitchResult(
                success=True,
                file_path=str(output_path),
                total_duration=duration,
                metadata={
                    "provider": "ffmpeg",
                    "num_clips": len(sorted_clips),
                    "codec": ss.video_codec,
                    "captions": any((c.caption or "").strip() for c in sorted_clips),
                },
            )

        except Exception as e:
            logger.exception("Stitching failed")
            return StitchResult(success=False, error=str(e))

    async def _normalize_clip(self, clip: SceneClip, ss: StitchSettings) -> Path:
        """Pad a clip to its target duration if it's too short. NEVER trim
        when the rendered clip is longer than the planner's target — the
        video provider's output is the source of truth (e.g. Wan22 always
        renders 5.04s @ 121 frames / 24fps regardless of scene.duration_seconds).
        Trimming threw away ~2s of every Wan22 clip; the final video came out
        ~45% shorter than expected."""
        clip_path = clip.file_path
        target = clip.target_duration

        actual = await self._get_duration(clip_path)
        clip.actual_duration = actual

        # Use actual whenever it's >= target. Only pad if rendered short.
        if actual >= target - 0.1:
            return clip_path

        norm_path = clip_path.parent / f"normalized_{clip_path.name}"
        pad_duration = target - actual
        cmd = [
            settings.ffmpeg_path, "-y",
            "-i", str(clip_path),
            "-vf", f"tpad=stop_mode=clone:stop_duration={pad_duration}",
            "-c:v", ss.video_codec,
            "-preset", "ultrafast",
            "-an",
            str(norm_path),
        ]
        await self._run_ffmpeg(cmd)
        return norm_path

    async def _concatenate_clips(
        self, clip_paths: list[Path], output: Path, ss: StitchSettings
    ) -> None:
        """Concatenate clips using FFmpeg concat demuxer."""
        # Create concat file list
        concat_file = output.parent / "concat_list.txt"
        with open(concat_file, "w") as f:
            for path in clip_paths:
                f.write(f"file '{path.resolve()}'\n")

        cmd = [
            settings.ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c:v", ss.video_codec,
            "-crf", str(ss.crf),
            "-preset", ss.preset,
            "-pix_fmt", "yuv420p",
            "-an",
            str(output),
        ]

        try:
            await self._run_ffmpeg(cmd)
        finally:
            if concat_file.exists():
                try:
                    concat_file.unlink()
                except OSError as exc:
                    logger.warning("Failed to cleanup concat file %s: %s", concat_file, exc)

    async def _concatenate_with_xfade(
        self, clip_paths: list[Path], durations: list[float], output: Path, ss: StitchSettings
    ) -> None:
        """Chain clips with the `xfade` filter. Each transition overlaps by
        ss.crossfade_duration seconds; total video shrinks by (N-1)*xfade_d."""
        xd = ss.crossfade_duration
        inputs: list[str] = []
        for p in clip_paths:
            inputs += ["-i", str(p)]

        # xfade requires both inputs to share width/height. Different providers
        # / post-processors (face restore, ESRGAN upscale) yield mixed sizes,
        # so force every clip to the first clip's dimensions before chaining.
        target_w, target_h = await self._get_dimensions(clip_paths[0])
        logger.info("xfade target dimensions: %dx%d (from %s)",
                    target_w, target_h, clip_paths[0].name)
        pre = [
            f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=disable,"
            f"format=yuv420p,fps=16,setpts=PTS-STARTPTS[v{i}]"
            for i in range(len(clip_paths))
        ]
        chain: list[str] = []
        last = "v0"
        stream_len = durations[0]
        for k in range(1, len(clip_paths)):
            offset = max(0.0, stream_len - xd)
            label = f"x{k}"
            chain.append(
                f"[{last}][v{k}]xfade=transition=fade:duration={xd:.3f}:offset={offset:.3f}[{label}]"
            )
            last = label
            stream_len += durations[k] - xd

        filter_complex = ";".join(pre + chain)
        cmd = [settings.ffmpeg_path, "-y", *inputs,
               "-filter_complex", filter_complex,
               "-map", f"[{last}]",
               "-c:v", ss.video_codec,
               "-crf", str(ss.crf),
               "-preset", ss.preset,
               "-pix_fmt", "yuv420p",
               "-an",
               str(output)]
        logger.info("FFmpeg xfade chain: %d clips, %.2fs each → stream_len ≈ %.2fs",
                    len(clip_paths), durations[0], stream_len)
        await self._run_ffmpeg(cmd)

    @staticmethod
    def _srt_ts(t: float) -> str:
        """Format seconds as an SRT timestamp HH:MM:SS,mmm."""
        t = max(0.0, t)
        h, rem = divmod(int(t), 3600)
        m, s = divmod(rem, 60)
        ms = int(round((t - int(t)) * 1000))
        if ms >= 1000:
            ms, s = 0, s + 1
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _caption_windows(
        durations: list[float], apply_xfade: bool, xfade_d: float
    ) -> list[tuple[float, float]]:
        """Per-scene [start, end] in the FINAL timeline, mirroring the xfade
        offset math in `_concatenate_with_xfade` so captions line up with the
        scene actually on screen."""
        xd = xfade_d if (apply_xfade and len(durations) > 1) else 0.0
        offsets, sl = [], 0.0
        for k, d in enumerate(durations):
            if k == 0:
                offsets.append(0.0); sl = d
            else:
                offsets.append(sl - xd); sl += d - xd
        return [
            (offsets[k], offsets[k + 1] if k + 1 < len(durations) else sl)
            for k in range(len(durations))
        ]

    async def _burn_captions(
        self, output_path: Path, sorted_clips: list[SceneClip],
        durations: list[float], ss: StitchSettings,
    ) -> None:
        """Burn per-scene captions onto the finished video via an SRT + the
        libass `subtitles` filter. No-op when no clip carries a caption."""
        captions = [(c.caption or "").strip() for c in sorted_clips]
        if not any(captions):
            return
        windows = self._caption_windows(durations, ss.apply_crossfades, ss.crossfade_duration)
        cues, idx = [], 1
        for (start, end), text in zip(windows, captions):
            if not text:
                continue
            s = start + 0.15
            e = max(s + 0.6, end - 0.15)
            cues.append(f"{idx}\n{self._srt_ts(s)} --> {self._srt_ts(e)}\n{text}\n")
            idx += 1
        srt = output_path.parent / f"{output_path.stem}_captions.srt"
        srt.write_text("\n".join(cues), encoding="utf-8")
        tmp = output_path.parent / f"{output_path.stem}_capped.mp4"
        style = ("FontName=DejaVu Sans,FontSize=16,PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
                 "Alignment=2,MarginV=28")
        vf = f"subtitles='{srt}':force_style='{style}'"
        cmd = [
            settings.ffmpeg_path, "-y", "-i", str(output_path),
            "-vf", vf, "-c:v", ss.video_codec, "-crf", str(ss.crf),
            "-preset", ss.preset, "-pix_fmt", "yuv420p", "-c:a", "copy",
            str(tmp),
        ]
        try:
            await self._run_ffmpeg(cmd)
            os.replace(tmp, output_path)
            logger.info("Burned %d captions into %s", idx - 1, output_path.name)
        finally:
            for p in (srt, tmp):
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    async def _overlay_audio(
        self, video_path: Path, audio_path: Path, output: Path, ss: StitchSettings
    ) -> None:
        """Overlay the continuous audio onto the concatenated video.

        Video is source-of-truth: output = video duration. When the audio is
        shorter (natural-pace narration on a longer video), pad the audio with
        silence to the video length so the tail plays out instead of clipping
        the video. Never use -shortest here — it would chop the video to the
        audio length, which is the bug we just removed."""
        video_duration = await self._get_duration(video_path)

        cmd = [
            settings.ffmpeg_path, "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex", f"[1:a]apad=whole_dur={video_duration:.3f}[aout]",
            "-c:v", "copy",
            "-c:a", ss.audio_codec,
            "-b:a", "192k",
            "-t", f"{video_duration:.3f}",
            "-map", "0:v:0",
            "-map", "[aout]",
            str(output),
        ]

        await self._run_ffmpeg(cmd)

    async def _get_dimensions(self, file_path: Path) -> tuple[int, int]:
        """Return (width, height) of the first video stream via ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-print_format", "json", str(file_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        try:
            data = json.loads(stdout.decode())
            s = data["streams"][0]
            return int(s["width"]), int(s["height"])
        except (json.JSONDecodeError, KeyError, IndexError, ValueError):
            return 832, 480  # safe Wan22 default

    async def _get_duration(self, file_path: Path) -> float:
        """Get duration of a media file using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(file_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return 0.0

        try:
            data = json.loads(stdout.decode())
            return float(data.get("format", {}).get("duration", 0))
        except (json.JSONDecodeError, ValueError):
            return 0.0

    async def _run_ffmpeg(self, cmd: list[str]) -> None:
        """Run an FFmpeg command and raise on failure."""
        logger.debug("FFmpeg: %s", " ".join(cmd[:6]) + "...")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error = stderr.decode()[-500:]
            raise RuntimeError(f"FFmpeg failed (rc={proc.returncode}): {error}")
