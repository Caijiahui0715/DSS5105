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
    from content.i18n import t
    source = listing.facts.get('coordSource') or t('Not provided', '未提供')
    if listing.provenance.get('coordinates') == 'derived':
        error = listing.facts.get('coordErrorM')
        return t(f'Approximate inferred location · {source}', f'推断的大致位置 · {source}') + (t(f' · estimated error {error} m', f' · 估计误差 {error} 米') if error is not None else '')
    return t(f'Data location · {source} · not independently verified', f'数据中的位置 · {source} · 未独立核实')
