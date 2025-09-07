#!/usr/bin/env python3
"""
CLI Utilities for PlugTrack
Provides verbosity control, error handling, and examples for CLI commands.
"""

import click
import sys
from typing import Optional, Callable, Any
from functools import wraps


class VerbosityLevel:
    """Verbosity levels for CLI commands."""
    QUIET = 0
    NORMAL = 1
    VERBOSE = 2


class CLIOutput:
    """Centralized output handling with verbosity control."""
    
    def __init__(self, verbosity: int = VerbosityLevel.NORMAL):
        self.verbosity = verbosity
    
    def echo(self, message: str, err: bool = False, nl: bool = True, **kwargs):
        """Echo a message respecting verbosity level."""
        if self.verbosity >= VerbosityLevel.NORMAL:
            click.echo(message, err=err, nl=nl, **kwargs)
    
    def verbose(self, message: str, err: bool = False, nl: bool = True, **kwargs):
        """Echo a verbose message (only shown with --verbose)."""
        if self.verbosity >= VerbosityLevel.VERBOSE:
            click.echo(f"[VERBOSE] {message}", err=err, nl=nl, **kwargs)
    
    def quiet(self, message: str, err: bool = False, nl: bool = True, **kwargs):
        """Echo a quiet message (only shown with --quiet)."""
        if self.verbosity <= VerbosityLevel.QUIET:
            click.echo(message, err=err, nl=nl, **kwargs)
    
    def success(self, message: str, **kwargs):
        """Echo a success message."""
        self.echo(f"✅ {message}", **kwargs)
    
    def error(self, message: str, **kwargs):
        """Echo an error message."""
        self.echo(f"❌ {message}", err=True, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Echo a warning message."""
        self.echo(f"⚠️  {message}", **kwargs)
    
    def info(self, message: str, **kwargs):
        """Echo an info message."""
        self.echo(f"ℹ️  {message}", **kwargs)


def add_verbosity_options(func: Callable) -> Callable:
    """Decorator to add verbosity options to CLI commands."""
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    @click.option('--quiet', '-q', is_flag=True, help='Suppress non-error output')
    @click.option('--examples', is_flag=True, help='Show usage examples')
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Handle examples flag
        if kwargs.get('examples'):
            show_examples(func.__name__)
            sys.exit(0)
        
        # Determine verbosity level
        verbose = kwargs.pop('verbose', False)
        quiet = kwargs.pop('quiet', False)
        
        if verbose and quiet:
            click.echo("Error: Cannot specify both --verbose and --quiet", err=True)
            sys.exit(1)
        
        verbosity = VerbosityLevel.VERBOSE if verbose else (VerbosityLevel.QUIET if quiet else VerbosityLevel.NORMAL)
        
        # Add verbosity to kwargs for the function
        kwargs['verbosity'] = verbosity
        kwargs['output'] = CLIOutput(verbosity)
        
        return func(*args, **kwargs)
    return wrapper


def handle_cli_error(func: Callable) -> Callable:
    """Decorator to handle CLI errors with proper exit codes."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except click.ClickException:
            # Re-raise Click exceptions as-is
            raise
        except Exception as e:
            output = kwargs.get('output', CLIOutput())
            output.error(f"Unexpected error: {str(e)}")
            if kwargs.get('verbosity', VerbosityLevel.NORMAL) >= VerbosityLevel.VERBOSE:
                import traceback
                output.verbose(f"Traceback: {traceback.format_exc()}")
            sys.exit(1)
    return wrapper


def show_examples(command_name: str):
    """Show usage examples for a specific command."""
    examples = {
        'sessions-export': """
📋 Sessions Export Examples:

Basic export:
  flask sessions-export --to sessions.csv

Export for specific car:
  flask sessions-export --to tesla_sessions.csv --car 1

Verbose output:
  flask sessions-export --to sessions.csv --verbose

Quiet mode (errors only):
  flask sessions-export --to sessions.csv --quiet
""",
        'sessions-import': """
📋 Sessions Import Examples:

Basic import:
  flask sessions-import --from sessions.csv

Import with car override:
  flask sessions-import --from sessions.csv --car 2

Verbose import:
  flask sessions-import --from sessions.csv --verbose
""",
        'backup-create': """
📋 Backup Create Examples:

Create backup:
  flask backup-create --to backup_2024.zip

Backup specific user:
  flask backup-create --to user1_backup.zip --user 2

Verbose backup:
  flask backup-create --to backup.zip --verbose
""",
        'backup-restore': """
📋 Backup Restore Examples:

Merge restore:
  flask backup-restore --from backup.zip

Replace restore:
  flask backup-restore --from backup.zip --mode replace

Verbose restore:
  flask backup-restore --from backup.zip --verbose
""",
        'recompute-sessions': """
📋 Recompute Sessions Examples:

Recompute all sessions:
  flask recompute-sessions --all

Recompute for specific user:
  flask recompute-sessions --user 1

Recompute specific session:
  flask recompute-sessions --session 123

Show summary:
  flask recompute-sessions --summary

Force recomputation:
  flask recompute-sessions --all --force

Verbose output:
  flask recompute-sessions --all --verbose
""",
        'reminders-run': """
📋 Reminders Run Examples:

Check all reminders:
  flask reminders-run

Check for specific user:
  flask reminders-run --user 1

Check for specific car:
  flask reminders-run --car 2

Verbose output:
  flask reminders-run --verbose
""",
        'analytics-dump': """
📋 Analytics Dump Examples:

Dump all analytics:
  flask analytics-dump

Dump for specific user:
  flask analytics-dump --user 1

Dump for specific car:
  flask analytics-dump --car 2

Verbose output:
  flask analytics-dump --verbose
"""
    }
    
    if command_name in examples:
        click.echo(examples[command_name])
    else:
        click.echo(f"No examples available for command: {command_name}")


def create_success_result(message: str, data: dict = None) -> dict:
    """Create a standardized success result."""
    result = {
        'success': True,
        'message': message,
        'exit_code': 0
    }
    if data:
        result.update(data)
    return result


def create_error_result(message: str, exit_code: int = 1, data: dict = None) -> dict:
    """Create a standardized error result."""
    result = {
        'success': False,
        'message': message,
        'exit_code': exit_code
    }
    if data:
        result.update(data)
    return result


def exit_with_result(result: dict):
    """Exit with proper code based on result."""
    if not result['success']:
        click.echo(f"Error: {result['message']}", err=True)
    else:
        click.echo(result['message'])
    
    sys.exit(result['exit_code'])
