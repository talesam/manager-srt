"""Tests for utils/helpers.py — core utility functions."""

import sys
from pathlib import Path

import pytest

# Ensure jellyfix is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usr" / "share"))

from jellyfix.utils.helpers import (
    calculate_subtitle_quality,
    clean_filename,
    detect_subtitle_language,
    extract_subtitle_dialogue,
    extract_quality_tag,
    extract_season_episode,
    extract_year,
    has_language_code,
    is_image_file,
    is_portuguese_subtitle,
    is_subtitle_file,
    is_video_file,
    normalize_language_code,
    normalize_spaces,
    parse_destination_for_search,
    parse_subtitle_filename,
    get_base_name,
    format_season_folder,
)


# ─── extract_year ────────────────────────────────────────────────────

class TestExtractYear:
    def test_year_in_parentheses(self):
        assert extract_year("The Matrix (1999)") == 1999

    def test_year_in_brackets(self):
        assert extract_year("The Matrix [2003]") == 2003

    def test_year_bare(self):
        assert extract_year("The Matrix 1999 1080p") == 1999

    def test_no_year(self):
        assert extract_year("The Matrix") is None

    def test_year_2000s(self):
        assert extract_year("Inception (2010)") == 2010

    def test_year_recent(self):
        assert extract_year("Dune Part Two 2024") == 2024

    def test_year_old_movie(self):
        assert extract_year("Some Classic (1950)") == 1950

    def test_number_not_year(self):
        # Numbers outside valid year range should not match
        assert extract_year("Area 51") is None

    def test_multiple_years_returns_first(self):
        result = extract_year("Movie (1999) Sequel 2003")
        assert result == 1999


# ─── extract_quality_tag ─────────────────────────────────────────────

class TestExtractQualityTag:
    @pytest.mark.parametrize("filename,expected", [
        ("movie.1080p.mkv", "1080p"),
        ("movie.720p.BluRay.mkv", "720p"),
        ("movie.480p.mkv", "480p"),
        ("movie.2160p.mkv", "2160p"),
        ("movie.4K.mkv", "2160p"),
        ("movie_1080p_bluray.mkv", "1080p"),
        ("movie [1080p].mkv", "1080p"),
        ("movie (720p).mkv", "720p"),
        ("movie.8K.mkv", "8K"),
    ])
    def test_resolution_detection(self, filename, expected):
        assert extract_quality_tag(filename) == expected

    def test_no_quality(self):
        assert extract_quality_tag("movie.mkv") is None

    def test_case_insensitive(self):
        assert extract_quality_tag("movie.1080P.mkv") == "1080p"


# ─── extract_season_episode ──────────────────────────────────────────

class TestExtractSeasonEpisode:
    def test_sxxexx(self):
        assert extract_season_episode("Show S01E05") == (1, 5, 5)

    def test_sxxexx_lowercase(self):
        assert extract_season_episode("show.s02e10.720p") == (2, 10, 10)

    def test_sxxexx_multi_episode(self):
        assert extract_season_episode("Show S01E01-E02") == (1, 1, 2)

    def test_nxnn(self):
        assert extract_season_episode("show 1x01") == (1, 1, 1)

    def test_nxnn_not_year(self):
        # "2018" should NOT be parsed as 20x18
        assert extract_season_episode("Movie 2018") is None

    def test_book_volume(self):
        assert extract_season_episode("Book 1 Episode 03") == (1, 3, 3)

    def test_temporada_ep(self):
        assert extract_season_episode("T01E05") == (1, 5, 5)

    def test_no_episode_info(self):
        assert extract_season_episode("The Matrix 1999 1080p") is None

    def test_season_episode_pattern(self):
        assert extract_season_episode("Season 2 Episode 5") == (2, 5, 5)

    def test_temp_pattern(self):
        assert extract_season_episode("Temp 3 Ep 12") == (3, 12, 12)

    def test_two_digit_season(self):
        assert extract_season_episode("Show S12E01") == (12, 1, 1)


# ─── is_video_file / is_subtitle_file / is_image_file ────────────────

class TestFileTypeDetection:
    @pytest.mark.parametrize("ext,expected", [
        (".mkv", True), (".mp4", True), (".avi", True),
        (".mov", True), (".webm", True), (".m4v", True),
        (".srt", False), (".txt", False), (".jpg", False),
    ])
    def test_is_video_file(self, ext, expected):
        assert is_video_file(Path(f"file{ext}")) == expected

    @pytest.mark.parametrize("ext,expected", [
        (".srt", True), (".ass", True), (".ssa", True),
        (".sub", True), (".vtt", True),
        (".mkv", False), (".txt", False),
    ])
    def test_is_subtitle_file(self, ext, expected):
        assert is_subtitle_file(Path(f"file{ext}")) == expected

    @pytest.mark.parametrize("ext,expected", [
        (".jpg", True), (".jpeg", True), (".png", True),
        (".gif", True), (".webp", True), (".svg", True),
        (".mkv", False), (".srt", False),
    ])
    def test_is_image_file(self, ext, expected):
        assert is_image_file(Path(f"file{ext}")) == expected


# ─── clean_filename ──────────────────────────────────────────────────

class TestCleanFilename:
    def test_removes_forbidden_chars(self):
        # ':' is rewritten to a space (not a dash): ':' is reserved on Jellyfin,
        # and a dash would collide with the "Series Name - S01E01" episode
        # separator, making Jellyfin read only the text before it as the title.
        assert clean_filename('Movie: The "Sequel"') == "Movie The Sequel"

    def test_removes_question_mark(self):
        assert clean_filename("What?") == "What"

    def test_removes_pipe(self):
        assert clean_filename("A|B") == "AB"

    def test_collapses_spaces(self):
        assert clean_filename("Movie   Name") == "Movie Name"

    def test_already_clean(self):
        assert clean_filename("My Movie (2024)") == "My Movie (2024)"


# ─── normalize_spaces ────────────────────────────────────────────────

class TestNormalizeSpaces:
    def test_dots_to_spaces(self):
        result = normalize_spaces("The.Matrix.1999")
        assert "The Matrix" in result
        assert "." not in result

    def test_underscores_to_spaces(self):
        result = normalize_spaces("The_Matrix")
        assert "The Matrix" in result

    def test_removes_quality_tags(self):
        result = normalize_spaces("Movie.Name.1080p.BluRay.x264")
        assert "1080p" not in result
        assert "BluRay" not in result
        assert "x264" not in result

    def test_removes_concatenated_streaming_source(self):
        result = normalize_spaces("Barba.Ensopada.De.Sangue.2025.1080p.AMZNWEB")
        assert result == "Barba Ensopada De Sangue"

    def test_preserves_year_in_parens(self):
        result = normalize_spaces("Movie Name (2024)")
        assert "(2024)" in result

    def test_removes_release_group(self):
        result = normalize_spaces("Movie.Name-YIFY")
        assert "YIFY" not in result

    def test_removes_bracket_content(self):
        result = normalize_spaces("Movie [1080p] [DUAL]")
        assert "[" not in result


# ─── has_language_code ────────────────────────────────────────────────

class TestHasLanguageCode:
    def test_eng_code(self):
        assert has_language_code("movie.eng.srt") == "eng"

    def test_por_code(self):
        assert has_language_code("movie.por.srt") == "por"

    def test_pt_code(self):
        assert has_language_code("movie.pt.srt") == "por"

    def test_pt_br_code(self):
        assert has_language_code("movie.pt-BR.srt") == "por"

    def test_pt_pt_code(self):
        assert has_language_code("movie.pt-PT.srt") == "por-pt"
        assert has_language_code("movie.pt_PT.srt") == "por-pt"

    def test_pt_code_detected(self):
        # Plain .pt. works fine
        assert has_language_code("movie.pt.srt") == "por"

    def test_no_code(self):
        assert has_language_code("movie.srt") is None

    def test_eng_forced(self):
        assert has_language_code("movie.eng.forced.srt") == "eng"

    def test_eng_sdh(self):
        assert has_language_code("movie.eng.sdh.srt") == "eng"

    def test_variant_number(self):
        assert has_language_code("movie.eng2.srt") == "eng"


# ─── normalize_language_code ──────────────────────────────────────────

class TestNormalizeLanguageCode:
    @pytest.mark.parametrize("code,expected", [
        ("en", "eng"), ("pt", "por"), ("es", "spa"), ("fr", "fre"),
        ("de", "ger"), ("it", "ita"), ("ja", "jpn"), ("ko", "kor"),
        ("br", "por"),
    ])
    def test_two_letter_codes(self, code, expected):
        assert normalize_language_code(code) == expected

    def test_three_letter_passthrough(self):
        assert normalize_language_code("eng") == "eng"
        assert normalize_language_code("por") == "por"

    def test_region_stripped(self):
        assert normalize_language_code("pt-BR") == "por"
        assert normalize_language_code("pt_BR") == "por"
        assert normalize_language_code("pt-PT") == "por-pt"
        assert normalize_language_code("pt_PT") == "por-pt"


# ─── calculate_subtitle_quality ──────────────────────────────────────

class TestCalculateSubtitleQuality:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.srt"
        f.write_text("")
        assert calculate_subtitle_quality(f) == 0.0

    def test_tiny_file(self, tmp_path):
        f = tmp_path / "tiny.srt"
        f.write_text("x" * 50)
        assert calculate_subtitle_quality(f) == 0.0

    def test_valid_subtitle(self, tmp_path):
        f = tmp_path / "good.srt"
        # Needs > 100 bytes to pass the minimum size check
        blocks = []
        for i in range(1, 20):
            blocks.append(f"{i}\n00:00:{i:02d},000 --> 00:00:{i+1:02d},000\nSubtitle line {i}\n")
        f.write_text("\n".join(blocks))
        score = calculate_subtitle_quality(f)
        assert score > 0

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "nonexistent.srt"
        assert calculate_subtitle_quality(f) == 0.0

    def test_larger_better(self, tmp_path):
        """A subtitle with more blocks should score higher."""
        small = tmp_path / "small.srt"
        large = tmp_path / "large.srt"

        small_content = (
            "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nWorld\n"
        )
        large_content = small_content * 20

        small.write_text(small_content)
        large.write_text(large_content)

        assert calculate_subtitle_quality(large) > calculate_subtitle_quality(small)


# ─── is_portuguese_subtitle ──────────────────────────────────────────

class TestIsPortugueseSubtitle:
    def test_portuguese_content(self, tmp_path):
        f = tmp_path / "test.srt"
        f.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n"
            "Você não pode fazer isso para ele\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\n"
            "Mas ela também vai com você sem onde ir\n\n"
            "3\n00:00:05,000 --> 00:00:06,000\n"
            "Como pode ser uma coisa muito boa\n"
        )
        assert is_portuguese_subtitle(f) is True

    def test_english_content(self, tmp_path):
        f = tmp_path / "test.srt"
        f.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n"
            "You cannot do this\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\n"
            "Where are we going now?\n"
        )
        assert is_portuguese_subtitle(f) is False

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "nonexistent.srt"
        assert is_portuguese_subtitle(f) is False

    def test_non_srt_extension(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Você não pode fazer isso")
        assert is_portuguese_subtitle(f) is False


# ─── content-based subtitle language detection ──────────────────

LANGUAGE_SAMPLES = {
    "por": (
        "Você não pode fazer isso agora, porque ainda temos muito trabalho. "
        "Ela vai para casa quando terminar, mas ele também quer falar sobre tudo. "
        "Como foi o seu dia e onde estão as pessoas que chegaram com você?"
    ),
    "eng": (
        "You cannot leave this place right now because we still have important work to do. "
        "She will return home when everything is finished, and he wants to speak with everyone. "
        "Where did you find these people and why are they waiting outside the building?"
    ),
    "fre": (
        "Vous ne pouvez pas quitter cet endroit maintenant parce que nous avons encore du travail. "
        "Elle rentrera chez elle quand tout sera terminé et il souhaite parler avec tout le monde. "
        "Pourquoi ces personnes attendent-elles toujours devant le bâtiment ce soir ?"
    ),
    "spa": (
        "No puedes salir de este lugar ahora porque todavía tenemos mucho trabajo por hacer. "
        "Ella volverá a casa cuando todo termine y él quiere hablar con todas las personas. "
        "Por qué siguen esperando afuera del edificio durante toda la noche?"
    ),
}


def _srt(text):
    return (
        "1\n00:00:01,000 --> 00:00:03,000\n"
        f"<i>{text}</i>\n"
    )


@pytest.mark.parametrize("language", ["por", "eng", "fre", "spa"])
def test_detects_untagged_srt_language(tmp_path, language):
    subtitle = tmp_path / "Movie.srt"
    subtitle.write_text(_srt(LANGUAGE_SAMPLES[language]), encoding="utf-8")

    assert detect_subtitle_language(subtitle) == language


def test_extracts_dialogue_from_ass_and_vtt(tmp_path):
    ass = tmp_path / "Movie.ass"
    ass.write_text(
        "[Script Info]\nTitle: Example\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,"
        f"{{\\i1}}{LANGUAGE_SAMPLES['eng']}{{\\i0}}\n",
        encoding="utf-8",
    )
    vtt = tmp_path / "Movie.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n"
        f"<v Speaker>{LANGUAGE_SAMPLES['fre']}</v>\n",
        encoding="utf-8",
    )

    assert "Dialogue:" not in extract_subtitle_dialogue(ass)
    assert detect_subtitle_language(ass) == "eng"
    assert detect_subtitle_language(vtt) == "fre"


def test_detects_textual_microdvd_sub_but_not_binary_sub(tmp_path):
    textual = tmp_path / "Movie.sub"
    textual.write_text(
        f"{{1}}{{80}}{LANGUAGE_SAMPLES['spa']}",
        encoding="utf-8",
    )
    binary = tmp_path / "Movie-binary.sub"
    binary.write_bytes(b"VobSub\x00\x01\x02" + b"binary data" * 20)

    assert detect_subtitle_language(textual) == "spa"
    assert extract_subtitle_dialogue(binary) == ""
    assert detect_subtitle_language(binary) is None


def test_short_or_ambiguous_subtitle_remains_unknown(tmp_path):
    subtitle = tmp_path / "Movie.srt"
    subtitle.write_text(_srt("Yes. No. Okay."), encoding="utf-8")

    assert detect_subtitle_language(subtitle) is None


def test_markup_and_accessibility_cues_do_not_drive_detection(tmp_path):
    subtitle = tmp_path / "Movie.srt"
    subtitle.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n"
        f"[DOOR SLAMS] <font color=\"white\">{LANGUAGE_SAMPLES['por']}</font> ♪\n",
        encoding="utf-8",
    )

    dialogue = extract_subtitle_dialogue(subtitle)
    assert "DOOR SLAMS" not in dialogue
    assert "font" not in dialogue
    assert detect_subtitle_language(subtitle) == "por"


# ─── parse_subtitle_filename ─────────────────────────────────────────

class TestParseSubtitleFilename:
    def test_lang_code(self):
        info = parse_subtitle_filename(Path("Movie.eng.srt"))
        assert info["language"] == "eng"

    def test_forced_flag(self):
        info = parse_subtitle_filename(Path("Movie.por.forced.srt"))
        assert info["forced"] is True
        assert info["language"] == "por"

    def test_sdh_flag(self):
        info = parse_subtitle_filename(Path("Movie.eng.sdh.srt"))
        assert info["sdh"] is True

    def test_default_flag(self):
        info = parse_subtitle_filename(Path("Movie.por.default.srt"))
        assert info["default"] is True

    def test_pt_pt_lang_code(self):
        info = parse_subtitle_filename(Path("Movie.pt-PT.srt"))
        assert info["language"] == "por-pt"

    def test_no_lang(self):
        info = parse_subtitle_filename(Path("Movie.srt"))
        assert info["language"] is None

    def test_base_name(self):
        info = parse_subtitle_filename(Path("My Movie.eng.forced.srt"))
        assert info["base_name"] == "My Movie"


# ─── get_base_name ───────────────────────────────────────────────────

class TestGetBaseName:
    def test_removes_lang_suffix(self):
        assert get_base_name(Path("Movie.por.srt")) == "Movie"

    def test_removes_regional_lang_suffix(self):
        assert get_base_name(Path("Movie.pt-PT.srt")) == "Movie"
        assert get_base_name(Path("Movie.pt_PT.srt")) == "Movie"

    def test_video_file(self):
        assert get_base_name(Path("Movie Name.mkv")) == "Movie Name"


# ─── format_season_folder ────────────────────────────────────────────

class TestFormatSeasonFolder:
    def test_single_digit(self):
        assert format_season_folder(1) == "Season 01"

    def test_double_digit(self):
        assert format_season_folder(12) == "Season 12"


# ─── parse_destination_for_search ─────────────────────────────────────

class TestParseDestinationForSearch:
    def test_movie_with_year_and_quality(self):
        dest = Path("/lib/Matrix (1999) [tmdbid-603]/The Matrix (1999) - 1080p.mkv")
        info = parse_destination_for_search(dest)
        assert info["title"] == "The Matrix"
        assert info["year"] == 1999
        assert info["is_episode"] is False
        assert info["season"] is None
        assert info["episode"] is None

    def test_episode_with_dash_separator(self):
        dest = Path("/lib/Show (2010) [tmdbid-1]/Season 01/Show - S01E05 - 720p.mkv")
        info = parse_destination_for_search(dest)
        assert info["title"] == "Show"
        assert info["is_episode"] is True
        assert info["season"] == 1
        assert info["episode"] == 5
        # Year is read from parent folder
        assert info["year"] == 2010

    def test_episode_without_dash(self):
        dest = Path("/lib/Show (2010)/Season 02/Show S02E10.mkv")
        info = parse_destination_for_search(dest)
        assert info["is_episode"] is True
        assert info["season"] == 2
        assert info["episode"] == 10

    def test_movie_no_year(self):
        dest = Path("/lib/Untitled.mkv")
        info = parse_destination_for_search(dest)
        assert info["title"] == "Untitled"
        assert info["year"] is None
        assert info["is_episode"] is False

    def test_raw_release_filename_with_bare_year(self):
        dest = Path("/tmp/a/Barba.Ensopada.De.Sangue.2025.1080p.AMZNWEB.mp4")
        info = parse_destination_for_search(dest)
        assert info["title"] == "Barba Ensopada De Sangue"
        assert info["year"] == 2025
        assert info["is_episode"] is False

    def test_episode_without_folder_year(self):
        dest = Path("/lib/Show/Season 01/Show S01E01.mkv")
        info = parse_destination_for_search(dest)
        assert info["is_episode"] is True
        assert info["year"] is None
