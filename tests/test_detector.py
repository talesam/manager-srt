"""Tests for core/detector.py — media type detection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usr" / "share"))

from jellyfix.core.detector import MediaInfo, MediaType


class TestMovieDetection:
    """Movies should be detected when there's no season/episode pattern."""

    def test_simple_movie(self, tmp_path):
        f = tmp_path / "The Matrix.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_movie()
        assert info.title == "The Matrix"

    def test_movie_with_year(self, tmp_path):
        f = tmp_path / "Inception 2010 1080p.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_movie()
        assert info.title == "Inception"
        assert info.year == 2010

    def test_movie_with_parenthesized_year(self, tmp_path):
        f = tmp_path / "Nada Entre Nós (2026) - 1080p.mp4"
        f.touch()
        info = MediaInfo(f)
        assert info.is_movie()
        assert info.title == "Nada Entre Nós"
        assert info.year == 2026

    def test_movie_with_quality(self, tmp_path):
        f = tmp_path / "Movie.Name.2024.720p.BluRay.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_movie()
        assert info.title == "Movie Name"
        assert info.year == 2024

    def test_movie_with_concatenated_streaming_source(self, tmp_path):
        f = tmp_path / "Barba.Ensopada.De.Sangue.2025.1080p.AMZNWEB.mp4"
        f.touch()
        info = MediaInfo(f)
        assert info.is_movie()
        assert info.title == "Barba Ensopada De Sangue"
        assert info.year == 2025

    def test_non_video_ignored(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.touch()
        info = MediaInfo(f)
        assert info.media_type == MediaType.UNKNOWN


class TestTVShowDetection:
    """TV shows should be detected from episode patterns."""

    def test_sxxexx(self, tmp_path):
        f = tmp_path / "Breaking Bad S01E05.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.season == 1
        assert info.episode_start == 5
        assert info.title == "Breaking Bad"

    def test_sxxexx_lowercase(self, tmp_path):
        f = tmp_path / "show.name.s02e10.720p.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.season == 2
        assert info.episode_start == 10

    def test_multi_episode(self, tmp_path):
        f = tmp_path / "Show S01E01-E02.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.episode_start == 1
        assert info.episode_end == 2

    def test_nxnn_format(self, tmp_path):
        f = tmp_path / "show 1x05.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.season == 1
        assert info.episode_start == 5

    def test_season_folder(self, tmp_path):
        """File in a Season XX folder without episode pattern in filename."""
        season_dir = tmp_path / "Season 02"
        season_dir.mkdir()
        f = season_dir / "some_episode.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.season == 2

    def test_temporada_folder(self, tmp_path):
        """Portuguese season folder naming."""
        season_dir = tmp_path / "Temporada 03"
        season_dir.mkdir()
        f = season_dir / "episode.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.season == 3

    def test_book_pattern(self, tmp_path):
        f = tmp_path / "Book 1 Episode 03.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.season == 1
        assert info.episode_start == 3

    def test_volume_pattern(self, tmp_path):
        f = tmp_path / "Volume 2 Ep 05.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()

    def test_title_extraction_sxxexx(self, tmp_path):
        f = tmp_path / "Game of Thrones S08E06.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.title == "Game of Thrones"

    def test_title_extraction_nxnn(self, tmp_path):
        f = tmp_path / "Friends 3x14.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.title == "Friends"

    def test_anime_absolute_numbering_is_a_tvshow(self, tmp_path):
        """Regressão: release de anime virava filme e o título era o arquivo inteiro."""
        f = tmp_path / "[Elite] Serial Experiments Lain - 01 [BD 1080p AAC-FLAC] [DUAL] [419E776F].mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.season == 1
        assert info.episode_start == 1
        assert info.title == "[Elite] Serial Experiments Lain"


class TestEdgeCases:
    """Edge cases and tricky filenames."""

    def test_year_not_confused_with_episode(self, tmp_path):
        """Year 2018 should NOT be parsed as S20E18."""
        f = tmp_path / "Movie 2018.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_movie()

    def test_subtitle_detected_as_unknown(self, tmp_path):
        f = tmp_path / "movie.srt"
        f.touch()
        info = MediaInfo(f)
        assert info.media_type == MediaType.UNKNOWN

    def test_spaces_in_name(self, tmp_path):
        f = tmp_path / "My Long Movie Name S01E01.mkv"
        f.touch()
        info = MediaInfo(f)
        assert info.is_tvshow()
        assert info.title == "My Long Movie Name"
