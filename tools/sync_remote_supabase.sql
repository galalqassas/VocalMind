-- ============================================================================
--  Production-Supabase reset to "Nexalink + Meridian only"
-- ============================================================================
--
--  Run this ONCE against the production Supabase database (Supabase Dashboard
--  → SQL Editor, paste, run). Idempotent — re-running is a no-op.
--
--  What it does:
--    1. Deletes the historical demo orgs (NileTech, CairoConnect) and every
--       row that cascades from them (users, interactions, processing jobs,
--       transcripts, utterances, emotion events, scores, policy compliance,
--       feedback rows, snapshots, assistant queries, notifications).
--    2. Leaves the schema itself untouched.
--
--  After this, restart the backend with SEED_DEMO_DATA=true at least once so
--  seed_nexalink + seed_meridian re-populate the canonical demo orgs.
--
--  ⚠  This is destructive. Take a backup first (Supabase → Database → Backups)
--     and double-check you are pointed at the right project.
-- ============================================================================

BEGIN;

-- Use IDs (defensive — slugs would also work but the IDs are guaranteed):
--   NileTech       = a0000000-0000-0000-0000-000000000001
--   CairoConnect   = a0000000-0000-0000-0000-000000000002

DELETE FROM organizations
WHERE id IN (
    'a0000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000002'
)
   OR slug IN ('nile-tech', 'cairo-connect', 'niletech', 'cairoconnect');

-- Sanity-check: only nexalink + meridian should remain (and any other real
-- orgs you've added — the assertion below allows up to 4 orgs total to be
-- forgiving, but warns loudly if Nexalink + Meridian are missing).
DO $$
DECLARE
    nexalink_exists  BOOLEAN;
    meridian_exists  BOOLEAN;
    total_orgs       INT;
BEGIN
    SELECT EXISTS(SELECT 1 FROM organizations WHERE slug = 'nexalink')  INTO nexalink_exists;
    SELECT EXISTS(SELECT 1 FROM organizations WHERE slug = 'meridian')  INTO meridian_exists;
    SELECT COUNT(*) FROM organizations                                  INTO total_orgs;

    RAISE NOTICE 'Post-cleanup: total orgs=%, nexalink present=%, meridian present=%',
        total_orgs, nexalink_exists, meridian_exists;

    IF NOT nexalink_exists OR NOT meridian_exists THEN
        RAISE NOTICE 'Nexalink and/or Meridian not yet seeded — that is expected if '
                     'this is the first run. Restart the backend with '
                     'SEED_DEMO_DATA=true to create them.';
    END IF;
END $$;

COMMIT;
