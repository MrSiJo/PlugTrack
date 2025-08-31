import sys
import os

# Add the current directory to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from flask import Flask
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config
from models.user import db, User
import click
from datetime import date
from models.car import Car
from models.charging_session import ChargingSession

migrate = Migrate()
login_manager = LoginManager()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize configuration after app creation
    config_class.init_app(app)
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    
    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))
    
    # Register blueprints
    from routes import auth_bp, cars_bp, charging_sessions_bp, settings_bp, dashboard_bp, analytics_bp
    from routes.blend import blend_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(cars_bp)
    app.register_blueprint(charging_sessions_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(blend_bp)
    
    # Add template globals for currency formatting
    from utils.currency import format_currency, get_currency_symbol, get_currency_info
    
    app.jinja_env.globals.update({
        'format_currency': format_currency,
        'get_currency_symbol': get_currency_symbol,
        'get_currency_info': get_currency_info
    })
    
    # Add context processor for reminder data (Phase 5.4)
    @app.context_processor
    def inject_reminder_data():
        try:
            from flask_login import current_user
            
            if current_user.is_authenticated:
                from services.reminders import ReminderService
                from models.car import Car
                
                # Get user's cars
                cars = Car.query.filter_by(user_id=current_user.id).all()
                
                # Check if any cars have reminder guidance enabled
                has_reminder_guidance = any(
                    car.recommended_full_charge_enabled and 
                    car.recommended_full_charge_frequency_value and 
                    car.recommended_full_charge_frequency_unit
                    for car in cars
                )
                
                # Get reminder data if guidance is enabled
                if has_reminder_guidance:
                    reminder_data = ReminderService.check_full_charge_due(current_user.id)
                    reminders = reminder_data.get('reminders', [])
                else:
                    reminders = []
                
                return {
                    'navbar_reminders': reminders,
                    'navbar_has_reminder_guidance': has_reminder_guidance
                }
            else:
                return {
                    'navbar_reminders': [],
                    'navbar_has_reminder_guidance': False
                }
        except Exception as e:
            # Log error but don't break the app
            return {
                'navbar_reminders': [],
                'navbar_has_reminder_guidance': False
            }
    
    # Register Phase 4 CLI commands
    @app.cli.command('reminders-run')
    def reminders_run():
        """Run 100% charge reminder checks for all users."""
        from services.reminders import ReminderService
        
        print("Running 100% charge reminder checks...")
        results = ReminderService.check_all_users()
        
        # Log results
        ReminderService.log_reminder_check(results)
        
        # Print summary
        total_reminders = results['total_reminders']
        users_with_reminders = results['users_with_reminders']
        
        if total_reminders == 0:
            print("✅ No reminders due")
        else:
            print(f"⚠️  {total_reminders} reminders due for {users_with_reminders} users")
            for user_reminder in results['user_reminders']:
                username = user_reminder.get('username', f"User {user_reminder['user_id']}")
                reminder_count = user_reminder['reminders_due']
                print(f"  📱 {username}: {reminder_count} reminder(s)")
        
        return results
    
    @app.cli.command('init-db')
    @click.option('--dry-run', is_flag=True, help='Show what would be done without making changes')
    @click.option('--force-fresh', is_flag=True, help='Treat as fresh install even if data exists')
    def init_db(dry_run, force_fresh):
        """Initialize or migrate the database using the modern migration system."""
        from init_db_v2 import init_database
        success = init_database(dry_run=dry_run, force_fresh=force_fresh)
        if not success:
            raise click.ClickException("Database initialization failed")
    
    @app.cli.command('migration-status')
    def migration_status():
        """Show detailed migration status."""
        from init_db_v2 import migration_status as show_status
        show_status()
    
    @app.cli.command('create-migration')
    @click.argument('migration_id')
    @click.argument('description')
    def create_migration_cmd(migration_id, description):
        """Create a new migration file."""
        from init_db_v2 import create_migration
        success = create_migration(migration_id, description)
        if not success:
            raise click.ClickException("Migration creation failed")
    
    @app.cli.command('apply-migrations')
    @click.option('--dry-run', is_flag=True, help='Show what would be done without making changes')
    def apply_migrations(dry_run):
        """Apply all pending migrations."""
        from migrations.migration_manager import MigrationManager
        migration_manager = MigrationManager(app)
        success = migration_manager.apply_all_pending(dry_run=dry_run)
        if not success:
            raise click.ClickException("Migration application failed")
    
    @app.cli.command('rollback-migration')
    @click.argument('migration_id')
    def rollback_migration(migration_id):
        """Rollback a specific migration."""
        from migrations.migration_manager import MigrationManager
        migration_manager = MigrationManager(app)
        success = migration_manager.rollback_migration(migration_id)
        if not success:
            raise click.ClickException(f"Migration rollback failed for {migration_id}")
    
    @app.cli.command('init-db-legacy')
    def init_db_legacy():
        """Legacy database initialization (deprecated - use init-db instead)."""
        click.echo("⚠️  This command is deprecated. Use 'flask init-db' instead.")
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

    @app.cli.command('modify-user')
    def modify_user():
        """Modify an existing user's username and/or password."""
        try:
            # List existing users
            users = User.query.all()
            if not users:
                print("No users found in the database.")
                return
            
            print("Existing users:")
            for user in users:
                print(f"  ID: {user.id}, Username: {user.username}")
            
            # Get user to modify
            try:
                user_id = int(input('\nEnter user ID to modify: '))
            except ValueError:
                print("Invalid user ID. Please enter a number.")
                return
            
            user = User.query.get(user_id)
            if not user:
                print(f"User with ID {user_id} not found.")
                return
            
            print(f"\nModifying user: {user.username}")
            
            # Get new username (optional)
            new_username = input('Enter new username (or press Enter to keep current): ').strip()
            if new_username:
                # Check if username already exists
                existing_user = User.query.filter_by(username=new_username).first()
                if existing_user and existing_user.id != user_id:
                    print(f"Username '{new_username}' already exists. Please choose a different username.")
                    return
                user.username = new_username
                print(f"Username updated to: {new_username}")
            
            # Get new password (optional)
            new_password = input('Enter new password (or press Enter to keep current): ').strip()
            if new_password:
                user.set_password(new_password)
                print("Password updated successfully.")
            
            if new_username or new_password:
                # Commit the changes with proper error handling
                db.session.commit()
                
                # Verify the update was committed
                db.session.refresh(user)
                print(f"User {user.username} updated successfully!")
                print(f"Verification: Username is now '{user.username}'")
            else:
                print("No changes made.")
                
        except Exception as e:
            print(f"Error updating user: {e}")
            db.session.rollback()
            print("Changes were rolled back due to an error.")

    @app.cli.command('delete-user')
    def delete_user():
        """Delete a user account."""
        # List existing users
        users = User.query.all()
        if not users:
            print("No users found in the database.")
            return
        
        print("Existing users:")
        for user in users:
            print(f"  ID: {user.id}, Username: {user.username}")
        
        # Get user to delete
        try:
            user_id = int(input('\nEnter user ID to delete: '))
        except ValueError:
            print("Invalid user ID. Please enter a number.")
            return
        
        user = User.query.get(user_id)
        if not user:
            print(f"User with ID {user_id} not found.")
            return
        
        # Confirm deletion
        confirm = input(f"\nAre you sure you want to delete user '{user.username}'? This will also delete all their data (cars, sessions, settings). Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            print("Deletion cancelled.")
            return
        
        # Delete user data (in correct order to respect foreign keys)
        from models.charging_session import ChargingSession
        from models.car import Car
        from models.settings import Settings
        
        # Delete in order: sessions -> cars -> settings -> user
        ChargingSession.query.filter_by(user_id=user_id).delete()
        Car.query.filter_by(user_id=user_id).delete()
        Settings.query.filter_by(user_id=user_id).delete()
        db.session.delete(user)
        db.session.commit()
        
        print(f"User '{user.username}' and all associated data deleted successfully!")

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
            import os
            import csv
            
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
            import os
            
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

    @app.cli.command('recompute-sessions')
    @click.option('--user', 'user_id', type=int, default=1, help='User ID (default: 1)')
    @click.option('--car', 'car_id', type=int, help='Filter by car ID')
    @click.option('--force', is_flag=True, help='Force recomputation even if already computed')
    @click.option('--summary', is_flag=True, help='Show summary of metrics status')
    def recompute_sessions(user_id, car_id, force, summary):
        """Recompute all derived metrics for charging sessions."""
        try:
            from services.session_metrics_precompute import SessionMetricsPrecomputeService
            
            if summary:
                # Show summary of current metrics status
                summary_data = SessionMetricsPrecomputeService.get_metrics_summary(user_id, car_id)
                click.echo(f"Metrics Summary for User {user_id}:")
                click.echo(f"  Total sessions: {summary_data['total_sessions']}")
                click.echo(f"  Sessions with metrics: {summary_data['sessions_with_metrics']}")
                click.echo(f"  Sessions without metrics: {summary_data['sessions_without_metrics']}")
                click.echo(f"  Completion: {summary_data['completion_percentage']:.1f}%")
                return
            
            # Recompute metrics
            click.echo(f"Recomputing metrics for user {user_id}...")
            if car_id:
                click.echo(f"Filtering by car {car_id}...")
            
            result = SessionMetricsPrecomputeService.precompute_all_sessions(
                user_id=user_id,
                car_id=car_id,
                force_recompute=force
            )
            
            click.echo(f"✅ {result['message']}")
            click.echo(f"  Total sessions: {result['total_sessions']}")
            click.echo(f"  Processed: {result['processed']}")
            
            if result['errors']:
                click.echo(f"  Errors: {len(result['errors'])}")
                for error in result['errors'][:5]:  # Show first 5 errors
                    click.echo(f"    Session {error['session_id']}: {error['error']}")
                if len(result['errors']) > 5:
                    click.echo(f"    ... and {len(result['errors']) - 5} more errors")
            
            if not result['success']:
                exit(1)
            
        except Exception as e:
            click.echo(f"Error: {str(e)}", err=True)
            exit(1)

    @app.cli.command('reminders-run')
    @click.option('--user', 'user_id', type=int, help='Check reminders for specific user ID')
    @click.option('--car', 'car_id', type=int, help='Check reminders for specific car ID')
    @click.option('--log-level', type=click.Choice(['debug', 'info', 'warning', 'error']), 
                  default='info', help='Logging level (default: info)')
    @click.option('--json', 'output_json', is_flag=True, help='Output results as JSON')
    def reminders_run(user_id, car_id, log_level, output_json):
        """Run reminder checks for 100% charge frequency."""
        try:
            from services.reminders import ReminderService
            import json
            
            if user_id:
                # Check specific user
                click.echo(f"Checking reminders for user {user_id}...")
                if car_id:
                    click.echo(f"Filtering by car {car_id}...")
                
                results = ReminderService.check_full_charge_due(user_id, car_id)
            else:
                # Check all users
                click.echo("Checking reminders for all users...")
                results = ReminderService.check_all_users()
            
            if output_json:
                # Output as JSON
                click.echo(json.dumps(results, indent=2))
            else:
                # Human-readable output
                if 'user_reminders' in results:
                    # Results from check_all_users()
                    total_reminders = results['total_reminders']
                    users_with_reminders = results['users_with_reminders']
                    total_users = results['total_users_checked']
                    
                    click.echo(f"✅ Checked {total_users} users")
                    
                    if total_reminders == 0:
                        click.echo("🎉 No 100% charge reminders due!")
                    else:
                        click.echo(f"⚠️  {total_reminders} reminders due for {users_with_reminders} users:")
                        
                        for user_reminder in results['user_reminders']:
                            username = user_reminder.get('username', f"User {user_reminder['user_id']}")
                            click.echo(f"\n  📋 {username}:")
                            
                            for reminder in user_reminder['reminders']:
                                car_name = reminder['car_make_model']
                                urgency = reminder['urgency']
                                days_overdue = reminder['days_overdue']
                                message = reminder['message']
                                
                                urgency_emoji = {
                                    'due': '🟡',
                                    'overdue': '🟠', 
                                    'critical': '🔴'
                                }.get(urgency, '⚪')
                                
                                click.echo(f"    {urgency_emoji} {car_name} ({urgency}): {days_overdue} days overdue")
                                click.echo(f"      {message}")
                else:
                    # Results from check_full_charge_due() for single user
                    reminder_count = results['reminders_due']
                    user_id = results['user_id']
                    cars_checked = results['total_cars_checked']
                    
                    click.echo(f"✅ Checked {cars_checked} cars for user {user_id}")
                    
                    if reminder_count == 0:
                        click.echo("🎉 No 100% charge reminders due!")
                    else:
                        click.echo(f"⚠️  {reminder_count} reminders due:")
                        
                        for reminder in results['reminders']:
                            car_name = reminder['car_make_model']
                            urgency = reminder['urgency']
                            days_overdue = reminder['days_overdue']
                            message = reminder['message']
                            
                            urgency_emoji = {
                                'due': '🟡',
                                'overdue': '🟠',
                                'critical': '🔴'
                            }.get(urgency, '⚪')
                            
                            click.echo(f"  {urgency_emoji} {car_name} ({urgency}): {days_overdue} days overdue")
                            click.echo(f"    {message}")
            
            # Log results if not outputting JSON
            if not output_json:
                ReminderService.log_reminder_check(results, log_level)
            
        except Exception as e:
            click.echo(f"Error: {str(e)}", err=True)
            exit(1)

    @app.cli.command('analytics-dump')
    @click.option('--user', 'user_id', type=int, help='Dump analytics for specific user ID')
    @click.option('--car', 'car_id', type=int, help='Filter by specific car ID')
    @click.option('--format', 'output_format', type=click.Choice(['json', 'csv']), 
                  default='json', help='Output format (default: json)')
    @click.option('--output', 'output_file', type=str, help='Output file path (default: stdout)')
    @click.option('--pretty', is_flag=True, help='Pretty-print JSON output')
    def analytics_dump(user_id, car_id, output_format, output_file, pretty):
        """Dump aggregated analytics to JSON or CSV format."""
        try:
            from services.aggregated_analytics import AggregatedAnalyticsService
            import json
            import csv
            import sys
            
            if user_id:
                click.echo(f"Dumping analytics for user {user_id}...")
                if car_id:
                    click.echo(f"Filtering by car {car_id}...")
                
                analytics_data = AggregatedAnalyticsService.get_all_aggregated_stats(user_id, car_id)
                all_data = {f'user_{user_id}': analytics_data}
            else:
                # Dump for all users
                from models.user import User
                click.echo("Dumping analytics for all users...")
                
                all_data = {}
                users = User.query.all()
                
                for user in users:
                    user_analytics = AggregatedAnalyticsService.get_all_aggregated_stats(user.id, car_id)
                    all_data[f'user_{user.id}_{user.username}'] = user_analytics
                
                click.echo(f"Processed {len(users)} users")
            
            # Determine output destination
            output_stream = open(output_file, 'w', encoding='utf-8') if output_file else sys.stdout
            
            try:
                if output_format == 'json':
                    # JSON output
                    if pretty:
                        json.dump(all_data, output_stream, indent=2, default=str)
                    else:
                        json.dump(all_data, output_stream, default=str)
                    
                    if output_file:
                        click.echo(f"✅ Analytics dumped to {output_file} (JSON)")
                else:
                    # CSV output - flatten the data
                    writer = csv.writer(output_stream)
                    
                    # Write header
                    header = [
                        'user_key', 'total_sessions', 'total_kwh', 'total_miles', 'total_cost_gbp',
                        'savings_vs_petrol_gbp', 'avg_cost_per_kwh', 'avg_cost_per_mile',
                        'cheapest_session_cost_per_mile', 'most_expensive_session_cost_per_mile',
                        'fastest_session_power_kw', 'slowest_session_power_kw',
                        'most_efficient_session', 'least_efficient_session',
                        'generated_at'
                    ]
                    writer.writerow(header)
                    
                    # Write data rows
                    for user_key, user_data in all_data.items():
                        lifetime = user_data['lifetime_totals']
                        best_worst = user_data['best_worst_sessions']
                        
                        row = [
                            user_key,
                            lifetime['total_sessions'],
                            lifetime['total_kwh'],
                            lifetime['total_miles'],
                            lifetime['total_cost_gbp'],
                            lifetime['savings_vs_petrol_gbp'],
                            lifetime['avg_cost_per_kwh'],
                            lifetime['avg_cost_per_mile'],
                            best_worst['cheapest_per_mile']['cost_per_mile'] if best_worst['cheapest_per_mile'] else '',
                            best_worst['most_expensive_per_mile']['cost_per_mile'] if best_worst['most_expensive_per_mile'] else '',
                            best_worst['fastest_session']['avg_power_kw'] if best_worst['fastest_session'] else '',
                            best_worst['slowest_session']['avg_power_kw'] if best_worst['slowest_session'] else '',
                            best_worst['most_efficient']['efficiency_used'] if best_worst['most_efficient'] else '',
                            best_worst['least_efficient']['efficiency_used'] if best_worst['least_efficient'] else '',
                            user_data['generated_at']
                        ]
                        writer.writerow(row)
                    
                    if output_file:
                        click.echo(f"✅ Analytics dumped to {output_file} (CSV)")
                
            finally:
                if output_file:
                    output_stream.close()
            
        except Exception as e:
            click.echo(f"Error: {str(e)}", err=True)
            exit(1)
    
    return app
