"""Tests for core/renamer.py safety behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from jellyfix.core.renamer import RenameOperation, Renamer


def _renamer(tmp_path: Path) -> Renamer:
    config = MagicMock()
    config.fetch_metadata = False

    with patch("jellyfix.core.renamer.get_config", return_value=config):
        renamer = Renamer()

    renamer.work_dir = tmp_path
    return renamer


def test_execute_aborts_before_delete_when_reversible_operation_fails(tmp_path):
    delete_target = tmp_path / "foreign.spa.srt"
    delete_target.write_text("subtitle", encoding="utf-8")

    renamer = _renamer(tmp_path)
    renamer.operations = [
        RenameOperation(
            source=delete_target,
            destination=delete_target,
            operation_type="delete",
            reason="delete foreign subtitle",
        ),
        RenameOperation(
            source=tmp_path / "missing.mkv",
            destination=tmp_path / "renamed.mkv",
            operation_type="rename",
            reason="missing source",
        ),
    ]

    stats = renamer.execute_operations(dry_run=False)

    assert stats["failed"] == 1
    assert stats["deleted"] == 0
    assert delete_target.exists()


def test_untagged_kept_subtitle_receives_detected_language(tmp_path):
    subtitle = tmp_path / "Movie.srt"
    subtitle.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\n"
        "You cannot leave this place right now because we still have important work to do. "
        "She will return home when everything is finished, and he wants to speak with everyone. "
        "Where did you find these people and why are they waiting outside the building?\n",
        encoding="utf-8",
    )
    renamer = _renamer(tmp_path)
    renamer.config.rename_no_lang = True
    renamer.config.remove_foreign_subs = False
    renamer.config.kept_languages = ["por", "eng"]
    renamer.config.min_pt_words = 5

    renamer._plan_subtitle_other_operations(subtitle)

    assert len(renamer.operations) == 1
    assert renamer.operations[0].destination == tmp_path / "Movie.eng.srt"


def test_untagged_detected_foreign_subtitle_is_not_deleted(tmp_path):
    subtitle = tmp_path / "Movie.srt"
    subtitle.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\n"
        "Vous ne pouvez pas quitter cet endroit maintenant parce que nous avons encore du travail. "
        "Elle rentrera chez elle quand tout sera terminé et il souhaite parler avec tout le monde. "
        "Pourquoi ces personnes attendent-elles toujours devant le bâtiment ce soir ?\n",
        encoding="utf-8",
    )
    renamer = _renamer(tmp_path)
    renamer.config.rename_no_lang = True
    renamer.config.remove_foreign_subs = True
    renamer.config.kept_languages = ["por", "eng"]
    renamer.config.all_languages = {"por": "Portuguese", "eng": "English", "fre": "French"}
    renamer.config.min_pt_words = 5

    renamer._plan_subtitle_other_operations(subtitle)

    assert renamer.operations == []


class _FakeTvMetadata:
    """Metadata escolhido manualmente no SearchDialog (media_type explícito)."""

    title = "Dark"
    original_title = "Dark"
    year = 2017
    tmdb_id = 70523
    tvdb_id = None
    imdb_id = None
    media_type = "tvshow"


def _tv_renamer(tmp_path: Path) -> Renamer:
    renamer = _renamer(tmp_path)
    renamer.config.organize_folders = True
    renamer.config.add_quality_tag = False
    renamer.config.use_ffprobe = False
    renamer.config.rename_nfo = False
    renamer.config.remove_non_media = False
    renamer.config.rename_no_lang = False
    renamer.config.remove_foreign_subs = False
    renamer.config.kept_languages = ["por", "eng"]
    return renamer


def test_manual_tvshow_without_episode_pattern_does_not_crash(tmp_path):
    """Marcar como série um arquivo sem SxxExx não deve estourar TypeError."""
    video = tmp_path / "Dark 2017 1080p.mkv"
    video.write_bytes(b"x")

    renamer = _tv_renamer(tmp_path)
    ops = renamer.replan_for_video_with_metadata(
        video_path=video, metadata=_FakeTvMetadata(), work_dir=tmp_path
    )

    assert ops == []


def test_manual_tvshow_infers_episode_from_loose_marker(tmp_path):
    video = tmp_path / "Dark Ep 3.mkv"
    video.write_bytes(b"x")

    renamer = _tv_renamer(tmp_path)
    ops = renamer.replan_for_video_with_metadata(
        video_path=video, metadata=_FakeTvMetadata(), work_dir=tmp_path
    )

    assert ops[0].destination == (
        tmp_path / "Dark (2017) [tmdbid-70523]" / "Season 01" / "Dark - S01E03.mkv"
    )


def test_manual_tvshow_infers_season_from_season_folder(tmp_path):
    video = tmp_path / "Season 02" / "Dark 05.mkv"
    video.parent.mkdir()
    video.write_bytes(b"x")

    renamer = _tv_renamer(tmp_path)
    ops = renamer.replan_for_video_with_metadata(
        video_path=video, metadata=_FakeTvMetadata(), work_dir=tmp_path
    )

    assert ops[0].destination == (
        tmp_path / "Dark (2017) [tmdbid-70523]" / "Season 02" / "Dark - S02E05.mkv"
    )


def test_manual_tvshow_keeps_series_folder_beside_old_one(tmp_path):
    """Sem work_dir a pasta nova era criada DENTRO da pasta de temporada."""
    video = tmp_path / "Dark Antiga (2017)" / "Season 03" / "Dark S03E07.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")

    renamer = _tv_renamer(tmp_path)
    ops = renamer.replan_for_video_with_metadata(
        video_path=video, metadata=_FakeTvMetadata(), work_dir=tmp_path
    )

    assert ops[0].destination == (
        tmp_path / "Dark (2017) [tmdbid-70523]" / "Season 03" / "Dark - S03E07.mkv"
    )
