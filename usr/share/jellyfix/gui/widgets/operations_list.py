#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/operations_list.py - Operations list view
#

"""
Operations list view for displaying rename operations.

Shows:
  - Source filename
  - Destination filename
  - Operation type (rename, move, delete)
  - Reason for operation
  - Checkbox for selection
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib
from typing import Optional, Callable, List

from ...utils.i18n import _
from ...utils.config import get_config
from ...core.renamer import RenameOperation


def _markup_escape(value) -> str:
    return GLib.markup_escape_text(str(value))


class OperationRow(Adw.ActionRow):
    """Single operation row"""

    def __init__(self, operation: RenameOperation, index: int, is_subtitle: bool = False):
        """
        Initialize operation row.

        Args:
            operation: RenameOperation instance
            index: Operation index
            is_subtitle: Whether this is a subtitle (for indentation)
        """
        super().__init__()

        self.operation = operation
        self.index = index

        # Set title to source filename
        self.set_title(_markup_escape(operation.source.name))

        # Set subtitle to destination
        dest_name = operation.destination.name
        if operation.source.parent != operation.destination.parent:
            # Different folder, show relative path
            dest_name = f"{operation.destination.parent.name}/{dest_name}"

        self.set_subtitle(f"→ {_markup_escape(dest_name)}")

        # Determine file type and icon based on extension
        ext = operation.source.suffix.lower()
        
        # Video extensions
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.mpg', '.mpeg'}
        # Subtitle extensions
        subtitle_exts = {'.srt', '.sub', '.ass', '.ssa', '.vtt'}
        # Image extensions
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        
        if ext in video_exts:
            icon_name = 'video-x-generic-symbolic'
            self.add_css_class('video-row')
        elif ext in subtitle_exts:
            icon_name = 'text-x-generic-symbolic'
            self.add_css_class('subtitle-row')
        elif ext in image_exts:
            icon_name = 'image-x-generic-symbolic'
        elif operation.operation_type == 'delete':
            icon_name = 'user-trash-symbolic'
        elif operation.operation_type == 'move' or operation.operation_type == 'move_rename':
            icon_name = 'folder-symbolic'
        else:
            icon_name = 'document-edit-symbolic'

        prefix_icon = Gtk.Image.new_from_icon_name(icon_name)
        self.add_prefix(prefix_icon)

        # Add visual styling for operation type
        if operation.operation_type == 'delete':
            self.add_css_class('error')
        elif operation.will_overwrite:
            self.add_css_class('warning')
        
        # Indent subtitles slightly
        if is_subtitle:
            self.set_margin_start(24)

        # Make row activatable
        self.set_activatable(True)


class OperationsListView(Gtk.Box):
    """Operations list view widget"""

    def __init__(self, on_operation_selected: Optional[Callable] = None,
                 on_apply_clicked: Optional[Callable] = None,
                 on_download_subs_clicked: Optional[Callable] = None):
        """
        Initialize operations list.

        Args:
            on_operation_selected: Callback when operation is selected
            on_apply_clicked: Callback when apply button is clicked
            on_download_subs_clicked: Callback for batch subtitle download
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self.on_operation_selected = on_operation_selected
        self.on_apply_clicked = on_apply_clicked
        self.on_download_subs_clicked = on_download_subs_clicked
        self.operations: List[RenameOperation] = []
        self.filtered_operations: List[RenameOperation] = []
        self.current_filter = "all"  # all, rename, move, delete
        self.search_text = ""
        # Tracks (row, handler_id) so we can disconnect on every rebuild.
        self._row_handlers: List = []
        # Linha atualmente selecionada — recebe a classe CSS .row-selected
        # para feedback visual ao usuário (Adw.ActionRow não mantém estado
        # selecionado nativamente em PreferencesGroup).
        self._selected_row: Optional[OperationRow] = None

        # Set expansion - CRITICAL for layout
        self.set_vexpand(True)
        self.set_hexpand(True)

        # Add CSS class
        self.add_css_class("operations-list")

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build operations list UI"""
        # Header bar
        header = Adw.HeaderBar()
        header.add_css_class("flat")

        # Title
        title_label = Gtk.Label()
        title_label.set_markup("<b>" + _("Operations") + "</b>")
        header.set_title_widget(title_label)

        self.append(header)

        # Toolbar with search and filters
        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar.set_spacing(6)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)

        # Search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(_("Search..."))
        self.search_entry.connect("search-changed", self._on_search_changed)
        toolbar.append(self.search_entry)

        # Filter buttons — cores semânticas por tipo de operação.
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        filter_box.set_spacing(4)
        filter_box.set_homogeneous(True)
        filter_box.add_css_class("filter-bar")
        filter_box.add_css_class("linked")

        # All button (neutro)
        self.filter_all_btn = Gtk.ToggleButton(label=_("All"))
        self.filter_all_btn.set_active(True)
        self.filter_all_btn.add_css_class("filter-all")
        self.filter_all_btn.add_css_class("flat")
        self.filter_all_btn.connect("toggled", self._on_filter_changed, "all")
        filter_box.append(self.filter_all_btn)

        # Rename (accent)
        self.filter_rename_btn = Gtk.ToggleButton(label=_("Rename"))
        self.filter_rename_btn.set_group(self.filter_all_btn)
        self.filter_rename_btn.add_css_class("filter-rename")
        self.filter_rename_btn.add_css_class("flat")
        self.filter_rename_btn.connect("toggled", self._on_filter_changed, "rename")
        filter_box.append(self.filter_rename_btn)

        # Move (success)
        self.filter_move_btn = Gtk.ToggleButton(label=_("Move"))
        self.filter_move_btn.set_group(self.filter_all_btn)
        self.filter_move_btn.add_css_class("filter-move")
        self.filter_move_btn.add_css_class("flat")
        self.filter_move_btn.connect("toggled", self._on_filter_changed, "move")
        filter_box.append(self.filter_move_btn)

        # Delete (destructive)
        self.filter_delete_btn = Gtk.ToggleButton(label=_("Delete"))
        self.filter_delete_btn.set_group(self.filter_all_btn)
        self.filter_delete_btn.add_css_class("filter-delete")
        self.filter_delete_btn.add_css_class("flat")
        self.filter_delete_btn.connect("toggled", self._on_filter_changed, "delete")
        filter_box.append(self.filter_delete_btn)

        toolbar.append(filter_box)

        # Download Subtitles Button — visual de ação destacada, mas não primária.
        self.download_subs_btn = Gtk.Button()
        dl_content = Adw.ButtonContent()
        dl_content.set_icon_name("media-view-subtitles-symbolic")
        dl_content.set_label(_("Download Subtitles for All"))
        self.download_subs_btn.set_child(dl_content)
        self.download_subs_btn.set_tooltip_text(_("Search and download subtitles for all listed videos"))
        self.download_subs_btn.add_css_class("batch-action")
        self.download_subs_btn.connect("clicked", self._on_download_batch_clicked)
        toolbar.append(self.download_subs_btn)

        self.append(toolbar)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Operations list container
        self.operations_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.operations_box.set_spacing(0)

        # Empty state
        self.empty_state = Adw.StatusPage(
            icon_name="document-properties-symbolic",
            title=_("No Operations"),
            description=_("Scan a directory to generate operations")
        )
        self.operations_box.append(self.empty_state)

        # Operations group (hidden initially)
        self.operations_group = Adw.PreferencesGroup()
        self.operations_group.set_visible(False)

        self.operations_box.append(self.operations_group)

        scrolled.set_child(self.operations_box)
        self.append(scrolled)

        # Status bar with apply button
        self.status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.status_bar.set_spacing(12)
        self.status_bar.set_margin_top(6)
        self.status_bar.set_margin_bottom(6)
        self.status_bar.set_margin_start(12)
        self.status_bar.set_margin_end(12)

        self.status_label = Gtk.Label()
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_hexpand(True)
        self.status_bar.append(self.status_label)

        # Simulação (dry-run): deixa conferir o que será feito SEM tocar nos
        # arquivos. Fica ao lado do botão Aplicar, que é onde a dúvida aparece.
        self.dry_run_label = Gtk.Label(label=_("Simulation"))
        self.dry_run_label.set_tooltip_text(
            _("Preview every change without touching any file")
        )
        self.status_bar.append(self.dry_run_label)

        self.dry_run_switch = Gtk.Switch()
        self.dry_run_switch.set_valign(Gtk.Align.CENTER)
        self.dry_run_switch.set_tooltip_text(
            _("Preview every change without touching any file")
        )
        self.dry_run_switch.set_active(bool(get_config().dry_run))
        self.dry_run_switch.connect("notify::active", self._on_dry_run_toggled)
        self.status_bar.append(self.dry_run_switch)

        # Apply button
        self.apply_button = Gtk.Button()
        self.apply_content = Adw.ButtonContent()
        self.apply_content.set_icon_name("emblem-ok-symbolic")
        self.apply_content.set_label(_("Apply"))
        self.apply_button.set_child(self.apply_content)
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.set_sensitive(False)
        self.apply_button.connect("clicked", self._on_apply_clicked)
        self.status_bar.append(self.apply_button)

        self.append(self.status_bar)
        self._refresh_apply_button()

    def _on_dry_run_toggled(self, switch, _param):
        """Liga/desliga o modo simulação (lembrado entre sessões)."""
        ativo = switch.get_active()
        get_config().dry_run = ativo
        self._refresh_apply_button()
        try:
            from ...utils.config_manager import ConfigManager
            ConfigManager().set('gui_dry_run', ativo)
        except Exception as e:  # preferência é conveniência, nunca quebra o app
            import logging
            logging.getLogger(__name__).debug("Não foi possível salvar gui_dry_run: %s", e)

    def _refresh_apply_button(self):
        """Deixa explícito no botão se vai simular ou aplicar de verdade."""
        dry = bool(get_config().dry_run)
        self.apply_content.set_label(_("Simulate") if dry else _("Apply"))
        self.apply_content.set_icon_name(
            "view-reveal-symbolic" if dry else "emblem-ok-symbolic"
        )
        if dry:
            self.apply_button.remove_css_class("suggested-action")
        else:
            self.apply_button.add_css_class("suggested-action")

    def _on_apply_clicked(self, button):
        """Handle apply button click"""
        if self.on_apply_clicked and self.operations:
            self.on_apply_clicked(self.operations)

    def _on_download_batch_clicked(self, button):
        """Handle download batch button click"""
        if self.on_download_subs_clicked and self.operations:
            # Pass all operations, or maybe just filtered ones?
            # User probably expects what they see to be processed, or all available.
            # Let's pass filtered operations to be consistent with "what I see is what I get"
            # BUT, we only want video operations.
            video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.mpg', '.mpeg'}
            
            videos = [
                op for op in self.filtered_operations 
                if op.source.suffix.lower() in video_exts
            ]
            
            self.on_download_subs_clicked(videos)

    def set_operations(self, operations: List[RenameOperation]):
        """
        Set operations to display.

        Args:
            operations: List of RenameOperation instances
        """
        self.operations = operations
        self._apply_filters()

        # Enable/disable apply button
        self.apply_button.set_sensitive(len(operations) > 0)
        
        # Enable/disable download button
        self.download_subs_btn.set_sensitive(len(operations) > 0)

    def _apply_filters(self):
        """Apply current filters and search to operations"""
        # Start with all operations
        filtered = self.operations

        # Apply type filter
        if self.current_filter != "all":
            if self.current_filter == "rename":
                # Rename e move_rename contêm renomeação
                filtered = [op for op in filtered if op.operation_type in ('rename', 'move_rename')]
            elif self.current_filter == "move":
                # Move e move_rename contêm movimentação
                filtered = [op for op in filtered if op.operation_type in ('move', 'move_rename')]
            else:
                filtered = [op for op in filtered if op.operation_type == self.current_filter]

        # Apply search filter
        if self.search_text:
            search_lower = self.search_text.lower()
            filtered = [
                op for op in filtered
                if search_lower in op.source.name.lower()
                or search_lower in op.destination.name.lower()
            ]

        self.filtered_operations = filtered
        self._update_display()

    def _update_display(self):
        """Update the display with filtered operations, grouped by video"""
        operations = self.filtered_operations

        # Disconnect handlers from previous rows before the old group is dropped,
        # so we don't leave stale connections holding references to `self`.
        for row, handler_id in self._row_handlers:
            try:
                row.disconnect(handler_id)
            except (TypeError, RuntimeError):
                # Row already destroyed by GTK — handler is gone too.
                pass
        self._row_handlers = []
        # As linhas antigas vão ser descartadas; esquece a seleção anterior.
        self._selected_row = None

        # Clear existing rows - rebuild the group instead of removing children
        # Remove old group from operations_box
        self.operations_box.remove(self.operations_group)

        # Create new operations group
        self.operations_group = Adw.PreferencesGroup()
        self.operations_group.set_visible(False)

        # Add new group to box
        self.operations_box.append(self.operations_group)

        if not operations:
            # Show empty state
            self.empty_state.set_visible(True)
            self.operations_group.set_visible(False)
            self.status_label.set_text("")
            return

        # Hide empty state, show operations
        self.empty_state.set_visible(False)
        self.operations_group.set_visible(True)

        # Separate videos from subtitles and other files
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.mpg', '.mpeg'}
        subtitle_exts = {'.srt', '.sub', '.ass', '.ssa', '.vtt'}
        
        videos = []
        subtitles = []
        others = []
        
        for op in operations:
            ext = op.source.suffix.lower()
            if ext in video_exts:
                videos.append(op)
            elif ext in subtitle_exts:
                subtitles.append(op)
            else:
                others.append(op)
        
        # Group subtitles with their videos by matching base name
        # Build a sorted list: video, then its subtitles, then next video, etc.
        grouped_operations = []
        used_subtitle_indices = set()  # Use indices since RenameOperation isn't hashable
        
        for video in videos:
            grouped_operations.append((video, False))  # (operation, is_subtitle)
            
            # Find matching subtitles (same base name without extension)
            video_stem = video.source.stem
            for idx, sub in enumerate(subtitles):
                if idx in used_subtitle_indices:
                    continue
                # Check if subtitle matches video (starts with video name)
                sub_stem = sub.source.stem
                # Remove language codes like .por, .eng from subtitle stem
                base_sub = sub_stem
                for lang in ['.por', '.eng', '.spa', '.fre', '.ger', '.ita', '.jpn', '.chi', '.kor']:
                    if base_sub.lower().endswith(lang):
                        base_sub = base_sub[:-4]
                        break
                
                if base_sub == video_stem or sub_stem.startswith(video_stem):
                    grouped_operations.append((sub, True))
                    used_subtitle_indices.add(idx)
        
        # Add remaining subtitles (not matched to videos)
        for idx, sub in enumerate(subtitles):
            if idx not in used_subtitle_indices:
                grouped_operations.append((sub, False))
        
        # Add other files at the end
        for other in others:
            grouped_operations.append((other, False))
        
        # Add operation rows in grouped order
        for i, (operation, is_subtitle) in enumerate(grouped_operations):
            row = OperationRow(operation, i, is_subtitle=is_subtitle)

            # Connect activation signal and track it for future disconnect.
            handler_id = row.connect("activated", self._on_row_activated)
            self._row_handlers.append((row, handler_id))

            self.operations_group.add(row)

        # Update status
        total_ops = len(self.operations)
        shown_ops = len(operations)

        rename_count = sum(1 for op in operations if op.operation_type == 'rename')
        move_count = sum(1 for op in operations if op.operation_type == 'move')
        delete_count = sum(1 for op in operations if op.operation_type == 'delete')

        status_parts = []
        if rename_count:
            status_parts.append(f"{rename_count} " + _("rename"))
        if move_count:
            status_parts.append(f"{move_count} " + _("move"))
        if delete_count:
            status_parts.append(f"{delete_count} " + _("delete"))

        if shown_ops < total_ops:
            status_text = _("Showing {} of {} operations").format(shown_ops, total_ops)
        else:
            status_text = _("Total: {} operations").format(total_ops)

        if status_parts:
            status_text += f" ({', '.join(status_parts)})"

        self.status_label.set_text(status_text)

    def _on_row_activated(self, row: OperationRow):
        """
        Handle row activation.

        Args:
            row: Activated row
        """
        # Remove o destaque da linha anterior antes de aplicar na nova.
        if self._selected_row is not None and self._selected_row is not row:
            try:
                self._selected_row.remove_css_class("row-selected")
            except (RuntimeError, TypeError):
                # Linha antiga já foi destruída pelo GTK
                pass
        row.add_css_class("row-selected")
        self._selected_row = row

        if self.on_operation_selected:
            self.on_operation_selected(row.operation, row.index)

    def _on_search_changed(self, entry: Gtk.SearchEntry):
        """
        Handle search text change.

        Args:
            entry: Search entry widget
        """
        self.search_text = entry.get_text()
        self._apply_filters()

    def _on_filter_changed(self, button: Gtk.ToggleButton, filter_type: str):
        """
        Handle filter button toggle.

        Args:
            button: Toggle button
            filter_type: Filter type (all, rename, move, delete)
        """
        if button.get_active():
            self.current_filter = filter_type
            self._apply_filters()

    def clear(self):
        """Clear all operations"""
        self.set_operations([])
