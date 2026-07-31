#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# cli/app.py - CLI application orchestrator
#

"""
Main entry point for the CLI application.

This module determines which CLI mode to use (interactive or non-interactive)
and delegates to the appropriate handler.
"""

from ..utils.config import get_config
from ..utils.logger import set_logger, get_logger, Logger
from ..utils.i18n import _


def run_cli():
    """
    Main CLI entry point.
    
    Determines the mode (interactive vs non-interactive) based on
    configuration and runs the appropriate CLI handler.
    """
    # Load configuration
    config = get_config()

    # Setup logger
    logger_instance = Logger(
        log_file=config.log_file if hasattr(config, 'log_file') else None,
        verbose=config.verbose,
        quiet=config.quiet
    )
    set_logger(logger_instance)
    logger = get_logger()
    
    try:
        # Determine mode based on config
        if config.interactive:
            # Interactive mode with menus
            from .interactive import InteractiveCLI
            
            cli = InteractiveCLI(config)
            if config.workdir_explicit:
                # --workdir provided: go directly to processing
                # Propaga o código de saída (ex.: diretório inexistente = 1);
                # antes ele era descartado e o jellyfix sempre saía com 0,
                # quebrando scripts que checam o status.
                return cli.run_direct() or 0
            else:
                # No workdir: show main menu
                cli.run()
        else:
            # Non-interactive scriptable mode
            from .non_interactive import NonInteractiveCLI

            cli = NonInteractiveCLI(config)
            return cli.run() or 0


    except KeyboardInterrupt:
        logger.info("\n" + _("Operation cancelled by user"))
        return 1
        
    except Exception as e:
        logger.error(_("Unexpected error: %s") % str(e))
        if config.verbose:
            import traceback
            traceback.print_exc()
        return 1
    
    return 0
