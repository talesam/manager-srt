"""Tests for core/subtitle_manager.py language handling."""

import sys
from pathlib import Path

from babelfish import Language

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usr" / "share"))

from jellyfix.core.subtitle_manager import SubtitleManager, _patch_opensubtitlescom_languages


class DummyConfig:
    kept_languages = ["por", "eng"]
    subtitle_providers = ["opensubtitlescom"]
    subtitle_extra_providers = []
    subtitle_max_pages = 1
    subtitle_timeout = 15
    opensubtitles_username = ""
    opensubtitles_password = ""
    opensubtitles_apikey = ""
    opensubtitles_accounts = []
    min_pt_words = 5


ENGLISH_SUBTITLE = (
    "1\n00:00:01,000 --> 00:00:04,000\n"
    "You cannot leave this place right now because we still have important work to do. "
    "She will return home when everything is finished, and he wants to speak with everyone. "
    "Where did you find these people and why are they waiting outside the building?\n"
)


class DummySubtitle:
    def __init__(self, language, release_info=""):
        self.language = language
        self.release_info = release_info


def test_build_languages_uses_portugal_variant(monkeypatch):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()

    langs = manager._build_languages(["por-pt"])

    assert Language("por", "PT") in langs
    assert Language("por", "BR") not in langs


def test_opensubtitlescom_provider_allows_portugal_portuguese(monkeypatch):
    import jellyfix.core.subtitle_manager as subtitle_manager
    from subliminal.providers.opensubtitlescom import OpenSubtitlesComProvider

    monkeypatch.setattr(subtitle_manager, "_OSCOM_LANGUAGES_PATCHED", False)
    OpenSubtitlesComProvider.languages.discard(Language("por", "PT"))

    _patch_opensubtitlescom_languages()

    assert Language("por", "PT") in OpenSubtitlesComProvider.languages


def test_build_languages_keeps_existing_portuguese_brazil_behavior(monkeypatch):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()

    langs = manager._build_languages(["por"])

    assert Language("por") in langs
    assert Language("por", "BR") in langs
    assert Language("por", "PT") not in langs


def test_subtitle_language_code_preserves_portugal_variant(monkeypatch):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    sub = DummySubtitle(Language("por", "PT"))

    assert manager._subtitle_language_code(sub) == "por-pt"


def test_generic_portuguese_release_stays_generic(monkeypatch):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    sub = DummySubtitle(Language("por"), release_info="Portuguese subtitles")

    assert manager._subtitle_language_code(sub) == "por"


def test_extract_tmdb_info_cleans_raw_release_filename():
    path = Path("/tmp/a/Barba.Ensopada.De.Sangue.2025.1080p.AMZNWEB.mp4")

    assert SubtitleManager.extract_tmdb_info_from_path(path) == (
        None,
        "Barba Ensopada De Sangue",
        2025,
    )


def test_download_only_searches_for_missing_sidecar_language(monkeypatch, tmp_path):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    (tmp_path / "Movie.eng.srt").write_text("English", encoding="utf-8")
    searched = {}

    def fake_search(video_path, languages, providers, min_score):
        searched['languages'] = languages
        return {}

    monkeypatch.setattr(manager, "_search_by_hash", fake_search)

    result = manager.download_subtitles(video, languages=["eng", "por"])

    assert set(result) == {"eng"}
    assert result["eng"] == []
    assert Language("eng") not in searched['languages']
    assert Language("por") in searched['languages']


def test_download_detects_untagged_sidecar_before_search(monkeypatch, tmp_path):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    (tmp_path / "Movie.srt").write_text(ENGLISH_SUBTITLE, encoding="utf-8")
    searched = {}

    def fake_search(video_path, languages, providers, min_score):
        searched["languages"] = languages
        return {}

    monkeypatch.setattr(manager, "_search_by_hash", fake_search)

    result = manager.download_subtitles(video, languages=["eng", "por"])

    assert result["eng"] == []
    assert Language("eng") not in searched["languages"]
    assert Language("por") in searched["languages"]


def test_download_skips_search_when_all_languages_exist(monkeypatch, tmp_path):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    (tmp_path / "Movie.en.srt").write_text("English", encoding="utf-8")
    (tmp_path / "Movie.pt-BR.ass").write_text("Português", encoding="utf-8")

    def unexpected_search(*args, **kwargs):
        raise AssertionError("provider search must not run")

    monkeypatch.setattr(manager, "_search_by_hash", unexpected_search)

    result = manager.download_subtitles(video, languages=["eng", "por"])

    assert result == {"eng": [], "por": []}


def test_existing_subtitles_ignore_other_video_sidecars(monkeypatch, tmp_path):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    (tmp_path / "Other.eng.srt").write_text("English", encoding="utf-8")

    assert manager._existing_subtitle_languages(video) == {}


def test_forced_sidecar_does_not_satisfy_full_language(monkeypatch, tmp_path):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    (tmp_path / "Movie.eng.forced.srt").write_text("Forced", encoding="utf-8")

    assert manager._existing_subtitle_languages(video) == {}


def test_batch_groups_videos_by_languages_still_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("jellyfix.core.subtitle_manager.get_config", lambda: DummyConfig())
    manager = SubtitleManager()
    first = tmp_path / "First.mkv"
    second = tmp_path / "Second.mkv"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    (tmp_path / "First.eng.srt").write_text("English", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        "jellyfix.core.subtitle_manager.scan_video", lambda path: path.name
    )

    def fake_download(videos, languages, **kwargs):
        calls.append((set(videos), set(languages)))
        return {}

    monkeypatch.setattr(
        "jellyfix.core.subtitle_manager.download_best_subtitles", fake_download
    )

    result = manager.download_subtitles_batch(
        [first, second], languages=["eng", "por"]
    )

    assert result[first] == {"eng": []}
    assert ({"First.mkv"}, manager._build_languages(["por"])) in calls
    assert (
        {"Second.mkv"}, manager._build_languages(["eng", "por"])
    ) in calls


def test_empty_download_rotates_to_next_opensubtitles_account(monkeypatch):
    class MultiAccountConfig(DummyConfig):
        opensubtitles_accounts = [
            {"username": "limited", "password": "one"},
            {"username": "available", "password": "two"},
        ]

    monkeypatch.setattr(
        "jellyfix.core.subtitle_manager.get_config", lambda: MultiAccountConfig()
    )
    manager = SubtitleManager()
    sub = DummySubtitle(Language("eng"))
    sub.provider_name = "opensubtitlescom"
    sub.content = None
    attempted = []
    monkeypatch.setattr("jellyfix.core.subtitle_manager.time.sleep", lambda seconds: None)

    def fake_download(subtitles, provider_configs):
        username = provider_configs['opensubtitlescom']['username']
        attempted.append(username)
        if username == "available":
            subtitles[0].content = b"subtitle"

    monkeypatch.setattr("subliminal.download_subtitles", fake_download)

    assert manager._retry_with_next_opensubtitles_account(sub) is True
    assert attempted == ["available"]
    assert manager._get_provider_configs()['opensubtitlescom']['username'] == "available"
