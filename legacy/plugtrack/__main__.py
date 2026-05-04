#!/usr/bin/env python3
"""
Entry point for running PlugTrack as a module
Usage: python -m plugtrack
"""

from . import create_app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
