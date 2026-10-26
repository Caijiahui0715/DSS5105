-- 2026-10-10: since the data grew to Sentosa Cove and the city centre, some listings have no MRT nearby,
-- so the four mrt_* columns allow NULL ("no MRT nearby" is a fact, not missing data).
-- Guarded with to_regclass: skipped in the test database (<DB_NAME>_test), which has no public.listings.
DO $$
BEGIN
  IF to_regclass('public.listings') IS NOT NULL THEN
    ALTER TABLE public.listings ALTER COLUMN mrt_station DROP NOT NULL;
    ALTER TABLE public.listings ALTER COLUMN mrt_distance_m DROP NOT NULL;
    ALTER TABLE public.listings ALTER COLUMN mrt_minutes_reported DROP NOT NULL;
    ALTER TABLE public.listings ALTER COLUMN mrt_operation_status DROP NOT NULL;
  END IF;
END $$;
