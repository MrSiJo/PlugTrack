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
    
    # Register Phase 4 CLI commands
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
    
    return app
