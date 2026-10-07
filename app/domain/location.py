"""Source-backed map coordinates, independent of demonstration commute values."""
import math


def coordinates(listing):
    lat, lon = listing.facts.get('latitude'), listing.facts.get('longitude')
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def location_note(listing):
    source = listing.facts.get('coordSource') or 'Not provided'
    if listing.provenance.get('coordinates') == 'derived':
        error = listing.facts.get('coordErrorM')
        return f'Approximate inferred location · {source}' + (f' · estimated error {error} m' if error is not None else '')
    return f'Data location · {source} · not independently verified'
