import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')  # Must be set in environment
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///plugtrack.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Global debug flag for development features
    DEBUG_REMINDERS = os.environ.get('DEBUG_REMINDERS', 'False').lower() == 'true'
    DEBUG_INSIGHTS = os.environ.get('DEBUG_INSIGHTS', 'False').lower() == 'true'
    
    @classmethod
    def init_app(cls, app):
        """Initialize configuration after app creation"""
        # Ensure environment variables are loaded
        load_dotenv()
        
        # Get database URL and fix path resolution issues
        db_url = os.environ.get('DATABASE_URL') or 'sqlite:///plugtrack.db'
        
        # Fix SQLite path resolution issues
        if db_url.startswith('sqlite:///'):
            db_path = db_url.replace('sqlite:///', '')
            if not os.path.isabs(db_path):
                # Resolve relative path correctly
                resolved_path = os.path.abspath(db_path)
                db_url = f'sqlite:///{resolved_path}'
        
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
        app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
