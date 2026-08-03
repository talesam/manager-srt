"""Tests for the styled operation confirmation summary."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jellyfix.core.renamer import RenameOperation
from jellyfix.gui.windows.main_window import JellyfixMainWindow
from jellyfix.gui.windows.operation_confirmation_window import count_operations


def _operation(operation_type):
    source = Path(f"/media/source-{operation_type}")
    destination = Path(f"/library/destination-{operation_type}")
    return RenameOperation(source, destination, operation_type, "test")


def test_count_operations_groups_all_visual_categories():
    operations = [
        _operation("rename"),
        _operation("move"),
        _operation("move_rename"),
        _operation("move_rename"),
        _operation("delete"),
    ]

    assert count_operations(operations) == {
        "rename": 1,
        "move": 1,
        "move_rename": 2,
        "delete": 1,
    }


def test_count_operations_handles_empty_summary():
    assert count_operations([]) == {}


def test_reset_clears_operations_and_preview():
    window = SimpleNamespace(
        hide_loading=Mock(),
        batch_progress=None,
        operations_list=SimpleNamespace(clear=Mock()),
        operations_handler=SimpleNamespace(
            operations=[object()],
            scanned_files=[Path("movie.mp4")],
        ),
        preview_panel=SimpleNamespace(clear=Mock()),
        selected_folders=[Path("folder")],
        selected_files=[Path("movie.mp4")],
        dashboard=SimpleNamespace(refresh_recent_libraries=Mock()),
        content_stack=SimpleNamespace(set_visible_child_name=Mock()),
        logger=SimpleNamespace(debug=Mock()),
    )

    JellyfixMainWindow._reset_to_welcome(window)

    window.operations_list.clear.assert_called_once_with()
    window.preview_panel.clear.assert_called_once_with()
    assert window.operations_handler.operations == []
    assert window.operations_handler.scanned_files == []
    window.content_stack.set_visible_child_name.assert_called_once_with("welcome")


def test_execution_completion_resets_before_centered_success():
    window = SimpleNamespace(
        hide_loading=Mock(),
        logger=SimpleNamespace(success=Mock()),
        _reset_to_welcome=Mock(),
        show_success=Mock(),
    )
    results = [object(), object(), object()]

    JellyfixMainWindow.on_execution_complete(window, results, dry_run=False)

    window._reset_to_welcome.assert_called_once_with()
    window.show_success.assert_called_once_with(3)


def test_stale_poster_cannot_restore_cleared_preview():
    selected = object()
    preview = SimpleNamespace(
        current_operation=None,
        load_poster=Mock(),
    )
    window = SimpleNamespace(preview_panel=preview)

    JellyfixMainWindow._load_poster_if_current(window, Path("poster.jpg"), selected)
    preview.load_poster.assert_not_called()

    preview.current_operation = selected
    JellyfixMainWindow._load_poster_if_current(window, Path("poster.jpg"), selected)
    preview.load_poster.assert_called_once_with(Path("poster.jpg"))
