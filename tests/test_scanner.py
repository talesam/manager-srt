"""Tests for core/scanner.py — library file discovery and categorization."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usr" / "share"))

from jellyfix.core.scanner import LibraryScanner, ScanResult


@pytest.fixture
def mock_config():
    """Create a mock Config with sensible defaults."""
    config = MagicMock()
    config.kept_languages = ["por", "eng"]
    config.remove_non_media = False
    config.min_pt_words = 5
    config.min_subtitle_bytes = 20
    return config


@pytest.fixture
def scanner(mock_config):
    """Create a LibraryScanner with mocked config."""
    with patch("jellyfix.core.scanner.get_config", return_value=mock_config):
        return LibraryScanner()


class TestScanVideoFiles:
    def test_finds_mkv(self, scanner, tmp_path):
        (tmp_path / "movie.mkv").write_bytes(b"\x00" * 100)
        result = scanner.scan(tmp_path)
        assert len(result.video_files) == 1

    def test_finds_mp4(self, scanner, tmp_path):
        (tmp_path / "movie.mp4").write_bytes(b"\x00" * 100)
        result = scanner.scan(tmp_path)
        assert len(result.video_files) == 1

    def test_recursive_scan(self, scanner, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "video.mkv").write_bytes(b"\x00" * 100)
        result = scanner.scan(tmp_path)
        assert len(result.video_files) == 1

    def test_empty_directory(self, scanner, tmp_path):
        result = scanner.scan(tmp_path)
        assert result.total_files == 0

    def test_nonexistent_directory(self, scanner, tmp_path):
        result = scanner.scan(tmp_path / "nonexistent")
        assert result.total_files == 0


class TestScanSubtitleFiles:
    def test_finds_srt(self, scanner, tmp_path):
        srt = tmp_path / "movie.eng.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        result = scanner.scan(tmp_path)
        assert len(result.subtitle_files) == 1

    def test_skips_tiny_subtitle(self, scanner, tmp_path):
        srt = tmp_path / "tiny.srt"
        srt.write_text("x")  # < 20 bytes
        result = scanner.scan(tmp_path)
        assert len(result.subtitle_files) == 0

    def test_categorizes_kept_language(self, scanner, tmp_path):
        srt = tmp_path / "movie.eng.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello World\n")
        result = scanner.scan(tmp_path)
        assert len(result.kept_subtitles) == 1

    def test_categorizes_portugal_portuguese_when_kept(self, mock_config, tmp_path):
        mock_config.kept_languages = ["por-pt", "eng"]
        with patch("jellyfix.core.scanner.get_config", return_value=mock_config):
            scanner = LibraryScanner()

        srt = tmp_path / "movie.pt-PT.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nOlá Mundo\n")

        result = scanner.scan(tmp_path)
        assert len(result.kept_subtitles) == 1

    def test_categorizes_variant(self, scanner, tmp_path):
        srt = tmp_path / "movie.por2.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nOlá Mundo\n")
        result = scanner.scan(tmp_path)
        assert len(result.variant_subtitles) == 1

    def test_categorizes_foreign(self, scanner, tmp_path):
        srt = tmp_path / "movie.spa.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHola Mundo\n")
        result = scanner.scan(tmp_path)
        assert len(result.foreign_subtitles) == 1

    def test_forced_not_foreign(self, scanner, tmp_path):
        srt = tmp_path / "movie.spa.forced.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHola\n")
        result = scanner.scan(tmp_path)
        # .forced subtitles should NOT be classified as foreign
        assert len(result.foreign_subtitles) == 0

    def test_untagged_kept_language_is_detected(self, scanner, tmp_path):
        srt = tmp_path / "movie.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:04,000\n"
            "You cannot leave this place right now because we still have important work to do. "
            "She will return home when everything is finished, and he wants to speak with everyone. "
            "Where did you find these people and why are they waiting outside the building?\n"
        )

        result = scanner.scan(tmp_path)

        assert result.no_lang_subtitles == [srt]

    def test_untagged_foreign_language_stays_safe(self, scanner, tmp_path):
        srt = tmp_path / "movie.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:04,000\n"
            "Vous ne pouvez pas quitter cet endroit maintenant parce que nous avons encore du travail. "
            "Elle rentrera chez elle quand tout sera terminé et il souhaite parler avec tout le monde. "
            "Pourquoi ces personnes attendent-elles toujours devant le bâtiment ce soir ?\n"
        )

        result = scanner.scan(tmp_path)

        assert result.foreign_subtitles == []
        assert result.other_files == [srt]


class TestScanOtherFiles:
    def test_nfo_files(self, scanner, tmp_path):
        (tmp_path / "movie.nfo").write_text("<movie/>")
        result = scanner.scan(tmp_path)
        assert len(result.nfo_files) == 1

    def test_image_files(self, scanner, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"\x00" * 100)
        result = scanner.scan(tmp_path)
        assert len(result.image_files) == 1

    def test_other_files(self, scanner, tmp_path):
        (tmp_path / "readme.txt").write_text("info")
        result = scanner.scan(tmp_path)
        assert len(result.other_files) == 1


class TestHiddenFiles:
    def test_hidden_skipped_by_default(self, scanner, tmp_path):
        (tmp_path / ".unmanic").write_text("hidden")
        result = scanner.scan(tmp_path)
        assert len(result.other_files) == 0

    def test_hidden_collected_when_remove_non_media(self, mock_config, tmp_path):
        mock_config.remove_non_media = True
        with patch("jellyfix.core.scanner.get_config", return_value=mock_config):
            scanner = LibraryScanner()
        (tmp_path / ".unmanic").write_text("hidden")
        result = scanner.scan(tmp_path)
        assert len(result.non_media_files) == 1

    def test_non_media_includes_nfo_when_enabled(self, mock_config, tmp_path):
        mock_config.remove_non_media = True
        with patch("jellyfix.core.scanner.get_config", return_value=mock_config):
            scanner = LibraryScanner()
        (tmp_path / "movie.nfo").write_text("<movie/>")
        result = scanner.scan(tmp_path)
        assert len(result.non_media_files) == 1


class TestScanResult:
    def test_total_files_property(self):
        result = ScanResult()
        result.video_files = [Path("a.mkv"), Path("b.mp4")]
        result.subtitle_files = [Path("c.srt")]
        result.other_files = [Path("d.txt")]
        assert result.total_files == 4
