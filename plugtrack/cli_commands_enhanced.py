#!/usr/bin/env python3
"""
Enhanced CLI Commands for PlugTrack B7-4
Provides verbosity control, improved error handling, and examples.
"""

import click
import sys
from datetime import date
from utils.cli_utils import CLIOutput, VerbosityLevel, show_examples, create_success_result, create_error_result, exit_with_result


def add_verbosity_decorator(func):
    """Add verbosity options to a CLI command."""
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    @click.option('--quiet', '-q', is_flag=True, help='Suppress non-error output')
    @click.option('--examples', is_flag=True, help='Show usage examples')
    def wrapper(*args, **kwargs):
        if kwargs.get('examples'):
            show_examples(func.__name__)
            sys.exit(0)
        
        if kwargs.get('verbose') and kwargs.get('quiet'):
            click.echo("Error: Cannot specify both --verbose and --quiet", err=True)
            sys.exit(1)
        
        verbosity = VerbosityLevel.VERBOSE if kwargs.get('verbose') else (VerbosityLevel.QUIET if kwargs.get('quiet') else VerbosityLevel.NORMAL)
        output = CLIOutput(verbosity)
        
        # Remove verbosity options from kwargs
        kwargs.pop('verbose', None)
        kwargs.pop('quiet', None)
        kwargs.pop('examples', None)
        
        # Add output to kwargs
        kwargs['output'] = output
        kwargs['verbosity'] = verbosity
        
        return func(*args, **kwargs)
    return wrapper


def handle_errors(func):
    """Handle errors with proper exit codes."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except click.ClickException:
            raise
        except Exception as e:
            output = kwargs.get('output', CLIOutput())
            output.error(f"Unexpected error: {str(e)}")
            if kwargs.get('verbosity', VerbosityLevel.NORMAL) >= VerbosityLevel.VERBOSE:
                import traceback
                output.verbose(f"Traceback: {traceback.format_exc()}")
            sys.exit(1)
    return wrapper


@add_verbosity_decorator
@handle_errors
def sessions_export(dst_path, car_id, date_from, date_to, user_id, output, verbosity):
    """Export charging sessions to CSV file."""
    from services.io_sessions import SessionIOService
    
    output.verbose(f"Starting sessions export to: {dst_path}")
    output.verbose(f"User ID: {user_id}, Car ID: {car_id}")
    output.verbose(f"Date range: {date_from} to {date_to}")
    
    # Parse dates
    parsed_date_from = None
    if date_from:
        try:
            parsed_date_from = date.fromisoformat(date_from)
            output.verbose(f"Parsed from date: {parsed_date_from}")
        except ValueError:
            output.error(f"Invalid date format for --from: {date_from}. Use YYYY-MM-DD")
            sys.exit(1)
    
    parsed_date_to = None
    if date_to:
        try:
            parsed_date_to = date.fromisoformat(date_to)
            output.verbose(f"Parsed to date: {parsed_date_to}")
        except ValueError:
            output.error(f"Invalid date format for --to-date: {date_to}. Use YYYY-MM-DD")
            sys.exit(1)
    
    # Export sessions
    output.verbose("Calling SessionIOService.export_sessions...")
    report = SessionIOService.export_sessions(
        user_id=user_id,
        dst_path=dst_path,
        car_id=car_id,
        date_from=parsed_date_from,
        date_to=parsed_date_to
    )
    
    output.success(f"Export completed: {report.to_cli_text()}")


@add_verbosity_decorator
@handle_errors
def sessions_import(src_path, car_id, dry_run, user_id, output, verbosity):
    """Import charging sessions from CSV file."""
    from services.io_sessions import SessionIOService
    
    output.verbose(f"Starting sessions import from: {src_path}")
    output.verbose(f"User ID: {user_id}, Car ID: {car_id}, Dry run: {dry_run}")
    
    # Import sessions
    output.verbose("Calling SessionIOService.import_sessions...")
    report = SessionIOService.import_sessions(
        user_id=user_id,
        src_path=src_path,
        car_id=car_id,
        dry_run=dry_run
    )
    
    if dry_run:
        output.info(f"Dry run completed: {report.to_cli_text()}")
    else:
        output.success(f"Import completed: {report.to_cli_text()}")


@add_verbosity_decorator
@handle_errors
def backup_create(dst_zip, user_id, output, verbosity):
    """Create a backup of user data."""
    from services.backup_restore import BackupRestoreService
    
    output.verbose(f"Starting backup creation to: {dst_zip}")
    output.verbose(f"User ID: {user_id}")
    
    # Create backup
    output.verbose("Calling BackupRestoreService.create_backup...")
    result = BackupRestoreService.create_backup(user_id, dst_zip)
    
    if result['success']:
        output.success(f"Backup created: {result['message']}")
    else:
        output.error(f"Backup failed: {result['error']}")
        sys.exit(1)


@add_verbosity_decorator
@handle_errors
def backup_restore(src_zip, mode, output, verbosity):
    """Restore user data from backup."""
    from services.backup_restore import BackupRestoreService
    
    output.verbose(f"Starting backup restore from: {src_zip}")
    output.verbose(f"Mode: {mode}")
    
    # Restore backup
    output.verbose("Calling BackupRestoreService.restore_backup...")
    result = BackupRestoreService.restore_backup(src_zip, mode)
    
    if result['success']:
        output.success(f"Backup restored: {result['message']}")
    else:
        output.error(f"Restore failed: {result['error']}")
        sys.exit(1)


@add_verbosity_decorator
@handle_errors
def recompute_sessions(recompute_all, user_id, session_id, force, summary, output, verbosity):
    """Recompute derived metrics for charging sessions."""
    from services.precompute import PrecomputeService
    
    if summary:
        output.verbose("Showing metrics summary...")
        result = PrecomputeService.get_metrics_summary()
        if result['success']:
            output.echo(f"📊 Metrics Summary:")
            output.echo(f"  Total sessions: {result['total_sessions']}")
            output.echo(f"  Computed sessions: {result['computed_sessions']}")
            output.echo(f"  Pending sessions: {result['pending_sessions']}")
            output.echo(f"  Completion rate: {result['completion_rate']:.1f}%")
        else:
            output.error(f"Summary failed: {result['error']}")
            sys.exit(1)
    
    elif recompute_all:
        output.verbose("Recomputing metrics for all sessions...")
        result = PrecomputeService.compute_all(force_recompute=force)
        if result['success']:
            output.success(f"Recomputation completed: {result['message']}")
            output.echo(f"  Total sessions: {result['total_sessions']}")
            output.echo(f"  Processed: {result['processed']}")
            if result.get('errors'):
                output.warning(f"  Errors: {len(result['errors'])}")
                for error in result['errors'][:5]:
                    output.echo(f"    Session {error['session_id']}: {error['error']}")
                if len(result['errors']) > 5:
                    output.echo(f"    ... and {len(result['errors']) - 5} more errors")
        else:
            output.error(f"Recomputation failed: {result['error']}")
            sys.exit(1)
    
    elif user_id:
        output.verbose(f"Recomputing metrics for user {user_id}...")
        result = PrecomputeService.compute_for_user(user_id, force_recompute=force)
        if result['success']:
            output.success(f"User recomputation completed: {result['message']}")
            output.echo(f"  Total sessions: {result['total_sessions']}")
            output.echo(f"  Processed: {result['processed']}")
        else:
            output.error(f"User recomputation failed: {result['error']}")
            sys.exit(1)
    
    elif session_id:
        output.verbose(f"Recomputing metrics for session {session_id}...")
        result = PrecomputeService.compute_for_session(session_id)
        if result['success']:
            output.success(f"Session recomputation completed")
            metrics = result['metrics']
            output.echo(f"  Efficiency: {metrics['efficiency_mpkwh']:.2f} mi/kWh")
            output.echo(f"  Cost per mile: {metrics['pence_per_mile']:.1f} p/mile")
            output.echo(f"  Loss percentage: {metrics['loss_pct']:.1f}%")
        else:
            output.error(f"Session recomputation failed: {result['error']}")
            sys.exit(1)
    
    else:
        output.error("Please specify --all, --user <id>, --session <id>, or --summary")
        output.echo("Use --help for more information")
        sys.exit(1)


@add_verbosity_decorator
@handle_errors
def reminders_run(user_id, car_id, output, verbosity):
    """Run 100% charge reminder checks for all users."""
    from services.reminders import ReminderService
    
    output.verbose("Starting reminder checks...")
    output.verbose(f"User ID: {user_id}, Car ID: {car_id}")
    
    # Run reminders
    output.verbose("Calling ReminderService.check_all_reminders...")
    result = ReminderService.check_all_reminders(user_id=user_id, car_id=car_id)
    
    if result['success']:
        output.success(f"Reminder checks completed: {result['message']}")
        output.echo(f"  Reminders sent: {result.get('reminders_sent', 0)}")
        output.echo(f"  Users checked: {result.get('users_checked', 0)}")
    else:
        output.error(f"Reminder checks failed: {result['error']}")
        sys.exit(1)


@add_verbosity_decorator
@handle_errors
def analytics_dump(user_id, car_id, output, verbosity):
    """Dump analytics data to console."""
    from services.analytics_agg import AnalyticsAggregationService
    
    output.verbose("Starting analytics dump...")
    output.verbose(f"User ID: {user_id}, Car ID: {car_id}")
    
    # Dump analytics
    output.verbose("Calling AnalyticsAggregationService.dump_analytics...")
    result = AnalyticsAggregationService.dump_analytics(user_id=user_id, car_id=car_id)
    
    if result['success']:
        output.success("Analytics dump completed")
        output.echo(result['data'])
    else:
        output.error(f"Analytics dump failed: {result['error']}")
        sys.exit(1)
