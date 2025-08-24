from routes.auth import auth_bp
from routes.cars import cars_bp
from routes.charging_sessions import charging_sessions_bp
from routes.settings import settings_bp
from routes.dashboard import dashboard_bp
from routes.analytics import analytics_bp
from routes.blend import blend_bp

__all__ = ['auth_bp', 'cars_bp', 'charging_sessions_bp', 'settings_bp', 'dashboard_bp', 'analytics_bp', 'blend_bp']
