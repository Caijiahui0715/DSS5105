import json
import csv
from data.source_loader import DATA_ROOT
from data.v2_mapping import typed_record, LABELS

def test_all_source_values_preserved(sources):
    rental = json.loads((DATA_ROOT/'rental_data_v1.json').read_text(encoding='utf-8'))
    evidence = json.loads((DATA_ROOT/'source_evidence_v1.json').read_text(encoding='utf-8'))
    meta = {row['listing_id']:row for row in rental['listing_metadata']}
    districts = {row['district_code']:row['district'] for row in rental['district_lookup']}
    ev = {row['listing_id']:row for row in evidence}
    with (DATA_ROOT/'rental_data_v2.csv').open(encoding='utf-8-sig', newline='') as handle:
        latest = {row['listing_id']: typed_record(row) for row in csv.DictReader(handle)}
    for listing in sources['listings']:
        row = latest[listing.id]
        assert listing.source_fields == row
        for key,value in row.items():
            parts = key.split('_')
            domain_key = parts[0]+''.join(part.capitalize() for part in parts[1:])
            assert listing.facts[domain_key] == LABELS.get(key, {}).get(value, value)
        assert listing.metadata['reviewFlags'] == meta[listing.id]['review_flags']
        assert listing.facts['districtName'] == districts[row['district_code']]
        assert listing.evidence['cardText'] == ev[listing.id]['card_text']
    assert all(listing.facts['scrapeStatus'] == 'active' for listing in sources['listings'])
    assert sum(l.facts['furnishing']=='unknown' for l in sources['listings']) == 1

def test_english_excerpts_preserve_originals(sources):
    import re
    for listing in sources['listings']:
        assert not re.search('[\u3400-\u9fff]',listing.facts['displayTitle'])
        assert listing.facts['displayTitle'] in listing.facts['title']
        if listing.facts['displayTitle'] != listing.facts['title']:
            assert listing.provenance['displayTitle']=='derived'
