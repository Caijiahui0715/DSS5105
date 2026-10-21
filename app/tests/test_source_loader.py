import pytest
from pathlib import Path
from adapters.backend_mapper import listing_images, safe_image_urls
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
