#!/usr/bin/env python3
"""
WSGI entry point for PlugTrack
"""

import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from __init__ import create_app

app = create_app()

if __name__ == '__main__':
    app.run()
