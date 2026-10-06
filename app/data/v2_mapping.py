"""Typed V2 records and explicit label normalization; delivery files stay intact."""
import math

FLOAT_FIELDS = {'rent_monthly_sgd', 'rent_monthly_sgd_now', 'area_sqm',
                'mrt_distance_m', 'latitude', 'longitude', 'coord_error_m',
                'pg_school_nearest_walk_m', 'pg_mrt_nearest_walk_m'}
INT_FIELDS = {'bedrooms', 'bathrooms', 'mrt_minutes_reported', 'tenant_count_reported',
              'poi_hawker_1km', 'poi_library_1km', 'poi_sport_1km',
              'poi_healthcare_1km', 'poi_community_1km', 'pg_school_count',
              'pg_school_nearest_walk_min', 'pg_mrt_count', 'poi_fnb_1km'}
LABELS = {
    'cooking_policy': {'light_cooking': 'light_only', 'cooking_any_cooking': 'allowed',
                       'cooking_not_allowed': 'not_allowed', 'cooking_prefer_not_to_say': 'unknown'},
    'pets_policy': {'no_pets': 'not_allowed', 'pets_allowed': 'allowed'},
}


def typed_record(raw):
    record = {}
    for key, value in raw.items():
        if key is None:
            raise ValueError('Unexpected extra CSV values.')
        if key in FLOAT_FIELDS | INT_FIELDS:
            if value is None or value.strip().lower() in ('', 'unknown', 'null', 'nan', 'none'):
                record[key] = None
                continue
            if key == 'coord_error_m' and value.startswith('~'):
                # Preserve the source's approximation marker instead of turning
                # it into an exact measurement.
                if not math.isfinite(float(value[1:])):
                    raise ValueError('Invalid approximate coordinate error.')
                record[key] = value
                continue
            number = float(value)
            if not math.isfinite(number) or (key in INT_FIELDS and not number.is_integer()):
                raise ValueError(f'Invalid numeric field {key} in listing {raw.get("listing_id")}.')
            record[key] = int(number) if key in INT_FIELDS else number
        else:
            # IDs and postcodes remain strings, including leading zeroes.
            record[key] = value
    return record
