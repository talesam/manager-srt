#!/usr/bin/env python3
"""Rich confirmation window for planned file operations."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ...utils.i18n import _  # noqa: E402
from .simulation_window import OPERATION_STYLES  # noqa: E402


def count_operations(operations) -> dict:
    """Count planned operations by type."""
    counts = {}
    for operation in operations:
        operation_type = getattr(operation, "operation_type", "unknown")
        counts[operation_type] = counts.get(operation_type, 0) + 1
    return counts


class OperationConfirmationWindow(Adw.Window):
    """Show a semantic summary before applying filesystem changes."""

    def __init__(self, parent, operations, on_confirm):
        super().__init__(transient_for=parent, modal=True)

        self.operations = list(operations or [])
        self.on_confirm = on_confirm

        self.set_title(_("Review changes"))
        self.set_default_size(620, 500)
        self.set_resizable(False)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title=_("Review changes"),
            subtitle=_("Confirm what Jellyfix will do"),
        ))
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(28)
        content.set_margin_end(28)
        content.append(self._build_heading())
        content.append(self._build_summary())

        if count_operations(self.operations).get("delete"):
            content.append(self._build_delete_warning())

        content.append(self._build_actions())
        toolbar.set_content(content)
        self.set_content(toolbar)

    def _build_heading(self) -> Gtk.Widget:
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading.set_halign(Gtk.Align.CENTER)

        icon_box = Gtk.Box()
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.add_css_class("confirmation-hero-icon")
        icon = Gtk.Image.new_from_icon_name("document-save-symbolic")
        icon.set_pixel_size(38)
        icon_box.append(icon)
        heading.append(icon_box)

        title = Gtk.Label(label=_("Apply these changes?"))
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.CENTER)
        heading.append(title)

        description = Gtk.Label(
            label=_("Check the summary before Jellyfix organizes your files."),
        )
        description.add_css_class("dim-label")
        description.set_halign(Gtk.Align.CENTER)
        description.set_wrap(True)
        heading.append(description)
        return heading

    def _build_summary(self) -> Gtk.Widget:
        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        summary.add_css_class("confirmation-summary")

        total_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        total_label = Gtk.Label(label=_("Planned operations"))
        total_label.add_css_class("heading")
        total_label.set_halign(Gtk.Align.START)
        total_label.set_hexpand(True)
        total_row.append(total_label)

        total = Gtk.Label(label=str(len(self.operations)))
        total.add_css_class("confirmation-total")
        total_row.append(total)
        summary.append(total_row)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        summary.append(separator)

        stats = Gtk.FlowBox()
        stats.set_selection_mode(Gtk.SelectionMode.NONE)
        stats.set_homogeneous(True)
        stats.set_min_children_per_line(2)
        stats.set_max_children_per_line(2)
        stats.set_column_spacing(10)
        stats.set_row_spacing(10)

        counts = count_operations(self.operations)
        for operation_type, (emoji, label, css_class) in OPERATION_STYLES.items():
            count = counts.get(operation_type, 0)
            if count:
                stats.append(self._build_stat(emoji, label, count, css_class))

        summary.append(stats)
        return summary

    @staticmethod
    def _build_stat(emoji, label, count, css_class) -> Gtk.Widget:
        stat = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        stat.add_css_class("confirmation-stat")
        stat.add_css_class(css_class)

        icon = Gtk.Label(label=emoji)
        icon.add_css_class("confirmation-stat-icon")
        stat.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        count_label = Gtk.Label(label=str(count))
        count_label.add_css_class("title-3")
        count_label.set_halign(Gtk.Align.START)
        text.append(count_label)

        type_label = Gtk.Label(label=label)
        type_label.add_css_class("caption")
        type_label.set_halign(Gtk.Align.START)
        text.append(type_label)
        stat.append(text)
        return stat

    @staticmethod
    def _build_delete_warning() -> Gtk.Widget:
        warning = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        warning.add_css_class("confirmation-warning")

        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(24)
        warning.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=_("Permanent deletions included"))
        title.add_css_class("heading")
        title.set_halign(Gtk.Align.START)
        text.append(title)

        detail = Gtk.Label(label=_("Deleted files cannot be recovered."))
        detail.set_halign(Gtk.Align.START)
        detail.set_wrap(True)
        text.append(detail)
        warning.append(text)
        return warning

    def _build_actions(self) -> Gtk.Widget:
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.set_halign(Gtk.Align.END)
        actions.set_margin_top(4)

        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_args: self.close())
        actions.append(cancel)

        apply_button = Gtk.Button()
        content = Adw.ButtonContent()
        content.set_icon_name("emblem-ok-symbolic")
        content.set_label(_("Apply changes"))
        apply_button.set_child(content)
        apply_button.add_css_class("suggested-action")
        apply_button.add_css_class("pill")
        apply_button.connect("clicked", self._on_apply_clicked)
        actions.append(apply_button)
        return actions

    def _on_apply_clicked(self, _button):
        callback = self.on_confirm
        self.close()
        if callback:
            callback()
