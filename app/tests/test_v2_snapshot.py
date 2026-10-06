import csv
import json
from dataclasses import replace

import pytest
from adapters.backend_mapper import BackendMapper
from data.source_loader import DATA_ROOT, read_sources
from data.v2_mapping import typed_record
from domain.location import coordinates, location_note
from domain.models import RentalRequirements, RentalPreferences
from domain.recommendation import evaluate, recommend


def test_removed_listings_never_recommended(sources):
    with (DATA_ROOT / 'removed_listings.csv').open(encoding='utf-8-sig', newline='') as handle:
        removed = {row['listing_id'] for row in csv.DictReader(handle)}
    assert not removed & {listing.id for listing in sources['listings']}
    recs = recommend(sources['listings'], RentalRequirements(None, None, None), RentalPreferences())
    assert len(recs) == 376
    assert not removed & {rec.listing_id for rec in recs}


def test_refreshed_price_changes_budget_decision(sources):
    listing = next(l for l in sources['listings'] if l.id == '25604246')
    assert listing.facts['rentMonthlySgd'] == 5700
    assert listing.facts['rentMonthlySgdNow'] == 5500
    assert listing.facts['effectiveRentMonthlySgd'] == 5500
    assert evaluate(listing, RentalRequirements(5600, None, None)).status == 'pass'
    assert evaluate(listing, RentalRequirements(5499, None, None)).status == 'fail'


def test_original_price_fallback_is_explicit(sources):
    listing = sources['listings'][0]
    row = {**listing.source_fields, 'rent_monthly_sgd_now': None}
    mapped = BackendMapper.listing(row, {'availability_status':'unknown', 'review_flags':[]}, {'district':'Test'}, {})
    assert mapped.facts['effectiveRentMonthlySgd'] == row['rent_monthly_sgd']
    assert mapped.facts['rentSource'] == 'original_advertised'
    assert mapped.facts['rentMonthlySgdNow'] is None


def test_coordinates_and_inferred_error(sources):
    assert all(coordinates(listing) is not None for listing in sources['listings'])
    inferred = next(l for l in sources['listings'] if l.facts['coordSource'] == 'pg_poi_inferred')
    assert inferred.provenance['coordinates'] == 'derived'
    assert 'Approximate inferred' in location_note(inferred)
    if inferred.facts['coordErrorM'] is not None:
        assert 'estimated error' in location_note(inferred)
    invalid = replace(inferred, facts={**inferred.facts, 'latitude':float('nan')})
    assert coordinates(invalid) is None


def test_csv_types_and_zero_values():
    row = typed_record({'listing_id':'00123', 'postcode':'012345', 'bedrooms':'0',
                        'poi_library_1km':'0', 'area_sqm':'', 'coord_error_m':'165.5'})
    assert row == {'listing_id':'00123', 'postcode':'012345', 'bedrooms':0,
                   'poi_library_1km':0, 'area_sqm':None, 'coord_error_m':165.5}
    with pytest.raises(ValueError):
        typed_record({'bedrooms':'1.5'})
    with pytest.raises(ValueError):
        typed_record({'latitude':'inf'})
    assert typed_record({'coord_error_m':'~500'})['coord_error_m'] == '~500'


def test_v2_labels_normalized_without_losing_source(sources):
    listing = next(l for l in sources['listings'] if l.source_fields['cooking_policy'] == 'light_cooking')
    assert listing.facts['cookingPolicy'] == 'light_only'
    assert listing.provenance['cookingPolicy'] == 'derived'
    assert listing.source_fields['cooking_policy'] == 'light_cooking'
    assert any(l.facts['petsPolicy'] == 'not_allowed' and l.source_fields['pets_policy'] == 'no_pets' for l in sources['listings'])


@pytest.fixture
def small_bundle(tmp_path):
    rental = json.loads((DATA_ROOT/'rental_data_v1.json').read_text(encoding='utf-8'))
    row = rental['listings'][0]
    listing_id = row['listing_id']
    rental['listings'] = [row]
    rental['listing_metadata'] = [m for m in rental['listing_metadata'] if m['listing_id'] == listing_id]
    evidence = json.loads((DATA_ROOT/'source_evidence_v1.json').read_text(encoding='utf-8'))
    (tmp_path/'rental_data_v1.json').write_text(json.dumps(rental), encoding='utf-8')
    (tmp_path/'source_evidence_v1.json').write_text(json.dumps([e for e in evidence if e['listing_id'] == listing_id]), encoding='utf-8')
    for name in ('field_dictionary_v1.json', 'validation_report.json'):
        (tmp_path/name).write_text('{}', encoding='utf-8')
    latest = {**row, 'rent_monthly_sgd_now':1200, 'scrape_status':'active', 'enriched_at':'2026-10-04 16:21', 'latitude':1.3, 'longitude':103.8, 'coord_source':'onemap_postcode'}
    return tmp_path, latest


def write_csv(path, rows, fields=None):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize('problem', ['duplicate', 'missing_join', 'removed', 'inactive', 'missing_column', 'invalid_price'])
def test_invalid_snapshot_does_not_fall_back_to_v1(small_bundle, problem):
    root, row = small_bundle
    removed = []
    if problem == 'missing_join': row['listing_id'] = 'no-v1-evidence'
    if problem == 'inactive': row['scrape_status'] = 'removed'
    if problem == 'removed': removed = [{'listing_id':row['listing_id']}]
    if problem == 'missing_column': del row['latitude']
    if problem == 'invalid_price': row['rent_monthly_sgd_now'] = -1
    write_csv(root/'rental_data_v2.csv', [row, row] if problem == 'duplicate' else [row])
    write_csv(root/'removed_listings.csv', removed, fields=['listing_id'])
    with pytest.raises(ValueError, match='Unable to load required rental data'):
        read_sources(root)


def test_map_uses_data_coordinates_and_empty_map_has_no_markers(sources, monkeypatch):
    import streamlit as st
    from components import map_view
    from adapters.static_rental_api import StaticRentalApi
    import folium
    api = StaticRentalApi()
    captured = []
    monkeypatch.setattr(map_view, 'st_folium', lambda obj, **kwargs: captured.append(obj) or {})
    monkeypatch.setattr(st, 'caption', lambda *args, **kwargs: None)
    monkeypatch.setattr(st, 'warning', lambda *args, **kwargs: None)
    st.session_state.selected_listing = None
    map_view.map_view(api, listing_ids=[], compact=True)
    assert not any(isinstance(child, folium.Marker) for child in captured[-1]._children.values())
    listing = sources['listings'][0]
    map_view.map_view(api, listing_ids=[listing.id], compact=True)
    markers = [child for child in captured[-1]._children.values() if isinstance(child, folium.Marker)]
    assert len(markers) == 2  # Listing plus clearly labelled illustrative campus anchor.
    assert markers[-1].location == list(coordinates(listing))
    assert listing.id in captured[-1].get_root().render()
