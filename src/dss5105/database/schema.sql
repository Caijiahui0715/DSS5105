-- =========================================================
-- DSS5105 Singapore Rental Decision Agent
-- Database Schema V1
-- =========================================================


-- ---------------------------------------------------------
-- 1. District lookup
-- ---------------------------------------------------------

CREATE TABLE district_lookup (
    district_code VARCHAR(3) PRIMARY KEY,
    district TEXT NOT NULL
);


-- ---------------------------------------------------------
-- 2. Main rental listings
-- ---------------------------------------------------------

CREATE TABLE listings (
    listing_id TEXT PRIMARY KEY,

    title TEXT NOT NULL,
    listing_url TEXT NOT NULL UNIQUE,

    rent_monthly_sgd NUMERIC(10, 2) NOT NULL,
    rent_price_type TEXT NOT NULL,

    rental_scope TEXT NOT NULL,
    room_type TEXT NOT NULL,
    property_type TEXT NOT NULL,

    bedrooms SMALLINT,
    bathrooms SMALLINT,

    area_sqm NUMERIC(10, 2),
    area_scope TEXT NOT NULL,

    district_code VARCHAR(3) NOT NULL,
    address TEXT NOT NULL,

    mrt_station TEXT NOT NULL,
    mrt_distance_m NUMERIC(10, 2),
    mrt_minutes_reported SMALLINT,
    mrt_operation_status TEXT NOT NULL,

    listed_date DATE NOT NULL,
    collected_at TIMESTAMP NOT NULL,

    tenant_count_reported SMALLINT,
    tenant_gender_label TEXT NOT NULL,

    gender_restriction TEXT NOT NULL,
    gender_preference TEXT NOT NULL,

    cooking_policy TEXT NOT NULL,
    furnishing TEXT NOT NULL,

    landlord_lives_in TEXT NOT NULL,
    private_bathroom TEXT NOT NULL,
    air_conditioning TEXT NOT NULL,
    pets_policy TEXT NOT NULL,

    CONSTRAINT fk_listings_district
        FOREIGN KEY (district_code)
        REFERENCES district_lookup(district_code)
);


-- ---------------------------------------------------------
-- 3. Data quality / metadata
-- ---------------------------------------------------------

CREATE TABLE listing_metadata (
    listing_id TEXT PRIMARY KEY,

    availability_status TEXT NOT NULL,

    review_flags TEXT[] NOT NULL,

    CONSTRAINT fk_metadata_listing
        FOREIGN KEY (listing_id)
        REFERENCES listings(listing_id)
        ON DELETE CASCADE
);


-- ---------------------------------------------------------
-- 4. Useful indexes for retrieval
-- ---------------------------------------------------------

CREATE INDEX idx_listings_rent
    ON listings(rent_monthly_sgd);

CREATE INDEX idx_listings_district
    ON listings(district_code);

CREATE INDEX idx_listings_rental_scope
    ON listings(rental_scope);

CREATE INDEX idx_listings_property_type
    ON listings(property_type);

CREATE INDEX idx_listings_bedrooms
    ON listings(bedrooms);

CREATE INDEX idx_listings_mrt_station
    ON listings(mrt_station);

CREATE INDEX idx_listings_listed_date
    ON listings(listed_date);