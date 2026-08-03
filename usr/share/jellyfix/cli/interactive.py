#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# cli/interactive.py - Interactive CLI mode with full menus
#

"""
Interactive CLI mode using questionary for menus.

This mode provides a user-friendly menu-driven interface
for scanning and organizing Jellyfin libraries.
"""

from pathlib import Path
from typing import Optional
import questionary
from questionary import Style

from ..core.scanner import LibraryScanner
from ..core.renamer import Renamer
from ..core.subtitle_manager import SubtitleManager
from ..utils.logger import get_logger
from ..utils.config_manager import ConfigManager
from ..utils.config import APP_VERSION
from ..utils.i18n import _
from .display import (
    console, show_banner, show_scan_results,
    show_operation_preview, show_execution_results,
    show_error, show_warning, show_success, show_info
)


# Custom style for menus
custom_style = Style([
    ('qmark', 'fg:#673ab7 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#4caf50 bold'),
    ('pointer', 'fg:#673ab7 bold'),
    ('highlighted', 'fg:#673ab7 bold'),
    ('selected', 'fg:#4caf50'),
    ('separator', 'fg:#cc5454'),
    ('instruction', ''),
    ('text', ''),
    ('checkbox', 'fg:#4caf50'),
    ('checkbox-selected', 'fg:#4caf50 bold'),
])


class InteractiveCLI:
    """Interactive CLI handler with menu-driven interface"""

    def __init__(self, config):
        """
        Initialize interactive CLI.

        Args:
            config: Configuration object
        """
        self.config = config
        self.logger = get_logger()
        self.config_manager = ConfigManager()

    def run(self):
        """Run interactive mode"""
        show_banner()

        while True:
            choice = self._main_menu()

            if not choice:
                break

            if choice == "scan":
                self._scan_library()
                console.clear()
                show_banner()
            elif choice == "process":
                self._process_files()
                console.clear()
                show_banner()
            elif choice == "subtitles":
                self._download_subtitles_menu()
                console.clear()
                show_banner()
            elif choice == "settings":
                self._settings_menu()
                console.clear()
                show_banner()
            elif choice == "help":
                self._show_help()
                console.clear()
                show_banner()
            elif choice == "exit":
                break

    def run_direct(self):
        """Run direct processing on the configured workdir (when --workdir is provided)"""
        workdir = Path(self.config.work_dir).resolve()

        if not workdir.exists() or not workdir.is_dir():
            show_error(_("Error: Directory does not exist: %s") % workdir)
            return 1

        show_banner()
        show_info(_("Scanning: %s") % workdir)

        # Scan
        scanner = LibraryScanner()
        result = scanner.scan(workdir)

        self.logger.info(
            _("Found: %d videos, %d subtitles") %
            (len(result.video_files), len(result.subtitle_files))
        )

        # Plan operations
        self.logger.info(_("Planning operations..."))
        renamer = Renamer()
        renamer.plan_operations(workdir, result)

        if len(renamer.operations) == 0:
            show_info(_("No operations needed. Everything is already organized!"))
            return 0

        # Show preview
        show_operation_preview(renamer, limit=50)

        if self.config.dry_run:
            show_warning(_("DRY-RUN mode: No changes will be made"))
            show_info(_("Use --execute to apply changes"))
            return 0

        # Ask for confirmation (unless --yes)
        if not self.config.auto_confirm:
            confirm = questionary.confirm(
                _("Execute these operations?"),
                default=False,
                style=custom_style
            ).ask()

            if not confirm:
                show_info(_("Operation cancelled"))
                return 0

        # Execute
        self.logger.info(_("Executing operations..."))
        stats = renamer.execute_operations(dry_run=False)

        # Show results
        show_execution_results(stats)
        return 0

    def _main_menu(self) -> Optional[str]:
        """
        Display main menu and get user choice.

        Returns:
            Menu choice or None if cancelled
        """
        choice = questionary.select(
            _("What would you like to do?"),
            choices=[
                questionary.Choice(_("📂 Scan library"), value="scan"),
                questionary.Choice(_("🔧 Settings"), value="settings"),
                questionary.Choice(_("🚀 Process files"), value="process"),
                questionary.Choice(_("📥 Download subtitles"), value="subtitles"),
                questionary.Choice(_("ℹ️  Help"), value="help"),
                questionary.Choice(_("❌ Exit"), value="exit")
            ],
            style=custom_style,
            instruction=_("(Use arrow keys to navigate)")
        ).ask()

        return choice

    def _download_subtitles_menu(self):
        """Download subtitles menu"""
        subtitle_manager = SubtitleManager()
        
        if not subtitle_manager.is_available():
            show_error(_("Subliminal library not found!"))
            console.print("[yellow]" + _("Please install 'subliminal' to use this feature.") + "[/yellow]")
            questionary.press_any_key_to_continue().ask()
            return

        # Select directory
        workdir = self._select_directory()
        if not workdir:
            return

        console.clear()
        show_info(_("Scanning for videos: %s") % workdir)

        # Scan
        scanner = LibraryScanner()
        result = scanner.scan(workdir)
        
        if not result.video_files:
            show_warning(_("No videos found!"))
            questionary.press_any_key_to_continue().ask()
            return

        # Create choices for video files
        choices = []
        for video in sorted(result.video_files):
            # Check if it already has subtitles (simplistic check)
            has_sub = any(s.stem.startswith(video.stem) for s in result.subtitle_files)
            status = "✓" if has_sub else "✗"
            
            choices.append(questionary.Choice(
                title=f"{status} {video.name}",
                value=video
            ))
            
        # Select videos
        selected_videos = questionary.checkbox(
            _("Select videos to download subtitles for:"),
            choices=choices,
            style=custom_style,
            instruction=_("(SPACE to select, ENTER to confirm)")
        ).ask()
        
        if not selected_videos:
            return
            
        # Confirm
        console.print(f"\n[bold]{_('Selected:')} {len(selected_videos)} {_('videos')}[/bold]")
        confirm = questionary.confirm(
            _("Start download?"),
            default=True,
            style=custom_style
        ).ask()
        
        if not confirm:
            return

        # Download using batch method (single provider connection for all videos)
        import rich.progress
        from ..core.detector import detect_media_type
        from ..utils.helpers import extract_year

        # Build metadata map for Level 2 fallback
        metadata_map = {}
        for video in selected_videos:
            media_info = detect_media_type(video)
            metadata_map[video] = {
                "title": media_info.title or video.stem,
                "year": media_info.year or extract_year(video.stem),
                "is_episode": media_info.is_tvshow(),
                "season": media_info.season,
                "episode": media_info.episode_start,
            }

        with rich.progress.Progress(
            rich.progress.SpinnerColumn(),
            rich.progress.TextColumn("[progress.description]{task.description}"),
            rich.progress.BarColumn(),
            rich.progress.TaskProgressColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(_("Downloading..."), total=len(selected_videos))

            def on_progress(vpath, idx, total):
                progress.update(task_id, description=_("Downloading for: {}").format(vpath.name))
                progress.update(task_id, completed=idx)

            batch_results = subtitle_manager.download_subtitles_batch(
                selected_videos,
                metadata_map=metadata_map,
                progress_callback=on_progress,
            )

            progress.update(task_id, completed=len(selected_videos))

        # Count results
        success_count = 0
        total_subs = 0
        for vpath, lang_map in batch_results.items():
            count = sum(len(paths) for paths in lang_map.values())
            total_subs += count
            if count > 0:
                success_count += 1

        # Show results
        if total_subs > 0:
            show_success(_("Downloaded {} subtitles for {} videos").format(total_subs, success_count))
        else:
            show_warning(_("No subtitles found"))

        questionary.press_any_key_to_continue().ask()

    def _scan_library(self):
        """Scan library and display results"""
        # Select directory
        workdir = self._select_directory()
        if not workdir:
            return

        console.clear()
        show_info(_("Scanning: %s") % workdir)

        # Scan
        scanner = LibraryScanner()
        result = scanner.scan(workdir)

        # Display results
        show_scan_results(result)

        # Wait for user
        questionary.press_any_key_to_continue().ask()

    def _process_files(self):
        """Process files: scan, plan, preview, execute"""
        # Select directory
        workdir = self._select_directory()
        if not workdir:
            return

        console.clear()
        show_info(_("Scanning: %s") % workdir)

        # Scan
        scanner = LibraryScanner()
        result = scanner.scan(workdir)

        self.logger.info(_("Found: %d videos, %d subtitles") % (len(result.video_files), len(result.subtitle_files)))

        # Plan operations
        self.logger.info(_("Planning operations..."))
        renamer = Renamer()
        renamer.plan_operations(workdir, result)

        if len(renamer.operations) == 0:
            show_warning(_("No operations needed"))
            questionary.press_any_key_to_continue().ask()
            return

        # Show preview
        show_operation_preview(renamer, limit=50)

        # Confirm
        confirm = questionary.confirm(_("Execute these operations?"), default=False, style=custom_style).ask()

        if not confirm:
            show_info(_("Operation cancelled"))
            return

        # Execute
        self.logger.info(_("Executing operations..."))
        stats = renamer.execute_operations(dry_run=False)

        # Show results
        show_execution_results(stats)

        questionary.press_any_key_to_continue().ask()

    def _select_directory(self, default: Optional[Path] = None) -> Optional[Path]:
        """
        Interactive directory selector.

        Args:
            default: Default starting directory

        Returns:
            Selected directory or None if cancelled
        """
        if default is None:
            # Use config work_dir instead of cwd
            default = self.config.work_dir if self.config.work_dir else Path.cwd()

        current_dir = default.resolve()

        while True:
            console.clear()
            console.print("\n[bold cyan]" + _("📂 Directory Browser") + "[/bold cyan]\n")
            console.print("[dim]" + _("Current:") + f"[/dim] [yellow]{current_dir}[/yellow]\n")

            # List directories
            try:
                choices = []

                # Add option to select current
                choices.append(questionary.Choice(_("✓ Select this directory"), value="__select__"))

                # Add parent option
                if current_dir.parent != current_dir:
                    choices.append(questionary.Choice(_("⬆️  .. (go back)"), value="__parent__"))

                # Add subdirectories
                dirs = sorted([d for d in current_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
                for d in dirs:
                    choices.append(questionary.Choice(f"📁 {d.name}", value=str(d)))

                # Add manual path entry
                choices.append(questionary.Choice(_("⌨️  Type path manually"), value="__manual__"))

                # Add cancel option
                choices.append(questionary.Choice(_("❌ Cancel"), value="__cancel__"))

                # Ask
                choice = questionary.select(_("Select directory:"), choices=choices, style=custom_style).ask()

                if not choice or choice == "__cancel__":
                    return None
                elif choice == "__select__":
                    return current_dir
                elif choice == "__parent__":
                    current_dir = current_dir.parent
                elif choice == "__manual__":
                    console.print("\n[cyan]" + _("Enter full directory path:") + "[/cyan]")
                    path_str = questionary.text(_("Path:"), default=str(current_dir), style=custom_style).ask()

                    if path_str:
                        new_path = Path(path_str).expanduser().resolve()
                        if new_path.exists() and new_path.is_dir():
                            return new_path
                        else:
                            show_error(_("Directory not found!"))
                            questionary.press_any_key_to_continue().ask()
                    continue
                else:
                    current_dir = Path(choice)

            except PermissionError:
                show_error(_("Permission denied"))
                questionary.press_any_key_to_continue().ask()
                current_dir = current_dir.parent

    def _settings_menu(self):
        """Complete settings configuration menu with sub-categories"""
        while True:
            console.clear()
            show_banner()
            console.print("\n[bold blue]⚙️  " + _("Settings") + "[/bold blue]\n")

            choice = questionary.select(
                _("What would you like to configure?"),
                choices=[
                    "📝 " + _("Subtitle Options"),
                    "🎬 " + _("Metadata Options"),
                    "📂 " + _("File Organization"),
                    "← " + _("Back"),
                ],
                style=custom_style,
                instruction=_("(Use ↑↓ and ENTER to select)"),
            ).ask()

            if not choice or _("Back") in choice:
                break
            elif _("Subtitle Options") in choice:
                self._subtitle_settings_menu()
            elif _("Metadata Options") in choice:
                self._metadata_settings_menu()
            elif _("File Organization") in choice:
                self._file_org_settings_menu()

    def _subtitle_settings_menu(self):
        """Subtitle-related settings"""
        while True:
            console.clear()
            show_banner()
            console.print("\n[bold blue]📝 " + _("Subtitle Options") + "[/bold blue]\n")

            kept_langs_str = ", ".join(self.config.kept_languages) if self.config.kept_languages else _("none")

            choice = questionary.select(
                _("Subtitle settings:"),
                choices=[
                    f"{'✓' if self.config.rename_por2 else '✗'} "
                    + _("Rename language variants (lang2→lang, lang3→lang)"),
                    f"{'✓' if self.config.remove_language_variants else '✗'} "
                    + _("Remove duplicate variants (lang2, lang3)"),
                    f"{'✓' if self.config.rename_no_lang else '✗'} " + _("Add language code to subtitles"),
                    f"{'✓' if self.config.remove_foreign_subs else '✗'} " + _("Remove foreign subtitles"),
                    "🌍 " + _("Kept languages:") + f" {kept_langs_str}",
                    f"{'✓' if self.config.fix_mirabel_files else '✗'} " + _("Fix Mirabel files (.pt-BR.hi → .por)"),
                    "📊 " + _("Min Portuguese words:") + f" {self.config.min_pt_words}",
                    "← " + _("Back"),
                ],
                style=custom_style,
                instruction=_("(Use ↑↓ and ENTER to select)"),
            ).ask()

            if not choice or _("Back") in choice:
                break
            elif _("Rename language variants") in choice:
                self.config.rename_por2 = not self.config.rename_por2
                self.config_manager.set("rename_por2", self.config.rename_por2)
                show_success(_("Setting saved"))
            elif _("Remove duplicate variants") in choice:
                self.config.remove_language_variants = not self.config.remove_language_variants
                self.config_manager.set("remove_language_variants", self.config.remove_language_variants)
                show_success(_("Setting saved"))
            elif _("Add language code") in choice:
                self.config.rename_no_lang = not self.config.rename_no_lang
                self.config_manager.set("rename_no_lang", self.config.rename_no_lang)
                show_success(_("Setting saved"))
            elif _("Remove foreign") in choice:
                self.config.remove_foreign_subs = not self.config.remove_foreign_subs
                self.config_manager.set("remove_foreign_subs", self.config.remove_foreign_subs)
                show_success(_("Setting saved"))
            elif _("Kept languages") in choice:
                self._language_selection_menu()
            elif _("Fix Mirabel files") in choice:
                self.config.fix_mirabel_files = not self.config.fix_mirabel_files
                self.config_manager.set("fix_mirabel_files", self.config.fix_mirabel_files)
                show_success(_("Setting saved"))
            elif _("Min Portuguese words") in choice:
                new_value = questionary.text(
                    _("Minimum number of Portuguese words:"), default=str(self.config.min_pt_words), style=custom_style
                ).ask()
                try:
                    value = int(new_value)
                    self.config.min_pt_words = value
                    self.config_manager.set("min_pt_words", value)
                    show_success(_("Setting saved to ~/.jellyfix/config.json"))
                except ValueError:
                    show_error(_("Invalid value!"))
                questionary.press_any_key_to_continue().ask()

    def _metadata_settings_menu(self):
        """Metadata and API settings"""
        while True:
            console.clear()
            show_banner()
            console.print("\n[bold blue]🎬 " + _("Metadata Options") + "[/bold blue]\n")

            choice = questionary.select(
                _("Metadata settings:"),
                choices=[
                    f"{'✓' if self.config.fetch_metadata else '✗'} " + _("Fetch metadata (TMDB/TVDB)"),
                    f"{'✓' if self.config.ask_on_multiple_results else '✗'} " + _("Ask when multiple TMDB results"),
                    "🔑 " + _("Configure APIs (TMDB/TVDB)"),
                    "← " + _("Back"),
                ],
                style=custom_style,
                instruction=_("(Use ↑↓ and ENTER to select)"),
            ).ask()

            if not choice or _("Back") in choice:
                break
            elif _("Fetch metadata") in choice:
                self.config.fetch_metadata = not self.config.fetch_metadata
                self.config_manager.set("fetch_metadata", self.config.fetch_metadata)
                show_success(_("Setting saved"))
            elif _("Ask when multiple TMDB results") in choice:
                self.config.ask_on_multiple_results = not self.config.ask_on_multiple_results
                self.config_manager.set("ask_on_multiple_results", self.config.ask_on_multiple_results)
                show_success(_("Setting saved"))
            elif _("Configure APIs") in choice:
                self._api_settings_menu()

    def _file_org_settings_menu(self):
        """File organization settings"""
        while True:
            console.clear()
            show_banner()
            console.print("\n[bold blue]📂 " + _("File Organization") + "[/bold blue]\n")

            choice = questionary.select(
                _("File organization settings:"),
                choices=[
                    f"{'✓' if self.config.organize_folders else '✗'} " + _("Organize in folders (Season XX)"),
                    f"{'✓' if self.config.add_quality_tag else '✗'} " + _("Add quality tags (1080p, 720p, etc)"),
                    f"{'✓' if self.config.use_ffprobe else '✗'} " + _("Use ffprobe for quality detection"),
                    f"{'✓' if self.config.rename_nfo else '✗'} " + _("Rename NFO files to match video"),
                    f"{'✓' if self.config.remove_non_media else '✗'} "
                    + _("Remove non-media files (keep only videos/subtitles)"),
                    "← " + _("Back"),
                ],
                style=custom_style,
                instruction=_("(Use ↑↓ and ENTER to select)"),
            ).ask()

            if not choice or _("Back") in choice:
                break
            elif _("Organize in folders") in choice:
                self.config.organize_folders = not self.config.organize_folders
                self.config_manager.set("organize_folders", self.config.organize_folders)
                show_success(_("Setting saved"))
            elif _("Add quality tags") in choice:
                self.config.add_quality_tag = not self.config.add_quality_tag
                self.config_manager.set("add_quality_tag", self.config.add_quality_tag)
                show_success(_("Setting saved"))
            elif _("Use ffprobe for quality detection") in choice:
                self.config.use_ffprobe = not self.config.use_ffprobe
                self.config_manager.set("use_ffprobe", self.config.use_ffprobe)
                show_success(_("Setting saved"))
            elif _("Rename NFO files to match video") in choice:
                self.config.rename_nfo = not self.config.rename_nfo
                self.config_manager.set("rename_nfo", self.config.rename_nfo)
                show_success(_("Setting saved"))
            elif _("Remove non-media files") in choice:
                self.config.remove_non_media = not self.config.remove_non_media
                self.config_manager.set("remove_non_media", self.config.remove_non_media)
                show_success(_("Setting saved"))

    def _language_selection_menu(self):
        """Language selection menu with checkbox"""
        console.clear()
        show_banner()
        console.print("\n[bold blue]🌍 " + _("Language Selection") + "[/bold blue]\n")
        console.print("[dim]" + _("Select languages to KEEP (will NOT be removed)") + "[/dim]")
        console.print("[dim]" + _("Use SPACE to check/uncheck, ENTER to confirm") + "[/dim]\n")

        # Create choices sorted alphabetically by language name
        choices = []
        for code, name in sorted(self.config.all_languages.items(), key=lambda x: x[1]):
            display_name = f"{name} ({code})"
            choices.append(questionary.Choice(
                title=display_name,
                value=code,
                checked=(code in self.config.kept_languages)
            ))

        selected = questionary.checkbox(
            _("Select languages to KEEP:"),
            choices=choices,
            style=custom_style,
            instruction=_("(SPACE = check/uncheck, ENTER = confirm)")
        ).ask()

        if selected is not None:
            self.config.kept_languages = selected
            console.print("\n[green]✓ " + _("Kept languages:") + f" {', '.join(selected)}[/green]")

            # Save to config file
            self.config_manager.set('kept_languages', selected)
            show_success(_("Saved to ~/.jellyfix/config.json"))

        questionary.press_any_key_to_continue().ask()

    def _api_settings_menu(self):
        """API configuration menu"""
        while True:
            console.clear()
            show_banner()
            console.print("\n[bold magenta]🔑 " + _("API Configuration") + "[/bold magenta]\n")

            # Show current status
            tmdb_key = self.config_manager.get_tmdb_api_key()
            tmdb_status = "[green]✓ " + _("Configured") + "[/green]" if tmdb_key else "[red]✗ " + _("Not configured") + "[/red]"

            os_accounts = self.config_manager.get_opensubtitles_accounts()
            os_users = ", ".join(account['username'] for account in os_accounts)
            os_status = ("[green]✓ " + _("Configured") + f" ({os_users})[/green]"
                         if os_accounts else "[red]✗ " + _("Not configured") + "[/red]")

            console.print(f"[bold]TMDB API Key:[/bold] {tmdb_status}")
            console.print(f"[bold]OpenSubtitles:[/bold] {os_status}")
            console.print("[bold]" + _("Config file:") + f"[/bold] [cyan]{self.config_manager.get_config_path()}[/cyan]\n")

            choice = questionary.select(
                _("What would you like to do?"),
                choices=[
                    "🔑 " + _("Configure TMDB API Key"),
                    "📋 " + _("View current key (TMDB)"),
                    "✓ " + _("Test TMDB connection"),
                    "🗑️  " + _("Remove TMDB key"),
                    "ℹ️  " + _("How to get TMDB key"),
                    "🎬 " + _("Add OpenSubtitles account"),
                    "🔌 " + _("Test OpenSubtitles accounts"),
                    "🗑️  " + _("Remove OpenSubtitles accounts"),
                    "← " + _("Back")
                ],
                style=custom_style,
                instruction=_("(Use ↑↓ and ENTER to select)")
            ).ask()

            if not choice or _("Back") in choice:
                break

            elif _("Add OpenSubtitles account") in choice:
                self._configure_opensubtitles_login()

            elif _("Test OpenSubtitles accounts") in choice:
                self._test_opensubtitles_login()

            elif _("Remove OpenSubtitles accounts") in choice:
                confirm = questionary.confirm(
                    _("Remove all stored OpenSubtitles accounts?"),
                    default=False,
                    style=custom_style
                ).ask()
                if confirm:
                    self.config_manager.remove_opensubtitles_credentials()
                    self.config.opensubtitles_accounts = []
                    self.config.opensubtitles_username = ""
                    self.config.opensubtitles_password = ""
                    show_success(_("OpenSubtitles accounts removed"))
                else:
                    show_warning(_("Operation cancelled"))
                questionary.press_any_key_to_continue().ask()

            elif _("Configure TMDB API Key") in choice:
                console.print("\n[cyan]" + _("Enter your TMDB API key:") + "[/cyan]")
                api_key = questionary.text(
                    "TMDB API Key:",
                    style=custom_style
                ).ask()

                if api_key and api_key.strip():
                    self.config_manager.set_tmdb_api_key(api_key.strip())
                    self.config.tmdb_api_key = api_key.strip()
                    console.print("\n[green]✓ " + _("TMDB key saved to:") + "[/green]")
                    console.print(f"  [cyan]{self.config_manager.get_config_path()}[/cyan]")
                else:
                    show_warning(_("Operation cancelled"))

                questionary.press_any_key_to_continue().ask()

            elif _("View current key (TMDB)") in choice:
                key = self.config_manager.get_tmdb_api_key()
                if key:
                    # Show only first and last 4 characters
                    masked_key = f"{key[:4]}..." if len(key) > 4 else "***"
                    console.print(f"\n[cyan]TMDB Key:[/cyan] {masked_key}")
                    console.print("\n[dim]" + _("File:") + f"[/dim] [cyan]{self.config_manager.get_config_path()}[/cyan]")
                else:
                    show_warning(_("No key configured"))

                questionary.press_any_key_to_continue().ask()

            elif _("Remove TMDB key") in choice:
                confirm = questionary.confirm(
                    _("Are you sure you want to remove the TMDB key?"),
                    default=False,
                    style=custom_style
                ).ask()

                if confirm:
                    self.config_manager.set_tmdb_api_key("")
                    self.config.tmdb_api_key = ""
                    show_success(_("TMDB key removed"))
                else:
                    show_warning(_("Operation cancelled"))

                questionary.press_any_key_to_continue().ask()

            elif _("Test TMDB connection") in choice:
                self._test_tmdb_connection()

            elif _("How to get TMDB key") in choice:
                self._show_tmdb_help()

    def _configure_opensubtitles_login(self):
        """Prompt for and add opensubtitles.com credentials."""
        console.print("\n[cyan]" + _("Add an OpenSubtitles account.") + "[/cyan]")
        console.print("[dim]" + _("Create a free account at https://www.opensubtitles.com/newuser") + "[/dim]")
        console.print("[yellow]⚠ " + _("Use your USERNAME, not your e-mail address.") + "[/yellow]\n")

        username = questionary.text(_("Username (not e-mail):"), style=custom_style).ask()
        if username is None:
            return
        password = questionary.password(_("Password:"), style=custom_style).ask()
        if password is None:
            return

        username = username.strip()
        if username and password:
            self.config_manager.set_opensubtitles_credentials(username, password)
            accounts = self.config_manager.get_opensubtitles_accounts()
            self.config.opensubtitles_accounts = accounts
            self.config.opensubtitles_username = accounts[0]['username']
            self.config.opensubtitles_password = accounts[0]['password']
            show_success(_("OpenSubtitles account saved"))
        else:
            show_warning(_("Username and password are both required"))

        questionary.press_any_key_to_continue().ask()

    def _test_opensubtitles_login(self):
        """Log in to every opensubtitles.com account to verify it."""
        console.clear()
        show_banner()
        console.print("\n[bold cyan]🔌 " + _("Testing OpenSubtitles accounts...") + "[/bold cyan]\n")

        accounts = self.config_manager.get_opensubtitles_accounts()
        if not accounts:
            show_error(_("No OpenSubtitles account configured!"))
            console.print("\n[yellow]" + _("Add an OpenSubtitles account first") + "[/yellow]")
            questionary.press_any_key_to_continue().ask()
            return

        from ..core.subtitle_manager import SubtitleManager
        manager = SubtitleManager()
        for account in accounts:
            ok, message = manager.test_opensubtitles_login(
                account['username'], account['password']
            )
            if ok:
                show_success(message + f" ({account['username']})")
            else:
                show_error(
                    _("Account test failed: %(user)s: %(message)s")
                    % {'user': account['username'], 'message': message}
                )

        questionary.press_any_key_to_continue().ask()

    def _test_tmdb_connection(self):
        """Test TMDB API connection"""
        console.clear()
        show_banner()
        console.print("\n[bold cyan]🔍 " + _("Testing TMDB connection...") + "[/bold cyan]\n")

        api_key = self.config_manager.get_tmdb_api_key()

        if not api_key:
            show_error(_("No API key configured!"))
            console.print("\n[yellow]" + _("Configure a key first using 'Configure TMDB API Key'") + "[/yellow]")
            questionary.press_any_key_to_continue().ask()
            return

        # Validate key format
        if len(api_key) != 32:
            show_error(_("Invalid key! Has %d characters, should have 32.") % len(api_key))
            console.print("\n[yellow]⚠️  " + _("You may have copied the Token instead of the API Key!") + "[/yellow]")
            console.print("[dim]" + _("See 'How to get TMDB key' for details") + "[/dim]")
            questionary.press_any_key_to_continue().ask()
            return

        try:
            import requests

            # Test with a simple search
            console.print("[cyan]" + _("Making test request...") + "[/cyan]")
            url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query=Matrix"

            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                total_results = data.get('total_results', 0)

                show_success(_("Connection successful!"))
                console.print("[green]• " + _("Valid and working API key") + "[/green]")
                console.print("[green]• " + _("Test search returned %d results") % total_results + "[/green]")

                if total_results > 0:
                    first_movie = data['results'][0]
                    console.print("\n[dim]" + _("Example:") + f" {first_movie.get('title')} ({first_movie.get('release_date', 'N/A')[:4]})[/dim]")

            elif response.status_code == 401:
                show_error(_("Invalid API key!"))
                console.print("[yellow]" + _("The key was rejected by TMDB.") + "[/yellow]")
                console.print("\n[bold]" + _("Possible causes:") + "[/bold]")
                console.print("1. " + _("You copied the Reading Token instead of the API Key"))
                console.print("2. " + _("The key is incorrect or has been revoked"))
                console.print("3. " + _("You copied only part of the key"))
                console.print("\n[cyan]" + _("See 'How to get TMDB key' for detailed instructions") + "[/cyan]")

            else:
                show_error(_("Request error: HTTP %d") % response.status_code)

        except requests.exceptions.Timeout:
            show_error(_("Timeout: Server did not respond in time"))
            console.print("[yellow]" + _("Check your internet connection") + "[/yellow]")

        except requests.exceptions.ConnectionError:
            show_error(_("Connection error"))
            console.print("[yellow]" + _("Check your internet connection") + "[/yellow]")

        except Exception as e:
            show_error(_("Unexpected error: %s") % e)

        questionary.press_any_key_to_continue().ask()

    def _show_tmdb_help(self):
        """Show TMDB API key help"""
        console.clear()
        show_banner()
        help_text = f"""[bold cyan]📖 {_("How to Get TMDB API Key")}[/bold cyan]

[bold]1. {_("Access:")}[/bold]
   [link=https://www.themoviedb.org/settings/api]https://www.themoviedb.org/settings/api[/link]

[bold]2. {_("Login or create a FREE account")}[/bold]
   • https://www.themoviedb.org/signup
   • {_("Fill in your details")}
   • {_("Confirm email")}

[bold]3. {_("Request an API key:")}[/bold]
   • {_("Access")}: https://www.themoviedb.org/settings/api
   • {_("Click 'Request an API Key'")}
   • {_("Choose 'Developer' (personal use)")}
   • {_("Fill in")}:
     - Application Name: Jellyfix
     - Application URL: http://localhost
     - Application Summary: Personal media organizer
   • {_("Accept terms of use")}

[bold red]⚠️  {_("IMPORTANT - Which key to copy:")}[/bold red]
   {_("You will see TWO keys on the page:")}
   [dim]• {_("API Read Access Token (long, starts with eyJ...)")}[/dim]
   [bold green]• {_("API Key (v3 auth) ← COPY THIS ONE!")}[/bold green]

   {_("The correct key has 32 characters (ex: 611bc23b57add08a67b2e64ecb850be8)")}

[bold]4. {_("Configure in jellyfix:")}[/bold]
   • {_("Return to menu and choose 'Configure TMDB API Key'")}
   • {_("Paste the API Key (32 characters)")}
   • {_("Use 'Test connection' to verify")}

[green]✓ {_("The key is free and does not expire!")}[/green]
[green]✓ {_("Allows up to 40 requests per 10 seconds")}[/green]
[green]✓ {_("Enough to organize thousands of files!")}[/green]
"""
        from rich.panel import Panel
        console.print(Panel(help_text, title=_("How to Get TMDB Key"), border_style="cyan", expand=False))
        questionary.press_any_key_to_continue().ask()

    def _show_help(self):
        """Show complete help information"""
        console.clear()
        show_banner()
        help_text = f"""[bold cyan]📖 {_("Help - jellyfix v")} {APP_VERSION}[/bold cyan]

[bold]{_("What jellyfix does:")}[/bold]

• [green]{_("Renames files")}[/green] {_("to Jellyfin standard")}
  - {_("Movies")}: [dim]{_("Movie Name (YYYY).mkv")}[/dim]
  - {_("Series")}: [dim]{_("Series Name - S01E01.mkv")}[/dim]

• [green]{_("Organizes subtitles")}[/green] {_("(ALL languages)")}
  - {_("Renames variants")}: por2→por, eng2→eng, spa3→spa
  - {_("Adds language code")} (.por.srt)
  - {_("Removes foreign subtitles")} ({_("keeps por and eng by default")})
  - {_("Option to remove duplicates")} (eng2, eng3 {_("when eng exists")})
  - [yellow]{_("NEVER")}[/yellow] {_("removes .forced.srt")}

• [green]{_("Folder structure")}[/green]
  - {_("Creates folders Season 01, Season 02, etc")}
  - {_("Moves episodes to correct folders")}

• [green]{_("Fetches metadata")}[/green]
  - {_("Searches year and IDs via TMDB/TVDB")}
  - {_("Adds IDs to folders [tmdbid-12345]")}

• [green]{_("Quality detection")}[/green]
  - {_("Adds quality tags (1080p, 720p, etc) to filenames")}
  - {_("Option to use ffprobe for accurate detection")}

[bold yellow]{_("Dry-Run Mode:")}[/bold yellow]
{_("By default, jellyfix shows what will be done WITHOUT changing files.")}
{_("You can review changes before applying.")}

[bold cyan]{_("Tip:")}[/bold cyan] {_("Configure your TMDB key")}:
[dim]Settings → Configure APIs → Configure TMDB API Key[/dim]
"""
        from rich.panel import Panel
        console.print(Panel(help_text, border_style="cyan", expand=False))
        questionary.press_any_key_to_continue().ask()
