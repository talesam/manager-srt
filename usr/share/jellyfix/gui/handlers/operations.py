#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/handlers/operations.py - Operations handlers for GUI
#

"""
Operations handlers for GUI interactions.

Connects GUI widgets to core business logic:
  - Directory selection
  - File scanning
  - Operation generation
  - Metadata fetching
  - Poster downloading
  - Operation execution
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib
from pathlib import Path
from typing import Optional, List, Callable

from ...core.scanner import scan_library
from ...core.renamer import Renamer
from ...core.metadata import MetadataFetcher
from ...core.image_manager import ImageManager
from ...utils.logger import get_logger
from ...utils.config import get_config
from ...utils.i18n import _


class OperationsHandler:
    """Handler for GUI operations"""

    def __init__(self, window: Adw.ApplicationWindow):
        """
        Initialize operations handler.

        Args:
            window: Main application window
        """
        self.window = window
        self.logger = get_logger()
        self.config = get_config()
        self.metadata_fetcher = None
        self.image_manager = None
        self.current_directory: Optional[Path] = None
        self.scanned_files: List[Path] = []
        self.operations: List = []

        # Initialize metadata fetcher if enabled
        if self.config.fetch_metadata:
            self.metadata_fetcher = MetadataFetcher()
            self.image_manager = ImageManager()

    def select_directory(self, callback: Optional[Callable] = None):
        """
        Open directory chooser dialog.

        Args:
            callback: Optional callback to run after selection
        """
        from ...utils.config_manager import ConfigManager
        from gi.repository import Gio
        
        config_manager = ConfigManager()
        
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select Directory to Scan"))
        dialog.set_modal(True)
        
        # Set initial folder to last opened directory
        last_dir = config_manager.get_last_directory()
        if last_dir and Path(last_dir).exists():
            initial_folder = Gio.File.new_for_path(last_dir)
            dialog.set_initial_folder(initial_folder)

        def on_response(dialog, result):
            try:
                folder = dialog.select_folder_finish(result)
                if folder:
                    self.current_directory = Path(folder.get_path())
                    self.logger.info(f"Selected directory: {self.current_directory}")
                    
                    # Save as last directory
                    config_manager.set_last_directory(str(self.current_directory))

                    if callback:
                        callback(self.current_directory)
            except Exception as e:
                if "dismissed" not in str(e).lower():
                    self.logger.error(f"Error selecting directory: {e}")

        dialog.select_folder(self.window, None, on_response)

    def scan_directory(self, directory: Optional[Path] = None,
                      progress_callback: Optional[Callable] = None,
                      complete_callback: Optional[Callable] = None):
        """
        Scan directory for media files.

        Args:
            directory: Directory to scan (uses current_directory if None)
            progress_callback: Called during scan with progress info
            complete_callback: Called when scan completes with ScanResult
        """
        scan_dir = directory or self.current_directory

        if not scan_dir:
            self.logger.error("No directory selected")
            return

        self.logger.info(f"Scanning directory: {scan_dir}")

        def scan_task():
            """Background scan task"""
            try:
                # Scan directory
                scan_result = scan_library(scan_dir)

                # Extract all files from scan result
                all_files = (
                    scan_result.video_files +
                    scan_result.subtitle_files +
                    scan_result.image_files
                )
                self.scanned_files = all_files

                # Update UI on main thread
                GLib.idle_add(self._on_scan_complete, scan_result, complete_callback)

            except Exception as e:
                self.logger.error(f"Scan failed: {e}")
                import traceback
                traceback.print_exc()
                GLib.idle_add(self._on_scan_error, str(e))

        # Run scan in background thread
        import threading
        thread = threading.Thread(target=scan_task, daemon=True)
        thread.start()

    def _on_scan_complete(self, scan_result, callback: Optional[Callable] = None):
        """
        Handle scan completion.

        Args:
            scan_result: ScanResult object from scan
            callback: Optional callback to run
        """
        # Get total files from ScanResult
        total_files = getattr(scan_result, 'total_files', 0)
        self.logger.success(f"Scan complete: {total_files} files found")

        if callback:
            callback(scan_result)

        return False  # Remove from GLib idle queue

    def _on_scan_error(self, error: str):
        """
        Handle scan error.

        Args:
            error: Error message
        """
        # Show error dialog
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=_("Scan Failed"),
            body=error
        )
        dialog.add_response("ok", _("OK"))
        dialog.present()

        return False  # Remove from GLib idle queue

    def generate_operations(self, files: Optional[List[Path]] = None,
                           scan_result=None,
                           complete_callback: Optional[Callable] = None):
        """
        Generate rename operations from scanned files.

        Args:
            files: Deprecated, use scan_result instead
            scan_result: ScanResult from scan (if provided, uses filtered files)
            complete_callback: Called when complete with operations list
        """
        if not self.current_directory:
            self.logger.error("No directory selected")
            return

        self.logger.info(f"Generating operations for directory: {self.current_directory}")
        if scan_result:
            print(f"DEBUG: generate_operations received scan_result with {len(scan_result.video_files)} videos")

        def generate_task():
            """Background operation generation task"""
            try:
                # Create renamer and plan operations
                # Passa o metadata_fetcher para o Renamer para compartilhar o cache de escolhas
                renamer = Renamer(metadata_fetcher=self.metadata_fetcher)
                operations = renamer.plan_operations(self.current_directory, scan_result=scan_result)
                self.operations = operations

                # Update UI on main thread
                GLib.idle_add(self._on_operations_complete, operations, complete_callback)

            except Exception as e:
                self.logger.error(f"Operation generation failed: {e}")
                import traceback
                traceback.print_exc()
                GLib.idle_add(self._on_operations_error, str(e))

        # Run in background thread
        import threading
        thread = threading.Thread(target=generate_task, daemon=True)
        thread.start()

    def _on_operations_complete(self, operations: List, callback: Optional[Callable] = None):
        """
        Handle operations generation completion.

        Args:
            operations: List of generated operations
            callback: Optional callback to run
        """
        self.logger.success(f"Generated {len(operations)} operations")

        if callback:
            callback(operations)

        return False  # Remove from GLib idle queue

    def _on_operations_error(self, error: str):
        """
        Handle operations error.

        Args:
            error: Error message
        """
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=_("Operation Generation Failed"),
            body=error
        )
        dialog.add_response("ok", _("OK"))
        dialog.present()

        return False  # Remove from GLib idle queue

    def download_poster(self, metadata, callback: Optional[Callable] = None):
        """
        Download poster for metadata.

        Args:
            metadata: Metadata object with poster info
            callback: Called when download completes with poster path
        """
        if not self.image_manager or not metadata:
            if callback:
                callback(None)
            return

        def download_task():
            """Background download task"""
            try:
                poster_path = self.image_manager.download_poster(metadata, size='medium')

                # Update UI on main thread
                GLib.idle_add(self._on_poster_downloaded, poster_path, callback)

            except Exception as e:
                self.logger.error(f"Poster download failed: {e}")
                GLib.idle_add(self._on_poster_downloaded, None, callback)

        # Run in background thread
        import threading
        thread = threading.Thread(target=download_task, daemon=True)
        thread.start()

    def _on_poster_downloaded(self, poster_path: Optional[Path],
                             callback: Optional[Callable] = None):
        """
        Handle poster download completion.

        Args:
            poster_path: Path to downloaded poster (or None if failed)
            callback: Optional callback to run
        """
        if poster_path:
            self.logger.debug(f"Poster downloaded: {poster_path}")
        else:
            self.logger.debug("No poster available")

        if callback:
            callback(poster_path)

        return False  # Remove from GLib idle queue

    def execute_operations(self, operations: Optional[List] = None,
                          progress_callback: Optional[Callable] = None,
                          complete_callback: Optional[Callable] = None):
        """
        Execute rename operations.

        Args:
            operations: Operations to execute (uses self.operations if None)
            progress_callback: Called for each operation with progress
            complete_callback: Called when all operations complete
        """
        ops = operations or self.operations

        if not ops:
            self.logger.error("No operations to execute")
            return

        # Check if in dry-run mode
        if self.config.dry_run:
            self.logger.warning("Dry-run mode: operations will not be executed")
            if complete_callback:
                complete_callback(ops, dry_run=True)
            return

        self.logger.info(f"Executing {len(ops)} operations")

        def execute_task():
            """Background execution task"""
            try:
                # Reuse the CLI executor instead of a second, weaker copy.
                # The old inline loop called shutil.move() directly, without the
                # will_overwrite check — two operations pointing at the same
                # destination silently DESTROYED the first file. It also had no
                # rollback, and its folder cleanup could climb above the
                # working directory.
                renamer = Renamer(metadata_fetcher=self.metadata_fetcher)
                renamer.operations = list(ops)
                renamer.work_dir = (
                    Path(self.current_directory).resolve()
                    if self.current_directory
                    else None
                )

                if progress_callback:
                    GLib.idle_add(progress_callback, 0, len(ops))

                stats = renamer.execute_operations(dry_run=False)

                results = [
                    op for op in ops
                    if getattr(op, 'operation_type', '') != 'delete'
                ]
                if stats.get('failed'):
                    self.logger.warning(f"{stats['failed']} operations failed")
                if stats.get('skipped'):
                    self.logger.warning(
                        f"{stats['skipped']} operations skipped (destination already exists)"
                    )

                if progress_callback:
                    GLib.idle_add(progress_callback, len(ops), len(ops))

                # Update UI on main thread
                GLib.idle_add(self._on_execution_complete, results, complete_callback)

            except Exception as e:
                self.logger.error(f"Execution failed: {e}")
                import traceback
                traceback.print_exc()
                GLib.idle_add(self._on_execution_error, str(e))

        # Run in background thread
        import threading
        thread = threading.Thread(target=execute_task, daemon=True)
        thread.start()

    def _on_execution_complete(self, results: List, callback: Optional[Callable] = None):
        """
        Handle execution completion.

        Args:
            results: Execution results
            callback: Optional callback to run
        """
        self.logger.success(f"Execution complete: {len(results)} operations")

        if callback:
            callback(results)

        return False  # Remove from GLib idle queue

    def _on_execution_error(self, error: str):
        """
        Handle execution error.

        Args:
            error: Error message
        """
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=_("Execution Failed"),
            body=error
        )
        dialog.add_response("ok", _("OK"))
        dialog.present()

        return False  # Remove from GLib idle queue
