-- =====================================================================
-- Migration 002: Users table
-- =====================================================================
-- Implements section 5 (User Management) and section 3 (User Roles)
-- of the project brief. We use PostgreSQL native ENUM types for
-- `role` and `account_status` so the database itself rejects invalid
-- values, in addition to any validation done in the Flask layer.
--
-- Roles:
--   user      -> can report hazards, view verified hazards, search routes
--   reporter  -> a "trusted"/authorized reporter (extra reporting privileges)
--   admin     -> can verify/reject/hide/resolve hazards, manage users
--
-- We never store plain-text passwords — only `password_hash`.
-- =====================================================================

CREATE TYPE user_role AS ENUM ('user', 'reporter', 'admin');

CREATE TYPE account_status AS ENUM ('active', 'suspended', 'deactivated');

CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(120)    NOT NULL,
    email           VARCHAR(255)    NOT NULL UNIQUE,
    password_hash   VARCHAR(255)    NOT NULL,
    role            user_role       NOT NULL DEFAULT 'user',
    account_status  account_status  NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Case-insensitive lookups (login by email) are extremely common,
-- so we index a lowercased copy of the email as well.
CREATE INDEX idx_users_email_lower ON users (LOWER(email));
CREATE INDEX idx_users_role ON users (role);

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at_timestamp();
