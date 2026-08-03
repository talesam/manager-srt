"""Tests for utils/config_manager.py — persistent JSON config."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usr" / "share"))

from jellyfix.utils.config_manager import ConfigManager
from jellyfix.utils.config import Config


@pytest.fixture
def config_manager(monkeypatch, tmp_path):
    """ConfigManager rooted in tmp_path instead of $HOME."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return ConfigManager()


class TestBasicLoadSave:
    def test_load_returns_empty_when_file_missing(self, config_manager):
        assert config_manager.load() == {}

    def test_save_roundtrip(self, config_manager):
        config_manager.save({"foo": "bar", "n": 42})
        loaded = config_manager.load()
        assert loaded == {"foo": "bar", "n": 42}

    def test_get_default_when_missing(self, config_manager):
        assert config_manager.get("missing", default="fallback") == "fallback"

    def test_set_then_get(self, config_manager):
        config_manager.set("answer", 42)
        assert config_manager.get("answer") == 42

    def test_remove(self, config_manager):
        config_manager.set("k", "v")
        config_manager.remove("k")
        assert config_manager.get("k") is None

    def test_remove_missing_key_is_safe(self, config_manager):
        config_manager.remove("not-there")  # should not raise


class TestApiKeys:
    def test_tmdb_api_key_roundtrip(self, config_manager):
        config_manager.set_tmdb_api_key("abc123")
        assert config_manager.get_tmdb_api_key() == "abc123"
        config_manager.remove_tmdb_api_key()
        assert config_manager.get_tmdb_api_key() is None

    def test_tvdb_api_key_roundtrip(self, config_manager):
        config_manager.set_tvdb_api_key("xyz")
        assert config_manager.get_tvdb_api_key() == "xyz"

    def test_opensubtitles_accounts_append_and_update(self, config_manager):
        config_manager.set_opensubtitles_credentials("first", "one")
        config_manager.set_opensubtitles_credentials("second", "two")
        config_manager.set_opensubtitles_credentials("FIRST", "updated")

        assert config_manager.get_opensubtitles_accounts() == [
            {"username": "FIRST", "password": "updated"},
            {"username": "second", "password": "two"},
        ]
        assert config_manager.get_opensubtitles_credentials() == ("FIRST", "updated")

    def test_opensubtitles_legacy_login_is_migrated(self, config_manager):
        config_manager.save({
            "opensubtitles_username": "legacy",
            "opensubtitles_password": "secret",
        })

        assert config_manager.get_opensubtitles_accounts() == [
            {"username": "legacy", "password": "secret"},
        ]

    def test_remove_opensubtitles_accounts_removes_legacy_keys(self, config_manager):
        config_manager.set_opensubtitles_credentials("first", "one")
        config_manager.set_opensubtitles_credentials("second", "two")

        config_manager.remove_opensubtitles_credentials()

        assert config_manager.get_opensubtitles_accounts() == []


class TestRecentLibraries:
    def test_empty_initially(self, config_manager):
        assert config_manager.get_recent_libraries() == []

    def test_add_recent_library(self, config_manager):
        config_manager.add_recent_library("/path/one")
        libs = config_manager.get_recent_libraries()
        assert len(libs) == 1
        assert libs[0]["path"] == "/path/one"

    def test_add_dedupes_and_moves_to_front(self, config_manager):
        config_manager.add_recent_library("/path/a")
        config_manager.add_recent_library("/path/b")
        config_manager.add_recent_library("/path/a")  # re-add
        libs = config_manager.get_recent_libraries()
        assert len(libs) == 2
        assert libs[0]["path"] == "/path/a"
        assert libs[1]["path"] == "/path/b"

    def test_capped_at_ten(self, config_manager):
        for i in range(15):
            config_manager.add_recent_library(f"/path/{i}")
        libs = config_manager.get_recent_libraries(max_count=100)
        assert len(libs) == 10
        # Most recent first
        assert libs[0]["path"] == "/path/14"

    def test_max_count_param(self, config_manager):
        for i in range(8):
            config_manager.add_recent_library(f"/path/{i}")
        assert len(config_manager.get_recent_libraries(max_count=3)) == 3

    def test_clear(self, config_manager):
        config_manager.add_recent_library("/path/one")
        config_manager.clear_recent_libraries()
        assert config_manager.get_recent_libraries() == []


class TestKeepRecentLibraries:
    def test_default_is_false(self, config_manager):
        assert config_manager.get_keep_recent_libraries() is False

    def test_set_then_get(self, config_manager):
        config_manager.set_keep_recent_libraries(True)
        assert config_manager.get_keep_recent_libraries() is True

    def test_legacy_clear_recent_on_start_migration(self, config_manager):
        # Legacy: clear_recent_on_start=False means user wanted to keep libraries
        config_manager.set("clear_recent_on_start", False)
        assert config_manager.get_keep_recent_libraries() is True

        # When setting via the new API, the legacy key is dropped
        config_manager.set_keep_recent_libraries(False)
        assert "clear_recent_on_start" not in config_manager.load()


class TestImportExport:
    def test_export_returns_json(self, config_manager):
        config_manager.set("foo", "bar")
        exported = config_manager.export_config()
        assert json.loads(exported) == {"foo": "bar"}

    def test_import_replaces_config(self, config_manager):
        config_manager.set("old", "value")
        config_manager.import_config('{"new": "value"}')
        assert config_manager.load() == {"new": "value"}

    def test_import_invalid_json_raises(self, config_manager):
        with pytest.raises(Exception):
            config_manager.import_config("not valid json")


class TestReset:
    def test_reset_removes_config_file(self, config_manager):
        config_manager.set("k", "v")
        assert config_manager.config_file.exists()
        config_manager.reset()
        assert not config_manager.config_file.exists()


class TestCorruptedFile:
    def test_corrupted_json_returns_empty(self, config_manager):
        config_manager.config_file.write_text("{ not valid")
        assert config_manager.load() == {}


class TestMinPtWords:
    def test_default(self, config_manager):
        assert config_manager.get_min_pt_words() == 5

    def test_custom(self, config_manager):
        config_manager.set_min_pt_words(10)
        assert config_manager.get_min_pt_words() == 10


class TestConfigPersistentSettings:
    def test_kept_languages_are_normalized(self, config_manager):
        config_manager.set("kept_languages", ["pt-PT", "pt_BR", "eng"])

        config = Config()
        config.load_persistent_settings()

        assert config.kept_languages == ["por-pt", "por", "eng"]

    def test_opensubtitles_accounts_are_loaded(self, config_manager):
        config_manager.set_opensubtitles_credentials("first", "one")
        config_manager.set_opensubtitles_credentials("second", "two")

        config = Config()
        config.load_persistent_settings()

        assert config.opensubtitles_accounts == [
            {"username": "first", "password": "one"},
            {"username": "second", "password": "two"},
        ]
        assert config.opensubtitles_username == "first"
