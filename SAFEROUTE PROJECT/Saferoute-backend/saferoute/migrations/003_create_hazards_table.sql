-- =====================================================================
-- Migration 003: Hazards table
-- =====================================================================
-- Implements sections 6-11 and 22 (Hazard Management, Severity, Status,
-- Visibility, Location, Duplicate Detection) of the project brief.
--
-- IMPORTANT DESIGN DECISIONS:
--
-- 1. `status` vs `visibility` are kept as TWO SEPARATE columns, per
--    section 9. `status` tracks the verification lifecycle; `visibility`
--    tracks whether the public API is allowed to show it (an admin can
--    hide even a verified hazard).
--
-- 2. Duplicate detection (section 22) is modeled with
--    `is_potential_duplicate` + `duplicate_of_hazard_id`, rather than
--    folding "duplicate" into the status enum. This keeps the lifecycle
--    enum clean (Reported -> Under Review -> Verified/Rejected ->
--    Resolved/Expired) while still letting the backend flag a report
--    as a likely duplicate of another hazard WITHOUT deleting it.
--
-- 3. Latitude/longitude are stored as plain NUMERIC columns so the
--    project works with plain PostgreSQL out of the box. Migration 007
--    optionally adds a PostGIS `geography` column on top of these for
--    students who have PostGIS installed and want to demonstrate
--    spatial indexing (ST_DWithin, etc.).
-- =====================================================================

CREATE TYPE hazard_type AS ENUM (
    'road_closure',
    'flooding',
    'waterlogging',
    'construction',
    'blocked_road',
    'accident',
    'temporary_restriction',
    'other'
);

CREATE TYPE hazard_severity AS ENUM ('low', 'medium', 'high', 'critical');

-- Verification / lifecycle status (section 8, section 10).
CREATE TYPE hazard_status AS ENUM (
    'reported',
    'under_review',
    'verified',
    'rejected',
    'resolved',
    'expired'
);

-- Public visibility, independent of verification status (section 9).
CREATE TYPE hazard_visibility AS ENUM ('visible', 'hidden');

CREATE TABLE hazards (
    id                      BIGSERIAL PRIMARY KEY,
    reporter_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    hazard_type             hazard_type NOT NULL,
    title                   VARCHAR(150) NOT NULL,
    description             TEXT NOT NULL,

    -- Location (section 11)
    address                 VARCHAR(255),
    city                    VARCHAR(100),
    latitude                NUMERIC(9,6) NOT NULL,
    longitude               NUMERIC(9,6) NOT NULL,

    severity                hazard_severity NOT NULL,

    start_time              TIMESTAMPTZ NOT NULL,
    expected_end_time       TIMESTAMPTZ,

    status                  hazard_status NOT NULL DEFAULT 'reported',
    visibility              hazard_visibility NOT NULL DEFAULT 'hidden',

    -- Duplicate detection (section 22) — see design note above.
    is_potential_duplicate  BOOLEAN NOT NULL DEFAULT FALSE,
    duplicate_of_hazard_id  BIGINT REFERENCES hazards(id) ON DELETE SET NULL,

    -- Verification (section 23) — the detailed history lives in
    -- hazard_verification_history (migration 004); these columns just
    -- cache the *latest* decision for quick lookups.
    verified_by             BIGINT REFERENCES users(id) ON DELETE SET NULL,
    verified_at             TIMESTAMPTZ,
    verification_note       TEXT,

    -- Resolution (section 25)
    resolved_by             BIGINT REFERENCES users(id) ON DELETE SET NULL,
    resolved_at             TIMESTAMPTZ,
    resolution_note         TEXT,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Section 11: validate coordinate ranges at the database level too,
    -- as a last line of defense behind the Flask-level validation.
    CONSTRAINT chk_latitude_range CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT chk_longitude_range CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT chk_expected_end_after_start
        CHECK (expected_end_time IS NULL OR expected_end_time > start_time)
);

-- Indexes to support common query patterns (sections 13-14):
CREATE INDEX idx_hazards_status ON hazards (status);
CREATE INDEX idx_hazards_visibility ON hazards (visibility);
CREATE INDEX idx_hazards_type ON hazards (hazard_type);
CREATE INDEX idx_hazards_severity ON hazards (severity);
CREATE INDEX idx_hazards_city ON hazards (city);
CREATE INDEX idx_hazards_reporter_id ON hazards (reporter_id);
CREATE INDEX idx_hazards_lat_lng ON hazards (latitude, longitude);
-- Speeds up "GET /api/hazards?type=flooding&severity=high" style queries
-- against only the hazards normal users are allowed to see:
CREATE INDEX idx_hazards_public_listing
    ON hazards (status, visibility)
    WHERE status = 'verified' AND visibility = 'visible';

CREATE TRIGGER trg_hazards_updated_at
    BEFORE UPDATE ON hazards
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();
