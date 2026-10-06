-- =====================================================================
-- Migration 008: Optional PostGIS geospatial support
-- =====================================================================
-- Section 12 says PostGIS "may be used" for geospatial capabilities.
-- The application works correctly WITHOUT this migration — nearby
-- search (Phase 6) can be implemented with the Haversine formula
-- directly on the existing latitude/longitude columns.
--
-- This migration is for students who want to demonstrate PostGIS
-- specifically (ST_DWithin, GIST spatial indexes, etc.) during their
-- viva. It is written defensively: if the PostGIS extension cannot be
-- installed on your PostgreSQL server, this migration prints a notice
-- and exits without breaking the rest of the schema.
--
-- If it succeeds, it adds a `location_point` geography column to
-- `hazards`, backfills it from the existing latitude/longitude values,
-- and keeps it in sync automatically via a trigger.
-- =====================================================================

DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS postgis;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'PostGIS extension is not available on this server. '
                      'Skipping geospatial column — nearby search will '
                      'use latitude/longitude with the Haversine formula '
                      'instead. This is expected and fine for the project.';
        RETURN;
    END;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'hazards' AND column_name = 'location_point'
    ) THEN
        ALTER TABLE hazards
            ADD COLUMN location_point geography(Point, 4326);

        UPDATE hazards
        SET location_point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
        WHERE location_point IS NULL;

        CREATE INDEX idx_hazards_location_point
            ON hazards USING GIST (location_point);
    END IF;
END $$;

-- Keep location_point automatically in sync if latitude/longitude
-- are ever updated directly, so the two representations never drift.
CREATE OR REPLACE FUNCTION sync_hazard_location_point()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'hazards' AND column_name = 'location_point'
    ) THEN
        NEW.location_point = ST_SetSRID(
            ST_MakePoint(NEW.longitude, NEW.latitude), 4326
        )::geography;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_hazards_sync_location_point ON hazards;
CREATE TRIGGER trg_hazards_sync_location_point
    BEFORE INSERT OR UPDATE OF latitude, longitude ON hazards
    FOR EACH ROW
    EXECUTE FUNCTION sync_hazard_location_point();
