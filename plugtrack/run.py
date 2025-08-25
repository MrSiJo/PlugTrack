from plugtrack import create_app, db
from plugtrack.models import User, Car, ChargingSession, Settings
from datetime import date, datetime
import click
import os
import csv

app = create_app()

@app.cli.command('init-db')
def init_db():
    """Initialize the database with sample data."""
    db.create_all()
    
    # Check if we already have a user
    if User.query.first() is None:
        # Create demo user
        user = User(username='demo')
        user.set_password('demo123')
        db.session.add(user)
        db.session.commit()
        
        # Create demo car
        car = Car(
            user_id=user.id,
            make='Tesla',
            model='Model 3',
            battery_kwh=75.0,
            efficiency_mpkwh=4.2,
            active=True,
            recommended_full_charge_enabled=True,
            recommended_full_charge_frequency_value=7,
            recommended_full_charge_frequency_unit='days'
        )
        db.session.add(car)
        db.session.commit()
        
        # Create demo charging session
        session = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=date.today(),
            odometer=15000,
            charge_type='AC',
            charge_speed_kw=7.4,
            location_label='Home',
            charge_network='Home Charger',
            charge_delivered_kwh=25.5,
            duration_mins=180,
            cost_per_kwh=0.12,
            soc_from=20,
            soc_to=54,
            notes='Evening charge at home'
        )
        db.session.add(session)
        db.session.commit()
        
        print('Database initialized with demo data!')
        print('Username: demo, Password: demo123')
    else:
        print('Database already contains data.')

@app.cli.command('create-admin')
def create_admin():
    """Create an admin user."""
    username = input('Enter username: ')
    password = input('Enter password: ')
    
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    print(f'Admin user {username} created successfully!')

# Phase 4 CLI Commands

@app.cli.command('sessions-export')
@click.option('--to', 'dst_path', required=True, help='Destination CSV file path')
@click.option('--car', 'car_id', type=int, help='Filter by car ID')
@click.option('--from', 'date_from', help='Filter from date (YYYY-MM-DD)')
@click.option('--to-date', 'date_to', help='Filter to date (YYYY-MM-DD)')
@click.option('--user', 'user_id', type=int, default=1, help='User ID (default: 1)')
def sessions_export(dst_path, car_id, date_from, date_to, user_id):
    """Export charging sessions to CSV file."""
    try:
        from services.io_sessions import SessionIOService
        
        # Parse dates
        parsed_date_from = None
        if date_from:
            try:
                parsed_date_from = date.fromisoformat(date_from)
            except ValueError:
                click.echo(f"Error: Invalid date format for --from: {date_from}. Use YYYY-MM-DD")
                return
        
        parsed_date_to = None
        if date_to:
            try:
                parsed_date_to = date.fromisoformat(date_to)
            except ValueError:
                click.echo(f"Error: Invalid date format for --to-date: {date_to}. Use YYYY-MM-DD")
                return
        
        # Export sessions
        report = SessionIOService.export_sessions(
            user_id=user_id,
            dst_path=dst_path,
            car_id=car_id,
            date_from=parsed_date_from,
            date_to=parsed_date_to
        )
        
        click.echo(report.to_cli_text())
        
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)

@app.cli.command('sessions-import')
@click.option('--from', 'src_path', required=True, help='Source CSV file path')
@click.option('--car', 'car_id', type=int, help='Override car ID for all sessions')
@click.option('--dry-run', is_flag=True, help='Validate only, no database writes')
@click.option('--user', 'user_id', type=int, default=1, help='User ID (default: 1)')
def sessions_import(src_path, car_id, dry_run, user_id):
    """Import charging sessions from CSV file."""
    try:
        from services.io_sessions import SessionIOService
        
        if not os.path.exists(src_path):
            click.echo(f"Error: Source file not found: {src_path}", err=True)
            return
        
        # Import sessions
        report = SessionIOService.import_sessions(
            user_id=user_id,
            src_path=src_path,
            car_id=car_id,
            dry_run=dry_run
        )
        
        click.echo(report.to_cli_text())
        
        if dry_run and report.errors:
            # Write error report to CSV
            error_csv = f"{src_path}.errors.csv"
            with open(error_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['row', 'field', 'message'])
                for error in report.errors:
                    writer.writerow([error['row'], error['field'], error['message']])
            click.echo(f"Error details written to: {error_csv}")
        
        # Exit with error code if there are validation errors
        if report.errors:
            exit(1)
        
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        exit(1)

@app.cli.command('backup-create')
@click.option('--to', 'dst_zip', required=True, help='Destination ZIP file path')
@click.option('--user', 'user_id', type=int, default=1, help='User ID (default: 1)')
def backup_create(dst_zip, user_id):
    """Create a backup ZIP containing sessions, cars, settings, and manifest."""
    try:
        from services.io_backup import BackupService
        
        # Create backup
        report = BackupService.create_backup(user_id=user_id, dst_zip=dst_zip)
        
        click.echo(report.to_cli_text())
        
        if not report.success:
            exit(1)
        
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        exit(1)

@app.cli.command('backup-restore')
@click.option('--from', 'src_zip', required=True, help='Source backup ZIP file path')
@click.option('--mode', 'mode', type=click.Choice(['merge', 'replace']), default='merge', help='Restore mode: merge (default) or replace')
@click.option('--dry-run', is_flag=True, help='Simulate restore, no database writes')
@click.option('--user', 'user_id', type=int, default=1, help='User ID (default: 1)')
def backup_restore(src_zip, mode, dry_run, user_id):
    """Restore from backup ZIP file."""
    try:
        from services.io_backup import BackupService
        
        if not os.path.exists(src_zip):
            click.echo(f"Error: Backup file not found: {src_zip}", err=True)
            return
        
        if mode == "replace" and not dry_run:
            # Confirm destructive operation
            if not click.confirm(f"This will replace ALL data for user {user_id}. Are you sure?"):
                click.echo("Restore cancelled.")
                return
        
        # Restore backup
        report = BackupService.restore_backup(
            user_id=user_id,
            src_zip=src_zip,
            mode=mode,
            dry_run=dry_run
        )
        
        click.echo(report.to_cli_text())
        
        if report.errors:
            exit(1)
        
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        exit(1)

if __name__ == '__main__':
    app.run(debug=True)
