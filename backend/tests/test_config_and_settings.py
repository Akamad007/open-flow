"""Config / settings + secrets-client cache."""

from __future__ import annotations

from unittest.mock import patch


class TestConfig:
    def test_settings_load(self):
        from app.config import settings
        assert settings.llm_provider in ("openai", "stub")
        assert settings.video_provider in ("ltx", "stub")
        assert settings.audio_provider in ("chatterbox", "stub")
        assert settings.llm_model
        assert settings.llm_api_base.startswith("http")

    def test_storage_dir_creation(self, tmp_path):
        from app.config import Settings
        s = Settings(storage_root=tmp_path / "test_storage")
        s.ensure_storage_dirs()
        assert (tmp_path / "test_storage" / "videos").is_dir()
        assert (tmp_path / "test_storage" / "audio").is_dir()
        assert (tmp_path / "test_storage" / "renders").is_dir()
        assert (tmp_path / "test_storage" / "temp").is_dir()

    def test_secrets_manager_settings_exist(self):
        from app.config import settings
        assert hasattr(settings, "secrets_manager_url")
        assert hasattr(settings, "secrets_manager_token")

    def test_chatterbox_settings_exist(self):
        from app.config import settings
        assert hasattr(settings, "chatterbox_reference_audio")
        assert hasattr(settings, "chatterbox_max_chunk_chars")
        assert settings.chatterbox_max_chunk_chars > 0


class TestSecretsClient:
    def test_cache_operations(self):
        from app.utils.secrets_client import _cache, clear_cache
        _cache["TEST_KEY"] = "test_value"
        assert _cache.get("TEST_KEY") == "test_value"
        clear_cache()
        assert _cache.get("TEST_KEY") is None

    def test_sync_fetch_no_token(self):
        from app.utils.secrets_client import clear_cache, get_secret_sync
        clear_cache()
        with patch("app.utils.secrets_client.settings") as mock_settings:
            mock_settings.secrets_manager_token = ""
            mock_settings.secrets_manager_url = "http://localhost:8010"
            assert get_secret_sync("SOME_KEY", use_cache=False) is None

    def test_sync_fetch_with_cache(self):
        from app.utils.secrets_client import _cache, get_secret_sync
        _cache["CACHED_KEY"] = "cached_value"
        try:
            assert get_secret_sync("CACHED_KEY", use_cache=True) == "cached_value"
        finally:
            del _cache["CACHED_KEY"]
