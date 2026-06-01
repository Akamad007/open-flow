"""LTX-Video provider — wraps the existing ltx_generate.py script."""

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.video.base import VideoProvider, VideoResult, VideoSettings

logger = logging.getLogger(__name__)


# Hardcoded baseline appended to every LTX negative prompt. LTX hallucinates
# burned-in subtitles and watermarks when the prompt mentions narration, ads,
# or dialogue — this catches what the LLM-emitted negative misses.
_TEXT_ARTIFACT_NEGATIVE = (
    "text, subtitles, captions, lower thirds, title card, end card, "
    "watermark, logo, signature, words, letters, alphabet, English text, "
    "Devanagari, Cyrillic, gibberish text, on-screen text, typography, "
    "writing, brand mark, "
    # F-SINGLE-SUBJECT (iter6): with wider shots, LTX started painting a
    # second figure in the open environment. Lock it to one subject only.
    "lone subject only, no extras, two people, multiple people, second person, extra person, crowd, "
    "background figure, bystander, duplicate character, twin, "
    "cropped figure, cut-off feet, partial body, waist-up, "
    # F-FAR-CAMERA (iter7c): every video was framed too close to the subject.
    # Penalise close-up framings at the model level so even if the LLM
    # slips in a tight shot, LTX is biased toward wide.
    "close-up, extreme close-up, headshot, bust shot, beauty shot, "
    "face filling frame, shoulders-up, dutch close, talking head, "
    "macro lens, telephoto compression, narrow depth of field, "
    "medium close-up, MCU, head-to-knees crop, head-to-waist, waist-up, "
    "half-body, chest-up, tight framing, subject fills frame, "
    "subject dominates frame"
)

# F-FAR-CAMERA (iter7e): even stronger wide prefix after iter7d failed.
# iter7d (15 ft + small figure) still produced chest-up framing on the
# denim_jacket scene because close-action verbs ("looks up at camera",
# "holds gaze", "intimate") in the body pulled LTX toward tight framing.
# This pass: emphasize SUBJECT SIZE (~25% frame height), explicit "feet
# visible at bottom edge", and "extreme long shot" cinematic term.
_FAR_CAMERA_PREFIX = (
    "EXTREME LONG SHOT, establishing shot. The subject appears as a SMALL "
    "figure occupying only about one-quarter of the frame height, "
    "positioned in the lower-third of a 16:9 landscape frame. Vast "
    "environment dominates the upper two-thirds: sky, ceiling, walls, or "
    "distant architecture. Camera is 30 feet away, chest-height, wide-"
    "angle 24mm lens. Both feet of the subject are clearly above the "
    "bottom edge with floor visible. Head clearly below the top edge with "
    "headroom above. NO close-up, NO bust shot, NO chest-up, NO talking "
    "head, NO face-filling-frame. "
)

# F-FAR-CAMERA (iter7e): scrub tight-framing AND close-action triggers.
# iter7d only scrubbed shot-size words. iter7e adds verbs/phrases that
# implicitly request tight framing: "intimate", "looks at camera", "holds
# gaze", "gaze fills frame" — these trigger LTX's selfie/portrait bias.
_TIGHT_FRAMING_RE = re.compile(
    r"\b(?:extreme[- ]close[- ]ups?|close[- ]ups?|closeups?|head[- ]?shots?|"
    r"bust[- ]shots?|beauty[- ]shots?|face[- ]filling[- ]frame|shoulders?[- ]up|"
    r"head[- ]and[- ]shoulders?|talking[- ]heads?|macro[- ](?:lens|shots?)|"
    r"medium[- ]close[- ]ups?|MCU|medium[- ]shots?|tight[- ](?:framing|shots?|crops?)|"
    r"head[- ]to[- ]knees?|head[- ]to[- ]waist|waist[- ]up|half[- ]body|"
    r"chest[- ]up|intimate(?:[- ](?:framing|mood|shot|moment))?)\b",
    re.IGNORECASE,
)

# Camera-aware action verbs that LTX reads as "frame the face" — replace
# with neutral framing-agnostic phrasing.
_CAMERA_AWARE_RE = re.compile(
    r"\b(?:looks?[- ](?:up[- ])?(?:at|towards?|into)[- ](?:the[- ])?camera|"
    r"holds?[- ]gaze|gaze[- ](?:fills?|locks?|holds?)|"
    r"stares?[- ](?:into|at)[- ](?:the[- ])?camera|"
    r"makes?[- ]eye[- ]contact[- ]with[- ](?:the[- ])?camera)\b",
    re.IGNORECASE,
)


def _scrub_tight_framing(prompt: str) -> str:
    """Replace tight-framing and camera-aware terms with wide-shot language."""
    out = _TIGHT_FRAMING_RE.sub("wide shot full body", prompt)
    out = _CAMERA_AWARE_RE.sub("looks ahead", out)
    return out


def _wants_closeup(raw_prompt: str) -> bool:
    """Decide whether the scene actually wants a tight/close framing.
    Run BEFORE _scrub_tight_framing — the scrubber strips these cues."""
    return bool(_TIGHT_FRAMING_RE.search(raw_prompt or ""))


# Words that, when present in the LTX prompt, dramatically increase the chance
# of LTX hallucinating burned-in text. Stripped from the prompt before
# subprocess call. The narrative meaning is preserved in audio elsewhere.
# Words/phrases that, anywhere in the prompt, increase the chance of LTX
# hallucinating burned-in text/subtitles. We strip the entire sentence that
# contains them so the visual description stays coherent.
_TEXT_TRIGGER_TOKENS = (
    "voiceover", "voice-over", "voice over",
    "narration", "narrator", "narrated",
    "caption", "captions", "subtitle", "subtitles",
    "title card", "title-card", "end card", "end-card",
    "logo screen", "logo-screen",
    "on-screen text", "onscreen text", "on screen text",
    "tagline", "call-to-action", "call to action",
    "lower thirds", "lower-thirds",
)


def _sanitize_prompt_for_ltx(prompt: str) -> str:
    """Remove narration / dialogue / on-screen-text triggers that cause LTX
    to hallucinate gibberish English text overlays. Keeps the visual
    description intact by dropping whole sentences that contain triggers,
    and stripping all quoted dialogue regardless of context."""
    if not prompt:
        return prompt

    # 1. Drop everything in quotes — that's almost always dialogue LTX will
    #    try to render on screen as text.
    cleaned = re.sub(r'"[^"]*"', "", prompt)
    cleaned = re.sub(r"'[^']{3,}'", "", cleaned)

    # 2. Split into sentences, drop any that contain a text-trigger token.
    sentences = re.split(r'(?<=[.!?])\s+', cleaned)
    kept = []
    for s in sentences:
        s_low = s.lower()
        if any(tok in s_low for tok in _TEXT_TRIGGER_TOKENS):
            continue
        kept.append(s)
    cleaned = " ".join(kept)

    # 3. Collapse whitespace, fix orphan punctuation left behind.
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\.\s*\.", ".", cleaned)
    cleaned = re.sub(r":\s*\.", ".", cleaned)
    return cleaned.strip()


def _augment_negative_for_ltx(negative: str) -> str:
    """Append the hardcoded text-artifact baseline to whatever the LLM emitted."""
    base = (negative or "").strip().rstrip(",")
    return f"{base}, {_TEXT_ARTIFACT_NEGATIVE}" if base else _TEXT_ARTIFACT_NEGATIVE


_RESTORE_SCRIPT = (
    Path(__file__).parent.parent.parent.parent.parent / "scripts" / "restore_faces.py"
)


async def _restore_faces_in_place(mp4_path: Path, env: dict) -> None:
    """Run GFPGAN restoration on the rendered mp4, overwriting in place.
    Restoration failure is non-fatal — we keep the unrestored video."""
    if not _RESTORE_SCRIPT.exists():
        logger.warning("Face restore script not found at %s — skipping", _RESTORE_SCRIPT)
        return
    tmp = mp4_path.with_suffix(".restored.mp4")
    cmd = [
        settings.gpu_python_path, str(_RESTORE_SCRIPT),
        str(mp4_path), str(tmp),
        "--device", "cuda", "--upscale", "1",
    ]
    logger.info("Restoring faces: %s", mp4_path.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0 and tmp.exists():
            tmp.replace(mp4_path)
            logger.info("✓ Face restoration applied")
        else:
            err = (stderr.decode()[-400:] if stderr else "?").strip()
            logger.warning("Face restoration failed (rc=%s): %s — keeping raw video",
                           proc.returncode, err)
            if tmp.exists():
                tmp.unlink()
    except Exception as e:
        logger.warning("Face restoration error: %s — keeping raw video", e)


class LTXVideoProvider(VideoProvider):
    """
    Generates video using LTX-Video via the existing ltx_generate.py script.
    Runs the script as a subprocess to avoid loading the model into the web server process.
    """

    def __init__(self):
        self._script_path = Path(__file__).parent.parent.parent.parent.parent / "ltx_generate.py"
        self._active_jobs: dict[str, asyncio.subprocess.Process] = {}

    async def generate_video(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        video_settings: Optional[VideoSettings] = None,
        condition_image_path: Optional[str] = None,
        character_image_path: Optional[str] = None,
        background_image_path: Optional[str] = None,
        scene_action_images: Optional[list[str]] = None,
        lora_plan_json: Optional[str] = None,
    ) -> VideoResult:
        vs = video_settings or VideoSettings(
            height=settings.ltx_height,
            width=settings.ltx_width,
            num_frames=settings.ltx_num_frames,
            num_inference_steps=settings.ltx_inference_steps,
            guidance_scale=settings.ltx_guidance_scale,
            fps=settings.ltx_fps,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        wants_closeup = _wants_closeup(prompt)
        if wants_closeup:
            clean_prompt = _sanitize_prompt_for_ltx(prompt)  # keep close-up framing intact
            logger.info("Close-up shot detected → snorricam_scale=1.0, skipping far-camera prefix")
        else:
            clean_prompt = _FAR_CAMERA_PREFIX + _scrub_tight_framing(_sanitize_prompt_for_ltx(prompt))
        clean_negative = _augment_negative_for_ltx(negative_prompt)
        if clean_prompt != prompt:
            logger.info("Stripped narration/dialogue triggers from prompt (was %d chars, now %d)",
                        len(prompt), len(clean_prompt))

        cmd = [
            settings.gpu_python_path, str(self._script_path),
            "--prompt", clean_prompt,
            "--negative-prompt", clean_negative,
            # CRITICAL: skip ltx_generate.py's QUALITY_SUFFIX which appends
            # "locked-off camera, tripod stable, static shot, character fully
            # visible" to every prompt. That suffix was forcing every video
            # to be a dead-still tripod shot — the root cause of the
            # "everything is static" complaints. Backend prompts are already
            # cinematically directed by the visual_director.
            "--no-enhance",
            "--output", str(output_path),
            "--model", settings.ltx_model_id,
            "--model-file", settings.ltx_model_file,
            "--device", settings.ltx_device,
            "--height", str(vs.height),
            "--width", str(vs.width),
            "--num-frames", str(vs.num_frames),
            "--fps", str(vs.fps),
            # Disable IC-LoRA adapter stack. Snorricam at scale=1.0 (script
            # default) is a face-mounted-rig effect that pulls every shot
            # tight to the subject — overriding even the EXTREME LONG SHOT
            # prefix. Pose+depth LoRAs were also failing shape-mismatch
            # against this base, so they were never applied cleanly anyway.
            "--pose-scale", "0",
            "--depth-scale", "0",
            "--snorricam-scale", "1.0" if wants_closeup else "0",
            "--num-inference-steps", str(vs.num_inference_steps),
            "--guidance-scale", str(vs.guidance_scale),
            "--seed", str(vs.seed),
        ]

        # ── F-TEXT-ONLY-LTX (iter6) ─────────────────────────────────────────
        # All static-image LTX conditions removed: bg/portrait/stills are
        # no longer pinned as frame conditions. LTX runs pure text-to-video
        # plus previous-scene last-frame for continuity.
        # We DO still pass --background-image to ltx_generate.py because
        # that arg is what selects LTXConditionPipeline (vs the broken-on-
        # this-checkpoint LTXPipeline). ltx_generate.py is patched in the
        # same iter to load the bg arg but skip the conditions.append.
        has_condition_images = False
        if background_image_path and Path(background_image_path).exists():
            cmd += ["--background-image", background_image_path]
            has_condition_images = True
            logger.info("Pass-through bg for pipeline-class selection: %s "
                        "(NOT used as frame condition)", background_image_path)
        # F-CANON-PORTRAIT-REVERTED (iter7b): user reported every video with
        # a frame-condition picture inserted looks horrible — same failure
        # mode as F-NO-STILL-PINS / F-TEXT-ONLY-LTX. Keep the portrait file
        # on disk (canonical_portrait stage still runs — useful for future
        # face-restoration / LoRA dataset) but DO NOT pass it to LTX as a
        # frame condition.
        if character_image_path and Path(character_image_path).exists():
            logger.info("Skipping portrait condition (F-CANON-PORTRAIT-REVERTED): %s",
                        character_image_path)
        if scene_action_images:
            logger.info("Skipping %d action stills (F-NO-STILL-PINS)",
                        len(scene_action_images))

        # ── Last frame from previous scene (always pass for continuity) ────────
        if condition_image_path and Path(condition_image_path).exists():
            cmd += ["--condition-image", condition_image_path]
            logger.info("Conditioning: last-frame=%s", condition_image_path)


        logger.info("Running LTX-Video: %s", " ".join(cmd[:5]) + "...")

        env = os.environ.copy()
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
        # With celery --concurrency=2 we run two scene renders in parallel,
        # one per GPU. Pin via the worker's prefork identity (worker 1→cuda:0,
        # worker 2→cuda:1). Falls back to cuda:0 outside a celery worker.
        import multiprocessing as _mp
        ident = getattr(_mp.current_process(), "_identity", ()) or ()
        gpu_id = ((ident[0] - 1) % 2) if ident else 0
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        logger.info("LTX pinned to cuda:%d (worker identity=%s)", gpu_id, ident)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            job_id = str(uuid.uuid4())
            self._active_jobs[job_id] = proc

            stdout, stderr = await proc.communicate()

            del self._active_jobs[job_id]

            if proc.returncode != 0:
                error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
                logger.error("LTX-Video failed: %s", error_msg)
                return VideoResult(success=False, error=error_msg)

            if not output_path.exists():
                return VideoResult(success=False, error="Output file not created")

            if settings.ltx_face_restore:
                await _restore_faces_in_place(output_path, env)

            duration = vs.num_frames / vs.fps
            return VideoResult(
                success=True,
                file_path=str(output_path),
                duration_seconds=duration,
                metadata={
                    "provider": "ltx",
                    "model": settings.ltx_model_id,
                    "model_file": settings.ltx_model_file,
                    "device": settings.ltx_device,
                    "height": vs.height,
                    "width": vs.width,
                    "num_frames": vs.num_frames,
                    "fps": vs.fps,
                },
            )

        except Exception as e:
            logger.exception("LTX-Video generation error")
            return VideoResult(success=False, error=str(e))

    async def get_status(self, job_id: str) -> str:
        if job_id in self._active_jobs:
            proc = self._active_jobs[job_id]
            if proc.returncode is None:
                return "running"
            return "complete" if proc.returncode == 0 else "failed"
        return "unknown"

    async def cancel(self, job_id: str) -> None:
        if job_id in self._active_jobs:
            self._active_jobs[job_id].terminate()
