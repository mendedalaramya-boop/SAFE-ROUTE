-- =====================================================================
-- Migration 006: Audit logs table
-- =====================================================================
-- Implements section 29 (Audit Logging). This is a general-purpose,
-- append-only trail of important actions across the whole platform
-- (registration, login, hazard creation/update, verification,
-- rejection, hiding, resolution, admin actions) — broader in scope
-- than hazard_verification_history, which only covers verification
-- decisions specifically.
--
-- `user_id` is nullable so that system-level events (or events from a
-- since-deleted user) can still be recorded without breaking the
-- foreign key.
-- =====================================================================

CREATE TABLE audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,

    action          VARCHAR(100) NOT NULL,      -- e.g. 'HAZARD_VERIFIED'
    resource_type   VARCHAR(50)  NOT NULL,      -- e.g. 'hazard', 'user'
    resource_id     BIGINT,                     -- id of the affected row
    description     TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_user_id ON audit_logs (user_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs (resource_type, resource_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs (created_at DESC);

-- Section 29: "Normal users must not be able to modify audit records."
-- This is primarily enforced at the application layer (no UPDATE/DELETE
-- endpoint will ever be exposed for this table), but revoking those
-- privileges from the application's database role is good defense in
-- depth. Uncomment and adjust the role name if you created a dedicated
-- least-privilege role for the running application:
--
-- REVOKE UPDATE, DELETE ON audit_logs FROM saferoute_user;
