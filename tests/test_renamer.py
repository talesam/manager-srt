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
