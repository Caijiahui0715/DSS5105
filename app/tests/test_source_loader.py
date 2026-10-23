import json
import pytest
from pathlib import Path
from adapters.backend_mapper import BackendMapper, listing_images, safe_image_urls
from data.source_loader import read_sources

def test_counts(sources):
    assert len(sources['listings']) == 327
    assert len(sources['metadata']) == 327
    assert len(sources['districts']) == 28
    assert sources['snapshot']['removed_count'] == 266
    assert sources['snapshot']['inferred_coordinates_count'] == 11

@pytest.mark.parametrize('value,expected',[(None,()),('broken',()),('{}',()),('["javascript:bad", null, 1]',()),('["https://example.com/image.jpg"]',('https://example.com/image.jpg',)),(['https://example.com/a','file:///secret'],('https://example.com/a',))])
def test_safe_images(value,expected):
    assert safe_image_urls(value) == expected

def test_listing_images_leave_out_agents_and_site_icons():
    agent = 'https://sg1-cdn.pgimgs.com/agent/12960381/APHO.160437683.164844421.V120B.jpg'
    icon = 'https://cdn.pgimgs.com/hive-ui/static/v0.1.137/pg-icons/font/v3/image-fallback.svg'
    project = 'https://sg1-cdn.pgimgs.com/projectnet-project/56782/ZPPHO.101796442.V800/Kent-Ridge.jpg'
    photo = 'https://sg1-cdn.pgimgs.com/listing/500253628/UPHO.161347572.V800/Chwee-Chian-View.jpg'
    plan = 'https://sg1-cdn.pgimgs.com/listing/500253628/UFLOO.145631751.V800.jpg'
    assert listing_images((), (agent, icon, project, photo, plan)) == (photo, plan, project)
    assert listing_images((photo,), (photo, agent)) == (photo,)
    assert listing_images((), (agent, icon)) == ()

def test_missing_required_data():
    with pytest.raises(ValueError,match='Unable to load required rental data'):
        read_sources(Path(__file__).resolve().parent/'nonexistent-source-directory')


def test_photos_in_the_data_come_before_the_source_record():
    photo = 'https://sg1-cdn.pgimgs.com/listing/1/UPHO.1.V800/home.jpg'
    project = 'https://sg1-cdn.pgimgs.com/projectnet-project/2/ZPPHO.2.V800/development.jpg'
    old = 'https://sg1-cdn.pgimgs.com/listing/1/UPHO.9.V800/old.jpg'
    row = {'listing_id': '1', 'title': 'Test', 'rent_monthly_sgd': 1000, 'rent_monthly_sgd_now': None}
    meta, district = {'availability_status': 'unknown', 'review_flags': []}, {'district': 'Test'}
    evidence = {'thumbnail_url': old, 'image_urls': json.dumps([old])}
    # The home's own photos first, then the development's.
    assert BackendMapper.listing({**row, 'photos': [project, photo]}, meta, district, evidence).images == (photo, project)
    # Without photos in the data, the source record's.
    assert BackendMapper.listing({**row, 'photos': []}, meta, district, evidence).images == (old,)
