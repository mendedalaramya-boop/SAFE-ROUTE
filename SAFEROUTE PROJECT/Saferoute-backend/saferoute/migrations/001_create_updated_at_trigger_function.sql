-- =====================================================================
-- Migration 001: Shared "updated_at" trigger function
-- =====================================================================
-- Several tables (users, hazards) need an `updated_at` timestamp that
-- refreshes automatically whenever a row is modified. Rather than
-- updating this manually in every SQL UPDATE statement (easy to
-- forget), we define one trigger function here and attach it to each
-- relevant table in later migrations.
-- =====================================================================

CREATE OR REPLACE FUNCTION set_updated_at_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
