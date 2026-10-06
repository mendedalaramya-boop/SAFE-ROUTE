-- =====================================================================
-- Migration 007: Route searches (optional history table)
-- =====================================================================
-- Section 32 marks `route_searches` as optional — routes don't have to
-- be permanently stored. We include it because it's useful later for:
--   - Debugging route/hazard matching (section 18)
--   - Reporting ("most searched areas")
--   - Detecting repeated searches near an active hazard
--
-- `user_id` is nullable to allow anonymous/unauthenticated route
-- lookups if the product decision in a later phase allows that.
-- =====================================================================

CREATE TABLE route_searches (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT REFERENCES users(id) ON DELETE SET NULL,

    origin_latitude     NUMERIC(9,6) NOT NULL,
    origin_longitude    NUMERIC(9,6) NOT NULL,
    destination_latitude  NUMERIC(9,6) NOT NULL,
    destination_longitude NUMERIC(9,6) NOT NULL,

    distance_km         NUMERIC(10,2),
    duration_minutes    NUMERIC(10,2),
    hazards_found_count INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_origin_lat_range CHECK (origin_latitude BETWEEN -90 AND 90),
    CONSTRAINT chk_origin_lng_range CHECK (origin_longitude BETWEEN -180 AND 180),
    CONSTRAINT chk_dest_lat_range CHECK (destination_latitude BETWEEN -90 AND 90),
    CONSTRAINT chk_dest_lng_range CHECK (destination_longitude BETWEEN -180 AND 180)
);

CREATE INDEX idx_route_searches_user_id ON route_searches (user_id);
CREATE INDEX idx_route_searches_created_at ON route_searches (created_at DESC);
