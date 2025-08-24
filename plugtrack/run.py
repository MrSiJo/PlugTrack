from plugtrack import create_app, db
from plugtrack.models import User, Car, ChargingSession, Settings
from datetime import date, datetime

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

if __name__ == '__main__':
    app.run(debug=True)
