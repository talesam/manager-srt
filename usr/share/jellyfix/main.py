#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# main.py - Entry point for Jellyfix CLI
#

"""
Jellyfix - Intelligent Jellyfin Library Organizer

Automatically renames and organizes movies, TV shows, and subtitles
following Jellyfin naming conventions.
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from jellyfix.utils.config import Config, set_config, APP_VERSION
from jellyfix.cli import run_cli
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.box import DOUBLE


def show_help():
    """Display colorful and detailed help using Rich"""
    console = Console()

    # Title banner — let Rich draw the box so the borders stay aligned
    # regardless of how the terminal renders the emoji widths.
    console.print()
    title = Text()
    title.append("🎬  JELLYFIX  🎬\n", style="bold magenta")
    title.append("Intelligent Jellyfin Library Organizer\n", style="cyan")
    title.append(f"v{APP_VERSION}", style="dim")
    title.justify = "center"
    console.print(Panel(title, box=DOUBLE, style="bold blue", width=60, padding=(0, 1)))
    console.print()

    # Usage
    console.print("[bold cyan]USAGE[/bold cyan]")
    console.print("  [yellow]jellyfix[/yellow] [OPTIONS]")
    console.print("  [yellow]jellyfix[/yellow] [dim]--help[/dim]     # Show this help")
    console.print("  [yellow]jellyfix[/yellow] [dim]--version[/dim]  # Show version")
    console.print()

    # Description
    console.print("[bold cyan]DESCRIPTION[/bold cyan]")
    console.print("  Automatically organizes your Jellyfin media library:")
    console.print("    • Renames files to Jellyfin standard")
    console.print("    • Organizes episodes into Season folders")
    console.print("    • Manages subtitles (renames, removes foreign, adds language codes)")
    console.print("    • Fetches metadata from TMDB/TVDB")
    console.print("    • Detects and adds quality tags (1080p, 720p, etc)")
    console.print()

    # General Options
    console.print("[bold cyan]GENERAL OPTIONS[/bold cyan]")
    console.print("  [green]-h, --help[/green]              Show this help message and exit")
    console.print("  [green]-v, --version[/green]           Show program version and exit")
    console.print("  [green]-w, --workdir[/green] [yellow]DIR[/yellow]      Working directory (default: current directory)")
    console.print()

    # Execution Mode
    console.print("[bold cyan]EXECUTION MODE[/bold cyan]")
    console.print("  [green]--dry-run[/green]               [bold](Default)[/bold] Preview changes without modifying files")
    console.print("  [green]--execute[/green]               Execute operations and modify files for real")
    console.print("  [green]-y, --yes[/green]               Auto-confirm all operations (skip confirmations)")
    console.print("  [green]--non-interactive[/green]       Non-interactive mode (for scripts/automation)")
    console.print()

    # Output Options
    console.print("[bold cyan]OUTPUT OPTIONS[/bold cyan]")
    console.print("  [green]--verbose[/green]               Verbose output with detailed information")
    console.print("  [green]-q, --quiet[/green]             Quiet mode (show errors only)")
    console.print("  [green]--log[/green] [yellow]FILE[/yellow]              Save detailed log to file")
    console.print()

    # Subtitle Options
    console.print("[bold cyan]SUBTITLE OPTIONS[/bold cyan]")
    console.print("  [green]--min-pt-words[/green] [yellow]N[/yellow]        Minimum Portuguese words to detect (default: 5)")
    console.print("  [green]--no-rename-por2[/green]        Do NOT rename .por2.srt → .por.srt")
    console.print("  [green]--no-add-lang[/green]           Do NOT add language codes to subtitles")
    console.print("  [green]--no-remove-foreign[/green]     Do NOT remove foreign subtitles")
    console.print()

    # File Cleanup Options
    console.print("[bold cyan]FILE CLEANUP OPTIONS[/bold cyan]")
    console.print("  [green]--remove-non-media[/green]      Remove all files that are not .srt or .mp4")
    console.print()

    # Metadata Options
    console.print("[bold cyan]METADATA OPTIONS[/bold cyan]")
    console.print("  [green]--no-metadata[/green]           Disable metadata fetching from TMDB/TVDB")
    console.print("  [green]--no-quality-tag[/green]        Do NOT add quality tags to filenames")
    console.print("  [green]--use-ffprobe[/green]           Use ffprobe for accurate quality detection")
    console.print()

    # Examples
    console.print("[bold cyan]EXAMPLES[/bold cyan]")
    console.print("  [dim]# Interactive mode (default - launches menu)[/dim]")
    console.print("  [yellow]jellyfix[/yellow]")
    console.print()
    console.print("  [dim]# Preview changes in a specific directory[/dim]")
    console.print("  [yellow]jellyfix[/yellow] --workdir /path/to/media --dry-run")
    console.print()
    console.print("  [dim]# Execute operations for real (with confirmation)[/dim]")
    console.print("  [yellow]jellyfix[/yellow] --workdir /path/to/media --execute")
    console.print()
    console.print("  [dim]# Auto-execute without confirmation (careful!)[/dim]")
    console.print("  [yellow]jellyfix[/yellow] --workdir /path/to/media --execute -y")
    console.print()
    console.print("  [dim]# Non-interactive mode for scripts[/dim]")
    console.print("  [yellow]jellyfix[/yellow] --workdir /path/to/media --execute --non-interactive -y")
    console.print()
    console.print("  [dim]# Save detailed log to file[/dim]")
    console.print("  [yellow]jellyfix[/yellow] --workdir /path/to/media --execute --log jellyfix.log")
    console.print()

    # Configuration
    console.print("[bold cyan]CONFIGURATION[/bold cyan]")
    console.print("  Config file: [cyan]~/.jellyfix/config.json[/cyan]")
    console.print("  - Stores TMDB API key, kept languages, and preferences")
    console.print("  - Configure via interactive menu: [yellow]jellyfix[/yellow] → Settings")
    console.print()

    # What it does
    console.print("[bold cyan]WHAT JELLYFIX DOES[/bold cyan]")
    console.print()
    console.print("  [bold green]Movies:[/bold green]")
    console.print("    [dim]Before:[/dim] movie.name.2023.1080p.bluray.mkv")
    console.print("    [dim]After:[/dim]  Movie Name (2023) [1080p].mkv")
    console.print()
    console.print("  [bold green]TV Shows:[/bold green]")
    console.print("    [dim]Before:[/dim] show.name.s01e05.720p.mkv")
    console.print("    [dim]After:[/dim]  Show Name/Season 01/Show Name - S01E05 [720p].mkv")
    console.print()
    console.print("  [bold green]Subtitles:[/bold green]")
    console.print("    • Renames: .por2.srt → .por.srt, .eng3.srt → .eng.srt")
    console.print("    • Adds language codes: subtitle.srt → Movie.por.srt")
    console.print("    • Removes foreign languages (keeps por, eng by default)")
    console.print("    • [bold]NEVER[/bold] removes .forced.srt files")
    console.print()
    console.print("  [bold green]Metadata:[/bold green]")
    console.print("    • Fetches from TMDB/TVDB")
    console.print("    • Adds IDs to folders: [tmdbid-12345]")
    console.print("    • Downloads posters and metadata")
    console.print()

    # Important notes
    console.print("[bold yellow]⚠️  IMPORTANT NOTES[/bold yellow]")
    console.print("  • [bold]Dry-run is DEFAULT[/bold] - files are NOT modified unless you use --execute")
    console.print("  • Always review the preview before executing")
    console.print("  • Configure TMDB API key for metadata: Settings → Configure APIs")
    console.print("  • Customize kept languages in interactive menu")
    console.print()

    # Links
    console.print("[bold cyan]LINKS[/bold cyan]")
    console.print("  Homepage:   [link=https://github.com/talesam/jellyfix]https://github.com/talesam/jellyfix[/link]")
    console.print("  Issues:     [link=https://github.com/talesam/jellyfix/issues]https://github.com/talesam/jellyfix/issues[/link]")
    console.print("  TMDB API:   [link=https://www.themoviedb.org/settings/api]https://www.themoviedb.org/settings/api[/link]")
    console.print()


def parse_args():
    """Parse command-line arguments"""
    # Check if --help or -h is requested
    if '-h' in sys.argv or '--help' in sys.argv:
        show_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog='jellyfix',
        description='Intelligent Jellyfin Library Organizer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False  # We handle help ourselves
    )

    parser.add_argument('-v', '--version', action='version',
                       version=f'jellyfix {APP_VERSION}')

    # Working directory
    parser.add_argument('-w', '--workdir', type=str, metavar='DIR',
                       help='Working directory (default: current)')

    # Execution mode
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--dry-run', action='store_true', default=False,
                           help='Simulate only, do not modify files')
    mode_group.add_argument('--execute', action='store_true',
                           help='Execute operations for real')

    # Confirmation
    parser.add_argument('-y', '--yes', action='store_true',
                       help='Confirm all operations automatically')

    # Interactive mode
    parser.add_argument('--non-interactive', action='store_true',
                       help='Non-interactive mode (for scripts)')

    # Output verbosity
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument('--verbose', action='store_true',
                                help='Verbose mode (more details)')
    verbosity_group.add_argument('-q', '--quiet', action='store_true',
                                help='Quiet mode (errors only)')

    # Logging
    parser.add_argument('--log', type=str, metavar='FILE',
                       help='Save log to file')

    # Subtitle options
    # NOTA: default=None (em vez de False/5) é o que permite distinguir
    # "usuário passou a flag" de "usuário não disse nada". Sem isso não há como
    # respeitar a prioridade CLI > config.json.
    parser.add_argument('--min-pt-words', type=int, default=None, metavar='N',
                       help='Minimum Portuguese words to detect (default: 5)')
    parser.add_argument('--no-rename-por2', action='store_true', default=None,
                       help='Do not rename .por2.srt → .por.srt')
    parser.add_argument('--no-add-lang', action='store_true', default=None,
                       help='Do not add language code to subtitles')
    parser.add_argument('--no-remove-foreign', action='store_true', default=None,
                       help='Do not remove foreign subtitles')

    # File cleanup
    parser.add_argument('--remove-non-media', action='store_true', default=None,
                       help='Remove all files that are not .srt or .mp4')

    # Metadata
    parser.add_argument('--no-metadata', action='store_true', default=None,
                       help='Disable metadata fetching from TMDB')
    parser.add_argument('--no-quality-tag', action='store_true', default=None,
                       help='Do not add quality tags to filenames')
    parser.add_argument('--use-ffprobe', action='store_true', default=None,
                       help='Use ffprobe for quality detection')

    return parser.parse_args()


def main():
    """Main entry point"""
    # Parse arguments
    args = parse_args()

    # Determine dry_run mode:
    # - --execute explicitly given → execute (dry_run=False)
    # - --dry-run explicitly given → dry_run=True
    # - Neither given + non-interactive → execute (dry_run=False)
    # - Neither given + interactive → dry_run=True (interactive mode will ask)
    if args.execute:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        # Neither flag given: non-interactive defaults to execute,
        # interactive defaults to dry-run (will show preview and ask)
        dry_run = not args.non_interactive

    workdir_explicit = args.workdir is not None

    # Mapeia flag da CLI -> opção do Config. Só entram no Config (e na lista de
    # "explícitas", protegidas contra o config.json) as que o usuário passou.
    # Antes, todas eram sempre passadas e depois sobrescritas pelo arquivo:
    # --no-remove-foreign, --no-metadata & cia. simplesmente não faziam efeito.
    negated_flags = {
        'rename_por2': args.no_rename_por2,
        'rename_no_lang': args.no_add_lang,
        'remove_foreign_subs': args.no_remove_foreign,
        'fetch_metadata': args.no_metadata,
        'add_quality_tag': args.no_quality_tag,
    }
    direct_flags = {
        'remove_non_media': args.remove_non_media,
        'use_ffprobe': args.use_ffprobe,
        'min_pt_words': args.min_pt_words,
    }

    overrides = {}
    for key, value in negated_flags.items():
        if value is not None:
            overrides[key] = not value
    for key, value in direct_flags.items():
        if value is not None:
            overrides[key] = value

    # Create configuration
    config = Config(
        work_dir=Path(args.workdir).resolve() if args.workdir else Path.cwd(),
        dry_run=dry_run,
        auto_confirm=args.yes,
        interactive=not args.non_interactive,
        verbose=args.verbose,
        quiet=args.quiet,
        log_file=Path(args.log) if args.log else None,
        workdir_explicit=workdir_explicit,
        **overrides,
    )
    config.load_persistent_settings(explicit_keys=overrides.keys())

    # Set global config
    set_config(config)

    # Run CLI
    try:
        return run_cli()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 1


if __name__ == '__main__':
    sys.exit(main())
