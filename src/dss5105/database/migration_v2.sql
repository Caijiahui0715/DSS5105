ALTER TABLE listings
ADD COLUMN rent_monthly_sgd_now NUMERIC(10, 2);

ALTER TABLE listings
ADD COLUMN scrape_status TEXT NOT NULL DEFAULT 'unknown';

CREATE TABLE listing_enrichment (
    listing_id TEXT PRIMARY KEY,

    enriched_at TIMESTAMP,
    postcode VARCHAR(10),
    street_name TEXT,

    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,

    poi_hawker_1km INTEGER,
    poi_library_1km INTEGER,
    poi_sport_1km INTEGER,
    poi_healthcare_1km INTEGER,
    poi_community_1km INTEGER,
    poi_fnb_1km INTEGER,

    pg_school_count INTEGER,
    pg_school_nearest_walk_m NUMERIC(10, 2),
    pg_school_nearest_walk_min NUMERIC(10, 2),

    pg_mrt_count INTEGER,
    pg_mrt_nearest_walk_m NUMERIC(10, 2),

    coord_source TEXT,
    coord_error_m NUMERIC(10, 2),

    CONSTRAINT fk_enrichment_listing
        FOREIGN KEY (listing_id)
        REFERENCES listings(listing_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_listings_scrape_status
    ON listings(scrape_status);

CREATE INDEX idx_listings_current_rent
    ON listings(rent_monthly_sgd_now);

CREATE INDEX idx_enrichment_postcode
    ON listing_enrichment(postcode);

CREATE INDEX idx_enrichment_coordinates
    ON listing_enrichment(latitude, longitude);