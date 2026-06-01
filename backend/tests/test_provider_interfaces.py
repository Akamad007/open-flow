"""Sanity checks on provider dataclass interfaces (Settings / Result / Clip)."""

from __future__ import annotations

from pathlib import Path


class TestVideoProviderInterface:
    def test_video_settings_defaults(self):
        from app.providers.video.base import VideoSettings
        vs = VideoSettings()
        assert vs.height == 480
        assert vs.width == 704
        assert vs.num_frames == 49
        assert vs.fps == 16

    def test_video_result_success(self):
        from app.providers.video.base import VideoResult
        r = VideoResult(success=True, file_path="/tmp/test.mp4", duration_seconds=4.0)
        assert r.success
        assert r.duration_seconds == 4.0

    def test_video_result_failure(self):
        from app.providers.video.base import VideoResult
        r = VideoResult(success=False, error="GPU OOM")
        assert not r.success
        assert r.error == "GPU OOM"


class TestAudioProviderInterface:
    def test_audio_settings_defaults(self):
        from app.providers.audio.base import AudioSettings
        a = AudioSettings()
        assert a.sample_rate == 44100
        assert a.channels == 2

    def test_audio_result_structure(self):
        from app.providers.audio.base import AudioResult
        r = AudioResult(success=True, file_path="/tmp/audio.wav", duration_seconds=16.0)
        assert r.success


class TestStitchingInterface:
    def test_stitch_settings_defaults(self):
        from app.providers.stitching.base import StitchSettings
        ss = StitchSettings()
        assert ss.video_codec == "libx264"
        assert ss.crf == 18
        assert ss.preset == "medium"

    def test_scene_clip_structure(self):
        from app.providers.stitching.base import SceneClip
        clip = SceneClip(
            scene_id="abc", file_path=Path("/tmp/scene.mp4"),
            order_index=0, target_duration=4.0,
        )
        assert clip.target_duration == 4.0
        assert clip.actual_duration is None

    def test_stitch_result_structure(self):
        from app.providers.stitching.base import StitchResult
        r = StitchResult(success=True, file_path="/tmp/final.mp4", total_duration=16.0)
        assert r.success
        assert r.total_duration == 16.0


class TestPipelineFactories:
    """Provider factories return the right stub class when configured for stubs."""

    def test_get_llm_provider_stub(self):
        from app.config import settings
        from app.orchestration.pipeline import get_llm_provider
        from app.providers.llm.stub_provider import StubLLMProvider

        original = settings.llm_provider
        try:
            settings.llm_provider = "stub"
            assert isinstance(get_llm_provider(), StubLLMProvider)
        finally:
            settings.llm_provider = original

    def test_get_video_provider_stub(self):
        from app.config import settings
        from app.orchestration.pipeline import get_video_provider
        from app.providers.video.stub_provider import StubVideoProvider

        original = settings.video_provider
        try:
            settings.video_provider = "stub"
            assert isinstance(get_video_provider(), StubVideoProvider)
        finally:
            settings.video_provider = original

    def test_get_audio_provider_stub(self):
        from app.config import settings
        from app.orchestration.pipeline import get_audio_provider
        from app.providers.audio.stub_provider import StubAudioProvider

        original = settings.audio_provider
        try:
            settings.audio_provider = "stub"
            assert isinstance(get_audio_provider(), StubAudioProvider)
        finally:
            settings.audio_provider = original
