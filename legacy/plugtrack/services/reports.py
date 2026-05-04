from models.charging_session import ChargingSession
from models.car import Car
from sqlalchemy import and_
from datetime import datetime
import csv
from io import StringIO

class ReportsService:
    """Service for generating reports and exports"""

    @staticmethod
    def export_sessions_csv(user_id, date_from=None, date_to=None, car_id=None,
                           charge_type=None, charge_network=None):
        """Export charging sessions to CSV with derived metrics"""
        # Build query
        query = ChargingSession.query.filter_by(user_id=user_id)
        
        # Apply filters
        if date_from:
            query = query.filter(ChargingSession.date >= date_from)
        if date_to:
            query = query.filter(ChargingSession.date <= date_to)
        if car_id:
            query = query.filter_by(car_id=car_id)
        if charge_type:
            query = query.filter_by(charge_type=charge_type)
        if charge_network:
            query = query.filter(ChargingSession.charge_network.ilike(f'%{charge_network}%'))
        
        # Get sessions with car data
        sessions = query.join(Car).order_by(ChargingSession.date.desc()).all()
        
        # Create CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Date', 'Car', 'Location', 'Network', 'Type', 'Speed (kW)',
            'Energy (kWh)', 'Duration (mins)', 'Cost per kWh', 'Total Cost',
            'SoC From (%)', 'SoC To (%)', 'Battery Added (%)', 'Notes'
        ])
        
        # Write data rows
        for session in sessions:
            car = session.car
            total_cost = session.charge_delivered_kwh * session.cost_per_kwh
            battery_added = session.soc_to - session.soc_from
            
            writer.writerow([
                session.date.strftime('%Y-%m-%d'),
                car.display_name if car else 'Unknown',
                session.location_label,
                session.charge_network or 'Home',
                session.charge_type,
                f"{session.charge_speed_kw:.1f}",
                f"{session.charge_delivered_kwh:.2f}",
                session.duration_mins,
                f"£{session.cost_per_kwh:.3f}",
                f"£{total_cost:.2f}",
                session.soc_from,
                session.soc_to,
                battery_added,
                session.notes or ''
            ])
        
        return output.getvalue()

    @staticmethod
    def get_export_filename(date_from=None, date_to=None, car_id=None):
        """Generate a descriptive filename for exports"""
        filename_parts = ['plugtrack_sessions']
        
        if date_from:
            filename_parts.append(f"from_{date_from.strftime('%Y%m%d')}")
        if date_to:
            filename_parts.append(f"to_{date_to.strftime('%Y%m%d')}")
        if car_id:
            car = Car.query.get(car_id)
            if car:
                filename_parts.append(f"car_{car.make}_{car.model}".replace(' ', '_'))
        
        filename_parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))
        return f"{'_'.join(filename_parts)}.csv"
