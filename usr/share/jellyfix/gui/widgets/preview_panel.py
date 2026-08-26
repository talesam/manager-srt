#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/widgets/preview_panel.py - Preview panel with operation details
#

"""
Preview panel for displaying operation details.

Shows:
  - Operation type (MOVE+RENAME, etc)
  - From: original file path
  - To: destination file path with TMDB ID
  - Poster image (when available)
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Pango
from pathlib import Path

from ...utils.i18n import _


class PreviewPanel(Gtk.Box):
    """Preview panel widget"""
    
    def __init__(self):
        """Initialize preview panel"""
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # Set expansion - CRITICAL for layout
        self.set_vexpand(True)
        self.set_hexpand(True)

        # Add CSS class
        self.add_css_class("preview-panel")

        # Build UI
        self._build_ui()
    
    def _build_ui(self):
        """Build preview panel UI"""
        # Scrolled window for content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Content box
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.set_spacing(16)
        self.content.set_margin_top(24)
        self.content.set_margin_bottom(24)
        self.content.set_margin_start(24)
        self.content.set_margin_end(24)
        self.content.set_vexpand(True)
        self.content.set_hexpand(True)
        
        # Empty state
        self.empty_state = Adw.StatusPage(
            icon_name="image-x-generic-symbolic",
            title=_("No Selection"),
            description=_("Select an item to preview")
        )
        self.empty_state.set_hexpand(True)
        self.empty_state.set_vexpand(True)
        self.content.append(self.empty_state)
        
        # Preview content (hidden initially)
        self.preview_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.preview_content.set_spacing(16)
        self.preview_content.set_visible(False)
        
        # Operation type header
        self.operation_type_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.operation_type_box.set_halign(Gtk.Align.CENTER)
        self.operation_type_box.set_spacing(8)
        
        self.operation_icon = Gtk.Image()
        self.operation_icon.set_pixel_size(24)
        self.operation_type_box.append(self.operation_icon)
        
        self.operation_type_label = Gtk.Label()
        self.operation_type_label.add_css_class("heading")
        self.operation_type_box.append(self.operation_type_label)
        
        self.preview_content.append(self.operation_type_box)
        
        # Poster image (optional, for movies)
        self.poster_image = Gtk.Picture()
        self.poster_image.set_size_request(200, 300)
        self.poster_image.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.poster_image.set_halign(Gtk.Align.CENTER)
        self.poster_image.set_visible(False)
        self.preview_content.append(self.poster_image)
        
        # Linha horizontal com os dois botões de ação (corrigir título + baixar legendas).
        # Antes ficavam empilhados verticalmente, ocupando espaço e parecendo desconexos.
        self.actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.actions_row.set_halign(Gtk.Align.CENTER)
        self.actions_row.set_spacing(8)
        self.actions_row.add_css_class("preview-actions")

        # Search title — cor warning (chama atenção: "talvez precise corrigir")
        self.search_button = Gtk.Button()
        search_content = Adw.ButtonContent()
        search_content.set_icon_name("system-search-symbolic")
        search_content.set_label(_("Search title"))
        self.search_button.set_child(search_content)
        self.search_button.add_css_class("preview-action-search")
        self.search_button.set_tooltip_text(_("Wrong title? Click to search manually"))
        self.search_button.connect("clicked", self._on_search_clicked)
        self.search_button.set_visible(False)
        self.actions_row.append(self.search_button)

        # Download subtitles — accent (ação positiva/principal)
        self.download_subs_button = Gtk.Button()
        subs_content = Adw.ButtonContent()
        subs_content.set_icon_name("media-view-subtitles-symbolic")
        subs_content.set_label(_("Download Subtitles"))
        self.download_subs_button.set_child(subs_content)
        self.download_subs_button.add_css_class("preview-action-subs")
        self.download_subs_button.set_tooltip_text(_("Search and download subtitles automatically"))
        self.download_subs_button.connect("clicked", self._on_download_subs_clicked)
        self.download_subs_button.set_visible(False)
        self.actions_row.append(self.download_subs_button)

        self.preview_content.append(self.actions_row)
        
        # Store current operation for search callback
        self.current_operation = None
        self.on_metadata_changed = None  # Callback when metadata is manually changed
        self.on_download_subs_clicked_callback = None # Callback for subtitle download
        
        # From/To card
        self.operation_card = Gtk.Frame()
        self.operation_card.add_css_class("card")
        self.operation_card.add_css_class("preview-card")
        
        card_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card_content.set_spacing(12)
        card_content.set_margin_top(16)
        card_content.set_margin_bottom(16)
        card_content.set_margin_start(16)
        card_content.set_margin_end(16)
        
        # From section
        from_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        from_box.set_spacing(4)
        
        from_header = Gtk.Label(label=_("From:"))
        from_header.add_css_class("dim-label")
        from_header.set_halign(Gtk.Align.START)
        from_box.append(from_header)
        
        self.from_path_label = Gtk.Label()
        self.from_path_label.set_halign(Gtk.Align.START)
        self.from_path_label.set_wrap(True)
        self.from_path_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.from_path_label.set_selectable(True)
        self.from_path_label.add_css_class("monospace")
        from_box.append(self.from_path_label)
        
        card_content.append(from_box)
        
        # Arrow separator
        arrow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        arrow_box.set_halign(Gtk.Align.CENTER)
        arrow_box.set_margin_top(4)
        arrow_box.set_margin_bottom(4)
        
        arrow_icon = Gtk.Image.new_from_icon_name("go-down-symbolic")
        arrow_icon.set_pixel_size(24)
        arrow_icon.add_css_class("dim-label")
        arrow_box.append(arrow_icon)
        
        card_content.append(arrow_box)
        
        # To section
        to_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        to_box.set_spacing(4)
        
        to_header = Gtk.Label(label=_("To:"))
        to_header.add_css_class("dim-label")
        to_header.set_halign(Gtk.Align.START)
        to_box.append(to_header)
        
        self.to_path_label = Gtk.Label()
        self.to_path_label.set_halign(Gtk.Align.START)
        self.to_path_label.set_wrap(True)
        self.to_path_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.to_path_label.set_selectable(True)
        self.to_path_label.add_css_class("monospace")
        self.to_path_label.add_css_class("success")
        to_box.append(self.to_path_label)
        
        card_content.append(to_box)
        
        self.operation_card.set_child(card_content)
        self.preview_content.append(self.operation_card)
        
        # Quality badge
        self.quality_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.quality_box.set_halign(Gtk.Align.CENTER)
        self.quality_box.set_spacing(8)
        self.quality_box.set_visible(False)
        
        self.quality_badge = Gtk.Label()
        self.quality_badge.add_css_class("badge")
        self.quality_box.append(self.quality_badge)
        
        self.preview_content.append(self.quality_box)
        
        self.content.append(self.preview_content)
        
        scrolled.set_child(self.content)
        self.append(scrolled)
    
    def load_poster(self, poster_path: Path):
        """
        Load and display poster image.
        
        Args:
            poster_path: Path to poster image
        """
        if poster_path and poster_path.exists():
            try:
                self.poster_image.set_filename(str(poster_path))
                self.poster_image.set_visible(True)
            except Exception as e:
                print(f"Error loading poster: {e}")
                self.poster_image.set_visible(False)
        else:
            self.poster_image.set_visible(False)
    
    def show_operation(self, operation):
        """
        Display operation details.
        
        Args:
            operation: RenameOperation instance
        """
        # Store current operation for search callback
        self.current_operation = operation

        # Descarta o poster do item anterior. Sem isso a capa antiga continuava
        # na tela enquanto a nova carregava — e ficava ali para sempre quando o
        # item novo não tinha capa (legenda, .nfo, exclusão), fazendo parecer
        # que o poster errado pertencia ao arquivo selecionado.
        self.poster_image.set_paintable(None)
        self.poster_image.set_visible(False)

        # Hide empty state, show content
        self.empty_state.set_visible(False)
        self.preview_content.set_visible(True)
        
        # Show search button for all operations except 'delete'
        op_type = getattr(operation, 'operation_type', 'rename')
        self.search_button.set_visible(op_type != 'delete')
        
        # Show download subs button for video files (all operations except 'delete')
        # Check extensions
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.mpg', '.mpeg'}
        is_video = operation.source.suffix.lower() in video_exts
        self.download_subs_button.set_visible(is_video and op_type != 'delete')

        # Set operation type
        op_type = getattr(operation, 'operation_type', 'rename')
        if op_type == 'move':
            self.operation_icon.set_from_icon_name("folder-symbolic")
            self.operation_type_label.set_text(_("MOVE"))
        elif op_type == 'delete':
            self.operation_icon.set_from_icon_name("user-trash-symbolic")
            self.operation_type_label.set_text(_("DELETE"))
        else:
            # Check if it's move+rename
            source_parent = operation.source.parent
            dest_parent = operation.destination.parent
            if source_parent != dest_parent:
                self.operation_icon.set_from_icon_name("document-edit-symbolic")
                self.operation_type_label.set_text(_("MOVE + RENAME"))
            else:
                self.operation_icon.set_from_icon_name("document-edit-symbolic")
                self.operation_type_label.set_text(_("RENAME"))
        
        # Set From path
        self.from_path_label.set_text(str(operation.source))
        
        # Set To path
        self.to_path_label.set_text(str(operation.destination))
        
        # Extract quality from filename if available
        filename = operation.destination.name
        quality = None
        for q in ['2160p', '1080p', '720p', '480p', '4K']:
            if q.lower() in filename.lower():
                quality = q
                break
        
        if quality:
            self.quality_badge.set_text(quality)
            self.quality_box.set_visible(True)
        else:
            self.quality_box.set_visible(False)
    
    def clear(self):
        """Clear preview and show empty state"""
        self.empty_state.set_visible(True)
        self.preview_content.set_visible(False)
        self.poster_image.set_visible(False)
        self.quality_box.set_visible(False)
        self.search_button.set_visible(False)
        self.download_subs_button.set_visible(False)
        self.current_operation = None
    
    def _on_search_clicked(self, button):
        """Handle search button click - open manual search dialog"""
        from ..windows.search_dialog import SearchDialog
        import re

        # Get parent window
        parent = self.get_root()

        # Detecta o tipo (filme vs série) a partir da operação atual:
        # se o destino planejado contiver "SxxExx" assumimos série; caso
        # contrário tratamos como filme.
        is_movie = True
        if self.current_operation is not None:
            dest_name = self.current_operation.destination.name
            if re.search(r'[Ss]\d{1,2}[Ee]\d{1,3}', dest_name):
                is_movie = False

        # Create and show dialog
        dialog = SearchDialog(
            parent=parent,
            is_movie=is_movie,
            on_select=self._on_metadata_selected
        )
        dialog.present(parent)
    
    def _on_metadata_selected(self, metadata):
        """Handle metadata selection from search dialog"""
        if self.on_metadata_changed and self.current_operation:
            self.on_metadata_changed(self.current_operation, metadata)
    
    def _on_download_subs_clicked(self, button):
        """Handle download subtitles button click"""
        if self.on_download_subs_clicked_callback and self.current_operation:
            self.on_download_subs_clicked_callback(self.current_operation)

    def set_metadata_callback(self, callback):
        """Set callback for when metadata is manually changed"""
        self.on_metadata_changed = callback

    def set_download_subs_callback(self, callback):
        """Set callback for download subtitles button"""
        self.on_download_subs_clicked_callback = callback

    # Legacy methods for compatibility
    def set_metadata(self, title: str, year: int = None,
                     original_title: str = None, overview: str = None,
                     quality: str = None):
        """Legacy method - kept for compatibility"""
        pass
