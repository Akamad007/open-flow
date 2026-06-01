#!/usr/bin/env python3
"""
Standalone Chatterbox TTS generation script.

Runs as a subprocess so the model is NOT loaded in the web server.
The Celery worker calls this script for audio generation.

Usage:
    python chatterbox_generate.py \
        --text "Full narration text here..." \
        --reference storage/audio/narrator_reference.wav \
        --output storage/audio/project_id/full_story.wav \
        --max-duration 60.0
"""

import argparse
import json
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Chatterbox TTS Generator")
    parser.add_argument("--text", required=True, help="Narration text to speak")
    parser.add_argument("--reference", required=True, help="Path to reference voice WAV (~10s)")
    parser.add_argument("--output", required=True, help="Output WAV file path")
    parser.add_argument("--device", default=None, help="Device: cuda or cpu (auto-detect if omitted)")
    parser.add_argument("--max-chunk-chars", type=int, default=500,
                        help="Max characters per chunk (Chatterbox works best with shorter text)")
    parser.add_argument("--max-duration", type=float, default=None,
                        help="Target duration in seconds — audio will be time-stretched via ffmpeg atempo to fit.")
    args = parser.parse_args()

    import torch
    import torchaudio as ta

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    print(f"[chatterbox] Device: {device}")
    print(f"[chatterbox] Reference: {args.reference}")
    print(f"[chatterbox] Text length: {len(args.text)} chars")
    print(f"[chatterbox] Output: {args.output}")
    if args.max_duration:
        print(f"[chatterbox] Target duration: {args.max_duration:.1f}s")

    # ── Patch perth watermarker BEFORE importing chatterbox ──────────────────
    # The C extension (_perth) doesn't load on this system, leaving
    # PerthImplicitWatermarker=None which crashes ChatterboxTurboTTS.__init__.
    # DummyWatermarker is perth's own no-op fallback for this exact case.
    import perth
    if perth.PerthImplicitWatermarker is None:
        print("[chatterbox] WARNING: perth C extension unavailable — using DummyWatermarker (no audio watermarking)")
        perth.PerthImplicitWatermarker = perth.DummyWatermarker

    t0 = time.time()
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    model = ChatterboxTurboTTS.from_pretrained(device=device)
    print(f"[chatterbox] Model loaded in {time.time() - t0:.1f}s")

    # ── Force float32 throughout model ───────────────────────────────────────
    # Root cause: librosa.resample() returns numpy float64, which
    # torch.from_numpy() converts to float64. This crashes the voice_encoder
    # LSTM which requires float32. Patch librosa.resample to always cast output.
    try:
        import librosa as _librosa
        import numpy as _np
        _orig_resample = _librosa.resample
        def _resample_f32(*a, **kw):
            out = _orig_resample(*a, **kw)
            return out.astype(_np.float32) if out.dtype != _np.float32 else out
        _librosa.resample = _resample_f32
        print("[chatterbox] Patched librosa.resample → float32 output")
    except Exception as e:
        print(f"[chatterbox] librosa.resample patch skipped: {e}")

    # Belt-and-suspenders: patch voice_encoder.embeds_from_wavs to cast numpy array
    try:
        import numpy as _np
        _orig_embeds = model.ve.embeds_from_wavs
        def _embeds_f32(wavs, **kwargs):
            wavs = [w.astype(_np.float32) if hasattr(w, 'astype') and w.dtype != _np.float32 else w for w in wavs]
            return _orig_embeds(wavs, **kwargs)
        model.ve.embeds_from_wavs = _embeds_f32
        print("[chatterbox] Patched voice_encoder.embeds_from_wavs → float32 cast")
    except Exception as e:
        print(f"[chatterbox] voice_encoder patch skipped: {e}")

    # Belt-and-suspenders: also patch log_mel_spectrogram in s3tokenizer
    try:
        s3tok = model.s3gen.tokenizer
        _orig_log_mel = s3tok.log_mel_spectrogram
        def _log_mel_f32(audio, padding=0, _orig=_orig_log_mel):
            if torch.is_tensor(audio):
                audio = audio.float()
            return _orig(audio, padding)
        s3tok.log_mel_spectrogram = _log_mel_f32
        print("[chatterbox] Patched s3tokenizer.log_mel_spectrogram → float32 cast")
    except Exception as e:
        print(f"[chatterbox] log_mel patch skipped: {e}")

    # Split long text into chunks for better quality
    chunks = split_text(args.text, max_chars=args.max_chunk_chars)
    print(f"[chatterbox] Generating {len(chunks)} chunks...")

    all_wavs = []
    for i, chunk in enumerate(chunks):
        print(f"[chatterbox]   Chunk {i+1}/{len(chunks)}: {len(chunk)} chars")
        t1 = time.time()
        wav = model.generate(chunk, audio_prompt_path=args.reference)
        print(f"[chatterbox]   Generated in {time.time() - t1:.1f}s")
        all_wavs.append(wav)

    final_wav = torch.cat(all_wavs, dim=-1) if len(all_wavs) > 1 else all_wavs[0]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    # Ensure float32 before saving
    final_wav = final_wav.float()
    # Use soundfile directly — torchaudio 2.11+ uses torchcodec backend which
    # requires a separate install. soundfile works universally for WAV.
    try:
        import soundfile as sf
        import numpy as np
        wav_np = final_wav.squeeze().numpy()  # (samples,) or (channels, samples)
        if wav_np.ndim == 2:
            wav_np = wav_np.T  # soundfile expects (samples, channels)
        sf.write(args.output, wav_np, model.sr)
    except ImportError:
        # fallback: try torchaudio with explicit soundfile backend
        ta.set_audio_backend("soundfile")
        ta.save(args.output, final_wav, model.sr)

    raw_duration = final_wav.shape[-1] / model.sr
    print(f"[chatterbox] Raw TTS duration: {raw_duration:.1f}s")

    # No time-stretching — natural-pace audio always sounds better than
    # atempo'd narration. If --max-duration is set it's only used as a soft
    # hint at planning time; the stitching stage matches the video to the
    # audio (or vice-versa) without modifying the audio waveform.
    duration = raw_duration

    print(f"[chatterbox] Saved {args.output} ({duration:.1f}s)")
    print(f"[chatterbox] Total time: {time.time() - t0:.1f}s")

    print(json.dumps({
        "duration": duration,
        "sample_rate": model.sr,
        "chunks": len(chunks),
        "output": args.output,
    }))


def build_atempo_filters(ratio: float) -> str:
    """
    Build an ffmpeg atempo filter chain for the given speed ratio.
    atempo only accepts 0.5–2.0 per stage; chain multiple for extreme ratios.

    ratio > 1 → speed up (audio longer than target)
    ratio < 1 → slow down (audio shorter than target)
    """
    filters = []
    r = ratio
    while r > 2.0:
        filters.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        filters.append("atempo=0.5")
        r /= 0.5
    filters.append(f"atempo={r:.6f}")
    return ",".join(filters)


def split_text(text: str, max_chars: int = 500) -> list[str]:
    """Split text into chunks at sentence boundaries."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


if __name__ == "__main__":
    main()
