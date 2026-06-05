"""Unit tests for caption timeline math (pure, no ffmpeg / no network)."""

from app.providers.stitching.ffmpeg_provider import FFmpegStitchingProvider as P


def test_srt_timestamp_format():
    assert P._srt_ts(0) == "00:00:00,000"
    assert P._srt_ts(4.85) == "00:00:04,850"
    assert P._srt_ts(64.85) == "00:01:04,850"
    assert P._srt_ts(3661.5) == "01:01:01,500"
    assert P._srt_ts(-1) == "00:00:00,000"  # clamps negative


def test_caption_windows_no_xfade():
    # Plain concat: windows tile the timeline back-to-back.
    w = P._caption_windows([5.0, 5.0, 5.0], apply_xfade=False, xfade_d=0.3)
    assert w == [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0)]


def test_caption_windows_with_xfade():
    # Each transition overlaps by xfade_d, so starts shift earlier and the
    # final end == total stream length (sum - (n-1)*xd).
    w = P._caption_windows([5.0, 5.0, 5.0], apply_xfade=True, xfade_d=0.3)
    starts = [round(s, 2) for s, _ in w]
    ends = [round(e, 2) for _, e in w]
    assert starts == [0.0, 4.7, 9.4]
    assert ends == [4.7, 9.4, 14.4]  # 15 - 2*0.3


def test_caption_windows_single_clip():
    assert P._caption_windows([5.04], apply_xfade=True, xfade_d=0.3) == [(0.0, 5.04)]
