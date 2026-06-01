"""Stub Video / Audio providers shell out to ffmpeg to produce placeholder media."""

from __future__ import annotations

import pytest


class TestStubVideoProvider:
    async def test_generates_placeholder(self, tmp_path):
        from app.providers.video.base import VideoSettings
        from app.providers.video.stub_provider import StubVideoProvider

        provider = StubVideoProvider()
        output = tmp_path / "test_video.mp4"

        result = await provider.generate_video(
            prompt="A sunset over the ocean",
            negative_prompt="ugly",
            output_path=output,
            video_settings=VideoSettings(num_frames=12, fps=24),
        )

        assert result.success, f"StubVideo failed: {result.error}"
        assert output.exists()
        assert result.duration_seconds == 0.5  # 12/24

    async def test_status_returns_complete(self):
        from app.providers.video.stub_provider import StubVideoProvider
        provider = StubVideoProvider()
        assert await provider.get_status("any-id") == "complete"


class TestStubAudioProvider:
    async def test_generates_silence(self, tmp_path):
        from app.providers.audio.stub_provider import StubAudioProvider

        provider = StubAudioProvider()
        output = tmp_path / "test_audio.wav"

        result = await provider.generate_full_story_audio(
            narration_text="Hello world",
            output_path=output,
            target_duration=5.0,
        )

        assert result.success, f"StubAudio failed: {result.error}"
        assert output.exists()
        assert result.duration_seconds == 5.0
