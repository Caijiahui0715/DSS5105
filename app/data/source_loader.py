import json
import csv
from pathlib import Path
import streamlit as st
from adapters.backend_mapper import BackendMapper
from data.v2_mapping import typed_record

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPOSITORY_ROOT / 'output-final-delivery'
SOURCE_FILES = ('rental_data_v1.json', 'source_evidence_v1.json', 'field_dictionary_v1.json',
                'validation_report.json', 'rental_data_v2.csv', 'removed_listings.csv')

def read_sources(root=DATA_ROOT):
    try:
        values = {name: json.loads((root / name).read_text(encoding='utf-8')) for name in ('rental_data_v1.json', 'source_evidence_v1.json', 'field_dictionary_v1.json', 'validation_report.json')}
        rental = values['rental_data_v1.json']
        if rental.get('schema_version') != '1.0':
            raise ValueError('Expected V1 data schema 1.0.')
        rows, metadata, districts = rental['listings'], rental['listing_metadata'], rental['district_lookup']
        evidence = values['source_evidence_v1.json']
        ids = [str(row['listing_id']) for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate listing IDs in source data.')
        meta = {str(row['listing_id']): row for row in metadata}
        dist = {row['district_code']: row for row in districts}
        ev = {str(row['listing_id']): row for row in evidence}
        if len(meta) != len(metadata) or len(dist) != len(districts) or len(ev) != len(evidence):
            raise ValueError('Duplicate source join keys.')
        with (root / 'rental_data_v2.csv').open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            required = {'listing_id', 'rent_monthly_sgd', 'rent_monthly_sgd_now',
                        'scrape_status', 'enriched_at', 'latitude', 'longitude', 'coord_source'}
            if not required <= set(reader.fieldnames or []):
                raise ValueError('Missing required V2 columns.')
            latest = [typed_record(row) for row in reader]
        with (root / 'removed_listings.csv').open(encoding='utf-8-sig', newline='') as handle:
            removed = {row['listing_id'] for row in csv.DictReader(handle)}
        latest_ids = [row['listing_id'] for row in latest]
        if len(latest_ids) != len(set(latest_ids)):
            raise ValueError('Duplicate V2 listing IDs.')
        for row in latest:
            if row['listing_id'] not in meta or row['listing_id'] not in ev:
                raise ValueError(f'V2 listing {row["listing_id"]} has no V1 evidence/metadata join.')
            if row['district_code'] not in dist:
                raise ValueError('V2 listing has no district join.')
            rent = row['rent_monthly_sgd_now']
            if rent is not None and rent <= 0:
                raise ValueError('Refreshed monthly rent must be positive.')
        active = [row for row in latest if row['scrape_status'] == 'active' and row['listing_id'] not in removed]
        if not active:
            raise ValueError('No active V2 listings. Refusing to fall back to stale V1 listings.')
        listings = [BackendMapper.listing(row, meta[row['listing_id']], dist[row['district_code']], ev[row['listing_id']]) for row in active]
        snapshot = {'dataset': 'V2', 'active_count': len(active), 'historical_v1_count': len(rows),
                    'removed_count': len(removed), 'checked_at': sorted({row['enriched_at'] for row in active if row.get('enriched_at')}),
                    'coordinates_count': sum(l.provenance['coordinates'] != 'unavailable' for l in listings),
                    'inferred_coordinates_count': sum(l.provenance['coordinates'] == 'derived' for l in listings)}
        return {'listings': listings, 'metadata': [meta[row['listing_id']] for row in active], 'districts': districts,
                'dictionary': values['field_dictionary_v1.json'], 'validation': values['validation_report.json'], 'snapshot': snapshot}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'Unable to load required rental data. Check V2 CSV, removed listings, and V1 evidence/metadata joins. {exc}') from exc

@st.cache_data(show_spinner='Loading source rental listings…')
def _cached_sources(source_version, domain_revision=3):
    sources = read_sources()
    sources['source_version'] = source_version
    return sources


def load_sources():
    # New delivery snapshots invalidate the cache without a manual cache clear.
    try:
        version = tuple((name, (DATA_ROOT / name).stat().st_mtime_ns, (DATA_ROOT / name).stat().st_size) for name in SOURCE_FILES)
    except OSError as exc:
        raise ValueError(f'Unable to load required rental data: {exc}') from exc
    return _cached_sources(version)
