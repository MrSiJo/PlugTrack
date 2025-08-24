from flask import Flask
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config
from models.user import db, User

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
    
    return app
