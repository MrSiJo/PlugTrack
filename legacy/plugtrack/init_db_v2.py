#!/usr/bin/env python3
"""
Modern database initialization system for PlugTrack
Handles both fresh installations and incremental migrations
"""

import os
import sys
from datetime import date

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app, db
from models import User, Car, ChargingSession, Settings
from migrations.migration_manager import MigrationManager


def init_database(dry_run: bool = False, force_fresh: bool = False):
    """
    Initialize or migrate the PlugTrack database.
    
    Args:
        dry_run: If True, show what would be done without making changes
        force_fresh: If True, treat as fresh install even if data exists
    """
    app = create_app()
    
    with app.app_context():
        migration_manager = MigrationManager(app)
        
        print("🚀 PlugTrack Database Initialization")
        print("=" * 50)
        
        # Check database state
        is_fresh = migration_manager.is_fresh_database() or force_fresh
        
        if is_fresh:
            print("📦 Fresh database detected - performing complete setup")
        else:
            print("🔄 Existing database detected - checking for migrations")
        
        # Get migration status
        status = migration_manager.get_migration_status()
        print(f"Migration Status:")
        print(f"  • Applied: {status['applied_count']}")
        print(f"  • Available: {status['available_count']}")
        print(f"  • Pending: {status['pending_count']}")
        
        if status['last_applied']:
            print(f"  • Last applied: {status['last_applied']}")
        
        # Apply migrations
        if status['pending_count'] > 0:
            print(f"\n📋 Pending migrations: {', '.join(status['pending_migrations'])}")
            
            if not dry_run:
                success = migration_manager.apply_all_pending(dry_run=False)
                if not success:
                    print("❌ Migration failed! Database may be in inconsistent state.")
                    return False
            else:
                print("[DRY RUN] Would apply pending migrations")
        else:
            print("✅ All migrations are up to date")
        
        # Create demo data for fresh installations
        if is_fresh and not dry_run:
            create_demo_data()
        elif is_fresh and dry_run:
            print("[DRY RUN] Would create demo data")
        
        # Initialize baselines for existing data
        if not is_fresh and not dry_run:
            initialize_baseline_sessions()
        elif not is_fresh and dry_run:
            print("[DRY RUN] Would initialize baseline sessions")
        
        print("\n✅ Database initialization completed successfully!")
        return True


def create_demo_data():
    """Create demo user, car, and sample charging session."""
    print("\n👤 Creating demo data...")
    
    # Check if we already have users
    if User.query.first() is not None:
        print("Users already exist - skipping demo data creation")
        return
    
    try:
        # Create demo user
        user = User(username='demo')
        user.set_password('demo123')
        db.session.add(user)
        db.session.flush()  # Get the user ID
        
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
        db.session.flush()  # Get the car ID
        
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
            ambient_temp_c=18.5,
            preconditioning_used=False,
            preconditioning_events=0,
            notes='Demo charging session - evening charge at home'
        )
        db.session.add(session)
        
        db.session.commit()
        
        print('✅ Demo data created:')
        print(f'   Username: demo')
        print(f'   Password: demo123')
        print(f'   Car: {car.display_name}')
        print(f'   Sessions: 1 sample session')
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creating demo data: {e}")
        raise


def initialize_baseline_sessions():
    """Initialize baseline flags for existing charging sessions."""
    print("\n🎯 Initializing baseline sessions...")
    
    try:
        from services.baseline_manager import BaselineManager
        
        # Get all users with charging sessions
        users_with_sessions = db.session.query(User.id, User.username).join(
            ChargingSession
        ).distinct().all()
        
        baseline_count = 0
        for user_id, username in users_with_sessions:
            BaselineManager.initialize_all_baselines(user_id)
            # Count baseline sessions for this user
            user_baselines = ChargingSession.query.filter_by(user_id=user_id, is_baseline=True).count()
            baseline_count += user_baselines
            print(f"   ✓ User {username}: {user_baselines} baseline sessions")
        
        print(f"✅ Initialized {baseline_count} baseline sessions")
        
    except ImportError:
        print("⚠️  BaselineManager not available - skipping baseline initialization")
    except Exception as e:
        print(f"⚠️  Error initializing baselines: {e}")


def migration_status():
    """Show detailed migration status."""
    app = create_app()
    
    with app.app_context():
        migration_manager = MigrationManager(app)
        status = migration_manager.get_migration_status()
        
        print("📊 Migration Status Report")
        print("=" * 30)
        print(f"Applied migrations: {status['applied_count']}")
        print(f"Available migrations: {status['available_count']}")
        print(f"Pending migrations: {status['pending_count']}")
        
        if status['applied_migrations']:
            print(f"\nApplied migrations:")
            for migration_id in status['applied_migrations']:
                print(f"  ✅ {migration_id}")
        
        if status['pending_migrations']:
            print(f"\nPending migrations:")
            for migration_id in status['pending_migrations']:
                print(f"  ⏳ {migration_id}")
        
        if status['last_applied']:
            print(f"\nLast applied: {status['last_applied']}")


def create_migration(migration_id: str, description: str):
    """Create a new migration file."""
    from migrations.migration_manager import create_migration_template
    
    # Ensure migrations/versions directory exists
    versions_dir = os.path.join(os.path.dirname(__file__), 'migrations', 'versions')
    os.makedirs(versions_dir, exist_ok=True)
    
    # Create migration file
    filename = f"{migration_id}_{description.lower().replace(' ', '_')}.py"
    filepath = os.path.join(versions_dir, filename)
    
    if os.path.exists(filepath):
        print(f"❌ Migration file already exists: {filepath}")
        return False
    
    template = create_migration_template(migration_id, description)
    
    with open(filepath, 'w') as f:
        f.write(template)
    
    print(f"✅ Created migration: {filepath}")
    print(f"📝 Edit the file to add your migration logic")
    return True


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='PlugTrack Database Management')
    parser.add_argument('command', choices=['init', 'status', 'create-migration'], 
                       help='Command to execute')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be done without making changes')
    parser.add_argument('--force-fresh', action='store_true',
                       help='Treat as fresh install even if data exists')
    parser.add_argument('--migration-id', type=str,
                       help='Migration ID for create-migration command')
    parser.add_argument('--description', type=str,
                       help='Migration description for create-migration command')
    
    args = parser.parse_args()
    
    if args.command == 'init':
        success = init_database(dry_run=args.dry_run, force_fresh=args.force_fresh)
        sys.exit(0 if success else 1)
    
    elif args.command == 'status':
        migration_status()
    
    elif args.command == 'create-migration':
        if not args.migration_id or not args.description:
            print("❌ --migration-id and --description are required for create-migration")
            sys.exit(1)
        success = create_migration(args.migration_id, args.description)
        sys.exit(0 if success else 1)
