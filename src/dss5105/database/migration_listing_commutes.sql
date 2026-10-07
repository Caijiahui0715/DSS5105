CREATE TABLE listing_commutes (
    listing_id TEXT NOT NULL,
    destination_id TEXT NOT NULL,

    travel_mode TEXT NOT NULL,

    distance_m INTEGER,
    duration_min NUMERIC(10, 2),

    route_provider TEXT NOT NULL DEFAULT 'onemap',

    calculated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        listing_id,
        destination_id,
        travel_mode
    ),

    CONSTRAINT fk_commute_listing
        FOREIGN KEY (listing_id)
        REFERENCES listings(listing_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_commute_destination
        FOREIGN KEY (destination_id)
        REFERENCES nus_destinations(destination_id)
        ON DELETE CASCADE
);


CREATE INDEX idx_listing_commutes_listing
    ON listing_commutes(listing_id);


CREATE INDEX idx_listing_commutes_destination
    ON listing_commutes(destination_id);


CREATE INDEX idx_listing_commutes_duration
    ON listing_commutes(duration_min);