-- Migration: Add indexes for efficiency calculations
-- Date: 2024-01-XX
-- Description: Add composite indexes to speed up efficiency calculations and odometer lookups

-- Composite index for fast anchor/kWh window scans
CREATE INDEX IF NOT EXISTS idx_cs_user_car_date_id
ON charging_session(user_id, car_id, date, id);

-- Odometer searches for efficiency calculations
CREATE INDEX IF NOT EXISTS idx_cs_user_car_odo
ON charging_session(user_id, car_id, odometer);

-- Note: These indexes will improve performance for:
-- 1. Finding previous odometer anchors within 30-day horizon
-- 2. Summing kWh in the window between anchors
-- 3. Daily efficiency calculations with bounded anchors
