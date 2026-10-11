-- The lease term each advert states, from the 2026-10-09 V2 data: "1 year", "2 years",
-- "Flexible", "Short Term", "Prefer not to say" or empty. The agent reads "1 year" and
-- "2 years" as the shortest lease the landlord accepts.
ALTER TABLE listings
ADD COLUMN IF NOT EXISTS lease_term TEXT;
