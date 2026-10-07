CREATE TABLE nus_destinations (
    destination_id TEXT PRIMARY KEY,

    faculty_code TEXT NOT NULL UNIQUE,
    faculty_name TEXT NOT NULL,

    destination_name TEXT NOT NULL,

    address TEXT NOT NULL,
    postal_code VARCHAR(10),

    campus_area TEXT,

    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,

    is_default BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_nus_destinations_faculty
    ON nus_destinations(faculty_code);