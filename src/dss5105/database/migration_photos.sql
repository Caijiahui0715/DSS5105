-- 2026-10-23: the listing's photos from the V2 data, up to six links on PropertyGuru's image CDN
-- (sg1-cdn.pgimgs.com): the home's own, then the development's. Listing cards show them from
-- these links; the pictures themselves are not stored.
ALTER TABLE listings
ADD COLUMN IF NOT EXISTS photos TEXT[];
