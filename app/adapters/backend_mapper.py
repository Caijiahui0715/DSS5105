from urllib.parse import urlparse
import json
from domain.models import Listing
from domain.provenance import provenance_for
from data.v2_mapping import LABELS

def safe_image_urls(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return ()
    if not isinstance(value, list):
        return ()
    return tuple(url for url in value if isinstance(url, str) and urlparse(url).scheme in ('http', 'https') and urlparse(url).hostname)

# Listing pages also carry the agent's headshot and the site's own icons; neither shows the home.
_NOT_THE_HOME = ('/agent/', '/hive-ui')


def listing_images(thumbnail, images):
    """The pictures to show for a listing: its own photos first (the thumbnail, then the rest), then
    others such as the development's photos; agent headshots and site icons are left out."""
    urls = [url for url in dict.fromkeys((*thumbnail, *images)) if not any(part in urlparse(url).path for part in _NOT_THE_HOME)]
    return tuple(sorted(urls, key=lambda url: '/listing/' not in urlparse(url).path))


class BackendMapper:
    @staticmethod
    def listing(row, metadata, district, evidence):
        # UI uses domain keys; the original dictionary is never mutated.
        facts = {''.join([key.split('_')[0]] + [part.capitalize() for part in key.split('_')[1:]]): value for key, value in row.items()}
        facts['districtName'] = district['district']
        # Exact English excerpts already present in these two bilingual source
        # titles. Original titles remain untouched in the domain facts.
        english_excerpts = {'25024859':'Super Nice Classic House', '19877684':'Modern GCB at Maryland Drive for Rent'}
        facts['displayTitle'] = english_excerpts.get(str(row['listing_id']), row['title'])
        # The photos the V2 data lists, else those of the V1 source record.
        photos = safe_image_urls(row.get('photos'))
        images = listing_images((), photos) if photos else listing_images(safe_image_urls([evidence.get('thumbnail_url')]), safe_image_urls(evidence.get('image_urls')))
        meta = {'availabilityStatus': metadata['availability_status'], 'reviewFlags': list(metadata['review_flags'])}
        ev = {'cardText': evidence.get('card_text'), 'availabilityText': evidence.get('availability_text'), 'sourceUrl': evidence.get('source_url'), 'fieldEvidence': evidence.get('original_field_evidence'), 'ruleEvidence': evidence.get('rule_evidence')}
        provenance = {key: provenance_for(value) for key, value in {**facts, **meta, **ev}.items()}
        for source_key, labels in LABELS.items():
            parts = source_key.split('_')
            key = parts[0] + ''.join(part.capitalize() for part in parts[1:])
            value = facts.get(key)
            if value in labels:
                facts[key] = labels[value]
                provenance[key] = 'derived' if labels[value] != 'unknown' else 'unavailable'
        refreshed = facts.get('rentMonthlySgdNow')
        facts['effectiveRentMonthlySgd'] = refreshed if refreshed is not None else facts['rentMonthlySgd']
        facts['rentSource'] = 'refreshed_advertised' if refreshed is not None else 'original_advertised'
        provenance['effectiveRentMonthlySgd'] = provenance_for(facts['effectiveRentMonthlySgd'])
        provenance['rentSource'] = 'derived'
        if facts['displayTitle'] != row['title']:
            provenance['displayTitle'] = 'derived'
        provenance.update(images='source' if images else 'unavailable', coordinates='unavailable', commute='unavailable', score='mock')
        if facts.get('latitude') is not None and facts.get('longitude') is not None:
            kind = 'derived' if facts.get('coordSource') == 'pg_poi_inferred' else 'source'
            provenance.update(coordinates=kind, latitude=kind, longitude=kind)
        return Listing(str(row['listing_id']), facts, meta, ev, images, provenance, dict(row))
