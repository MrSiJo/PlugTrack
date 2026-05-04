#!/usr/bin/env python3
"""
Migration 004: Phase 6 Backend - Stages A & B
Created: 2024-12-21 Analytics aggregation API endpoints and services
"""

import sys
import os

# Add the parent directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from models.user import db
from sqlalchemy import text


def upgrade():
    """Apply Phase 6 Backend Stages A & B."""
    print("Applying migration 004: Phase 6 Backend - Stages A & B")
    
    # This migration primarily adds backend services and API endpoints
    # No database schema changes are required for Stages A & B
    
    print("✅ Phase 6 Backend Stages A & B features added:")
    print("   • Analytics aggregation service (analytics_agg.py)")
    print("   • /api/analytics/summary endpoint - weighted efficiency, lifetime totals, cost extremes")
    print("   • /api/analytics/seasonal endpoint - efficiency vs ambient temperature bins")
    print("   • /api/analytics/leaderboard endpoint - per-location metrics")
    print("   • /api/analytics/sweetspot endpoint - SoC window efficiencies")
    print("   • Support for P6-1 API Endpoints requirement")
    print("   • Support for P6-5 Leaderboards & Seasonal requirement")
    
    # No database operations needed for this migration
    db.session.commit()


def downgrade():
    """Rollback Phase 6 Backend Stages A & B."""
    print("Rolling back migration 004: Phase 6 Backend - Stages A & B")
    
    # This migration only added services and API endpoints
    # No database schema changes to rollback
    print("✅ Phase 6 Backend Stages A & B rollback completed")
    print("   Note: API endpoints and services would need to be manually removed from code")
    
    db.session.commit()


# Migration metadata
MIGRATION_ID = "004"
DESCRIPTION = "Phase 6 Backend - Stages A & B (Analytics aggregation API endpoints)"
DEPENDENCIES = ["003"]


if __name__ == "__main__":
    from __init__ import create_app
    
    app = create_app()
    with app.app_context():
        upgrade()
