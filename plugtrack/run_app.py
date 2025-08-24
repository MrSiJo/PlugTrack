#!/usr/bin/env python3
"""
Simple Flask application launcher for PlugTrack
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to Python path so absolute imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Now import the Flask app
from __init__ import create_app

if __name__ == '__main__':
    app = create_app()
    
    # Set default port and host
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '127.0.0.1')
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    print(f"Starting PlugTrack on http://{host}:{port}")
    print(f"Debug mode: {debug}")
    print("Press Ctrl+C to stop the server")
    
    app.run(host=host, port=port, debug=debug)
