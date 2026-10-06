-- =====================================================================
-- Migration 004: Hazard verification history
-- =====================================================================
-- Implements section 24 (Verification History). Every time an
-- administrator changes a hazard's status (Reported -> Under Review,
-- Under Review -> Verified/Rejected, Verified -> Resolved/Expired,
-- etc.) we INSERT a new row here. We NEVER update or delete existing
-- rows — this table is an append-only audit trail specifically for
-- verification decisions, giving full accountability for "who decided
-- what, and when."
--
-- (General-purpose audit logging for all actions, not just
-- verification, is handled separately in migration 006: audit_logs.)
-- =====================================================================

CREATE TABLE hazard_verification_history (
    id                  BIGSERIAL PRIMARY KEY,
    hazard_id           BIGINT NOT NULL REFERENCES hazards(id) ON DELETE CASCADE,
    admin_id            BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    previous_status     hazard_status NOT NULL,
    new_status          hazard_status NOT NULL,
    verification_note   TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_verification_history_hazard_id
    ON hazard_verification_history (hazard_id);
CREATE INDEX idx_verification_history_admin_id
    ON hazard_verification_history (admin_id);
